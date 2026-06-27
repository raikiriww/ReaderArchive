from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlmodel import Session

from app.core.config import Settings
from app.core.db import get_engine
from app.crud import ArchiveTaskRepository
from app.models import ArchiveTaskSourceType
from app.semantic import LocalEmbeddingProvider, SemanticDocumentPreparer, semantic_texts_for_embedding


@dataclass(frozen=True)
class EvalArticle:
    task_id: str
    title: str
    url: str
    tags: tuple[str, ...]
    paragraphs: tuple[str, ...]
    source_type: ArchiveTaskSourceType = ArchiveTaskSourceType.MANUAL
    source_title: str | None = None


@dataclass(frozen=True)
class EvalQuery:
    query: str
    expected: tuple[str, ...]
    kind: str


ARTICLES: tuple[EvalArticle, ...] = (
    EvalArticle(
        "work-ai-vacation",
        "今天可以放假吗",
        "https://reader.eval/articles/work-ai-vacation",
        ("work", "ai", "benefits"),
        (
            "一家团队开始使用 AI 工具以后，白领工作效率明显提高。过去需要一周完成的分析、文档和整理任务，现在几个小时就能完成。",
            "文章讨论的问题不是偷懒，而是如果员工用更少时间完成同样成果，公司是否应该把节省出来的生产率转化成休息、福利或者更短的工作周。",
            "它提出一种朴素判断：当 AI 让工作更快完成时，今天可以放假吗，或者至少可以少上一天班吗。",
        ),
    ),
    EvalArticle(
        "rsync-debate",
        "rsync 的争论",
        "https://reader.eval/articles/rsync-debate",
        ("tools", "open-source"),
        (
            "rsync 是一个历史很长的命令行同步工具，很多脚本、服务器和备份流程依赖它稳定工作。",
            "争论的焦点在于老工具应该优先保持兼容，还是接受现代替代方案带来的更好体验、协议和安全设计。",
            "开源维护者还要面对文档、缺陷修复、发行节奏和用户期望之间的长期拉扯。",
        ),
    ),
    EvalArticle(
        "local-llm-cost",
        "本地模型的成本",
        "https://reader.eval/articles/local-llm-cost",
        ("local", "model"),
        (
            "本地模型适合隐私敏感和离线场景，不需要把查询发到外部服务，也不用依赖网络可用性。",
            "本地向量数据库可以和本地模型一起跑，把文章片段和查询都留在个人设备或自有服务器里。",
            "很多人会问，向量数据库能不能放在本地跑；答案通常是可以，但要接受资源占用和维护成本。",
            "代价是硬件、内存、磁盘和启动时间都需要自己承担。轻量模型在 CPU 上能跑，但效果和速度要按具体任务评估。",
            "对于个人阅读归档，模型不联网搜索文章是一种可接受的折中。",
        ),
    ),
    EvalArticle(
        "pgvector-search",
        "PostgreSQL 向量检索实践",
        "https://reader.eval/articles/pgvector-search",
        ("postgres", "search"),
        (
            "PostgreSQL 可以通过向量扩展保存文本片段的向量表示，并使用索引进行相似内容搜索。",
            "实际做法是把长文章切成正文片段，为每段生成向量，然后用用户输入生成一个查询向量。",
            "This is a local vector database pattern for semantic search when the archive already uses PostgreSQL.",
            "pgvector 和 HNSW 索引可以让本地语义检索保持简单，数据也继续留在同一个数据库里。",
        ),
    ),
    EvalArticle(
        "rss-reading-flow",
        "RSS 阅读流整理",
        "https://reader.eval/articles/rss-reading-flow",
        ("rss", "reading"),
        (
            "订阅源会不断带来新文章，阅读器需要区分未读、已读、稍后读和已经归档的内容。",
            "一个好的 RSS 阅读流会让用户快速筛选主题、保存重要文章，并在以后通过标题、标签和正文重新找到它们。",
            "未读和已读管理不是装饰功能，而是长期阅读积累时避免混乱的关键。",
        ),
    ),
    EvalArticle(
        "apple-motion-cues",
        "车辆运动提示",
        "https://reader.eval/articles/apple-motion-cues",
        ("apple", "mobile"),
        (
            "iPhone 的车辆运动提示功能会在屏幕边缘显示随车辆移动变化的小点，用视觉线索缓解乘车时的不适。",
            "这个功能常被用来解释手机防晕车设计：它不是药物，而是让眼睛看到的运动和身体感受到的运动更一致。",
            "移动场景里的无障碍设计往往来自这些很小但具体的体验改进。",
        ),
    ),
    EvalArticle(
        "semantic-short-word",
        "短词搜索为什么不稳定",
        "https://reader.eval/articles/semantic-short-word",
        ("search", "quality"),
        (
            "语义模型更擅长处理完整句子和自然语言问题，不擅长只靠一个很短的关键词判断用户意图。",
            "短词搜索应该优先走精确匹配和正文命中，因为词本身已经很明确。",
            "如果完全依赖语义相似度，放假、预算、测试这种短词很容易被模型判得过低或者误判到别的主题。",
        ),
    ),
    EvalArticle(
        "security-ai-patches",
        "AI 修补开源漏洞",
        "https://reader.eval/articles/security-ai-patches",
        ("security", "ai"),
        (
            "AI 发现漏洞的能力提升以后，开源项目可能收到更多安全报告和自动生成的补丁。",
            "这会改变维护者的工作重心：他们不只是写代码，还要验证补丁、补测试、判断风险。",
            "自动修补漏洞听起来节省人力，但如果缺少审核流程，也可能给开源维护带来新的压力。",
        ),
    ),
    EvalArticle(
        "vac-travel-plan",
        "珠海音乐节出行计划",
        "https://reader.eval/articles/vac-travel-plan",
        ("travel", "music"),
        (
            "去珠海参加音乐节需要提前确认演出时间、交通路线、住宿地点和散场后的返程方式。",
            "如果主舞台演出持续到深夜，最好把酒店订在交通方便的位置，并预留排队和打车时间。",
            "这篇文章关注的是行程安排，而不是音乐评论。",
        ),
    ),
    EvalArticle(
        "recipe-tomato-eggs",
        "番茄炒蛋做法",
        "https://reader.eval/articles/recipe-tomato-eggs",
        ("cooking",),
        (
            "番茄炒蛋的关键是先把鸡蛋炒到蓬松，再用番茄炒出汁水。",
            "可以加一点盐和糖调整酸甜，最后把鸡蛋回锅，让蛋块吸收番茄汤汁。",
            "这是一篇做饭步骤文章，用来测试无关主题不会干扰技术搜索。",
        ),
    ),
    EvalArticle(
        "finance-budget",
        "家庭预算表",
        "https://reader.eval/articles/finance-budget",
        ("finance",),
        (
            "家庭预算表把收入、固定账单、日常支出和储蓄目标放在一起。",
            "每月底复盘消费分类，可以看出餐饮、交通、订阅服务和临时购物是否超出预期。",
            "这个样例用于测试财务内容是否会被错误匹配到技术主题。",
        ),
    ),
    EvalArticle(
        "python-testing",
        "Python 测试实践",
        "https://reader.eval/articles/python-testing",
        ("python", "testing"),
        (
            "测试数据应该覆盖正常路径、边界情况和容易回归的问题。",
            "在搜索功能里，固定查询和预期结果可以帮助判断改动是否提升了质量，而不是只看单个例子。",
            "写测试数据验证搜索质量时，最好同时保存输入、目标结果、实际排名和命中片段。",
        ),
    ),
    EvalArticle(
        "docker-isolation",
        "Docker 隔离环境",
        "https://reader.eval/articles/docker-isolation",
        ("docker", "test"),
        (
            "独立评测环境应该使用单独数据库、单独端口和单独数据卷，避免污染真实数据。",
            "Docker 可以让服务和数据库保持运行，方便反复灌入测试数据和调试搜索结果。",
            "评测结束后保留容器，有利于复现同一批查询。",
        ),
    ),
    EvalArticle(
        "browser-automation",
        "浏览器自动化验证",
        "https://reader.eval/articles/browser-automation",
        ("browser", "test"),
        (
            "页面功能不能只靠接口判断，还需要打开浏览器检查搜索框、按钮、筛选和结果片段。",
            "浏览器自动化验证会实际登录页面，输入查询，切换未读和全部，确认页面状态符合预期。",
            "对于 Reader 这种应用，搜索和筛选的交互验证尤其重要。",
        ),
    ),
    EvalArticle(
        "english-ai-workweek",
        "AI and the shorter workweek",
        "https://reader.eval/articles/english-ai-workweek",
        ("english", "work", "ai"),
        (
            "AI tools can compress a week of routine knowledge work into a much shorter block of focused effort.",
            "The article asks whether productivity gains should become a shorter workweek, more flexible schedules, or better employee benefits.",
            "It is an English counterpart to the Chinese discussion about taking time off when AI makes work faster.",
        ),
    ),
    EvalArticle(
        "english-vector-db",
        "Vector databases for local search",
        "https://reader.eval/articles/english-vector-db",
        ("english", "vector", "search"),
        (
            "A local vector database stores embeddings for document chunks and compares them with an embedding of the user's query.",
            "这类本地向量数据库也可以放在本地跑，用来支持个人归档里的语义搜索。",
            "For personal archives, local semantic search can avoid external APIs while still finding related passages by meaning.",
            "The tradeoff is that small CPU-friendly models may need keyword search as a fallback.",
        ),
    ),
    EvalArticle(
        "mixed-rss-ai",
        "RSS and AI 摘要工作流",
        "https://reader.eval/articles/mixed-rss-ai",
        ("rss", "ai", "summary"),
        (
            "An RSS summary workflow can collect feeds, archive articles, and then use AI to create short reading notes.",
            "中文阅读场景里，摘要不是替代原文，而是帮助用户快速判断哪些文章值得稍后读。",
            "这个中英混合样例用于测试 RSS summary workflow with AI 这类查询。",
        ),
    ),
    EvalArticle(
        "mobile-siri-wwdc",
        "Siri 发布会细节",
        "https://reader.eval/articles/mobile-siri-wwdc",
        ("apple", "siri"),
        (
            "发布会上反复提到 Siri，但现场听众的手机没有被误唤醒。",
            "这说明演示环境可能做了特殊处理，也说明语音唤醒在大型发布会里需要防误触设计。",
            "这篇文章和车辆运动提示一样属于移动体验细节。",
        ),
    ),
    EvalArticle(
        "open-source-credit",
        "没发生的问题没人记得",
        "https://reader.eval/articles/open-source-credit",
        ("engineering", "maintenance"),
        (
            "很多工程工作是在预防问题，真正成功时，用户往往什么都感觉不到。",
            "修复还没发生的事故、改进备份和补齐监控，通常很难获得和新功能一样的可见认可。",
            "这篇文章用于区分维护价值和功能发布的不同评价方式。",
        ),
    ),
    EvalArticle(
        "team-communication",
        "AI 内容要尊重注意力",
        "https://reader.eval/articles/team-communication",
        ("communication", "ai"),
        (
            "把 AI 生成内容直接丢给同事，会消耗对方注意力，也让沟通责任变得模糊。",
            "更好的做法是标注哪些内容来自 AI，附上自己的判断、摘要和需要对方关注的问题。",
            "团队沟通里，尊重注意力比展示生成速度更重要。",
        ),
    ),
    EvalArticle(
        "frontend-state",
        "前端状态管理小结",
        "https://reader.eval/articles/frontend-state",
        ("frontend",),
        (
            "前端页面里的搜索词、筛选条件和选中记录需要保持同步，否则用户会看到旧结果。",
            "状态管理应该让输入框、列表和详情面板之间的关系清楚可预测。",
        ),
    ),
    EvalArticle(
        "database-migration",
        "数据库迁移 checklist",
        "https://reader.eval/articles/database-migration",
        ("database",),
        (
            "数据库迁移前需要确认备份、扩展、索引和回滚路径。",
            "从 SQLite 切换到 PostgreSQL 后，评测环境也应该使用同样的数据库能力。",
        ),
    ),
    EvalArticle(
        "video-archive",
        "视频归档注意事项",
        "https://reader.eval/articles/video-archive",
        ("video",),
        (
            "视频归档需要处理下载格式、封面、描述文件和登录受限页面。",
            "这个样例用于干扰普通网页搜索，不应该命中向量数据库查询。",
        ),
    ),
    EvalArticle(
        "reading-habits",
        "长期阅读习惯",
        "https://reader.eval/articles/reading-habits",
        ("reading",),
        (
            "长期阅读不是保存越多越好，而是能否重新找到重要内容。",
            "标签、正文片段、归档时间和搜索质量共同决定一个阅读系统是否可持续。",
        ),
    ),
    EvalArticle(
        "cpu-performance",
        "CPU 上的嵌入模型性能",
        "https://reader.eval/articles/cpu-performance",
        ("cpu", "model"),
        (
            "轻量嵌入模型可以在 CPU 上运行，适合个人设备和本地服务。",
            "批量生成向量比逐条生成更高效，后台处理也应该限制并发，避免影响页面响应。",
        ),
    ),
    EvalArticle(
        "privacy-archive",
        "私人归档的隐私边界",
        "https://reader.eval/articles/privacy-archive",
        ("privacy",),
        (
            "个人归档里可能包含阅读偏好、账户页面和私密资料。",
            "本地检索减少外部调用，但仍然要注意数据库、备份和浏览器配置目录的权限。",
        ),
    ),
    EvalArticle(
        "music-review",
        "电子音乐现场评论",
        "https://reader.eval/articles/music-review",
        ("music",),
        (
            "电子音乐现场的重点是音响、灯光、节奏推进和观众情绪。",
            "这篇文章和珠海音乐节行程相近，但更关注演出体验而不是交通住宿安排。",
        ),
    ),
    EvalArticle(
        "shopping-laptop",
        "购买笔记本电脑清单",
        "https://reader.eval/articles/shopping-laptop",
        ("shopping",),
        (
            "购买笔记本电脑前可以比较重量、屏幕、内存、续航和售后。",
            "这是一篇消费决策文章，用来测试它不会被误认为本地模型部署指南。",
        ),
    ),
    EvalArticle(
        "markdown-notes",
        "Markdown 笔记整理",
        "https://reader.eval/articles/markdown-notes",
        ("notes",),
        (
            "Markdown 适合保存阅读笔记、摘录和链接。",
            "如果笔记和网页归档能一起搜索，用户更容易从旧资料里找到上下文。",
        ),
    ),
    EvalArticle(
        "mars-insurance-decoy",
        "火星殖民保险条款",
        "https://reader.eval/articles/mars-insurance-decoy",
        ("decoy",),
        (
            "这是一篇刻意设置的无关文章，讨论火星殖民基地的保险条款和星际运输赔付。",
            "它不应该因为个别词相似就出现在 Reader 语义检索的常规结果里。",
        ),
    ),
)


QUERIES: tuple[EvalQuery, ...] = (
    EvalQuery("放假", ("work-ai-vacation",), "keyword"),
    EvalQuery("今天可以放假吗", ("work-ai-vacation",), "keyword"),
    EvalQuery("AI 提高效率以后能不能少上一天班", ("work-ai-vacation", "english-ai-workweek"), "rewrite"),
    EvalQuery("工作几小时完成一周任务", ("work-ai-vacation", "english-ai-workweek"), "rewrite"),
    EvalQuery("员工因为 AI 变高效后应该获得什么福利", ("work-ai-vacation",), "rewrite"),
    EvalQuery("rsync 为什么有人争论", ("rsync-debate",), "rewrite"),
    EvalQuery("老工具兼容性和现代替代方案", ("rsync-debate",), "rewrite"),
    EvalQuery("PostgreSQL 怎么做相似内容搜索", ("pgvector-search",), "rewrite"),
    EvalQuery("向量数据库能不能放在本地跑", ("pgvector-search", "english-vector-db", "local-llm-cost"), "rewrite"),
    EvalQuery("本地模型不联网搜索文章", ("local-llm-cost", "english-vector-db"), "rewrite"),
    EvalQuery("RSS 文章怎么管理未读已读", ("rss-reading-flow",), "rewrite"),
    EvalQuery("稍后读和订阅源整理", ("rss-reading-flow",), "rewrite"),
    EvalQuery("iPhone 防晕车功能", ("apple-motion-cues",), "rewrite"),
    EvalQuery("车辆运动提示是什么", ("apple-motion-cues",), "rewrite"),
    EvalQuery("短词为什么搜不到语义结果", ("semantic-short-word",), "rewrite"),
    EvalQuery("AI 自动修补漏洞会影响开源维护吗", ("security-ai-patches",), "rewrite"),
    EvalQuery("珠海音乐节怎么安排行程", ("vac-travel-plan",), "rewrite"),
    EvalQuery("番茄炒蛋", ("recipe-tomato-eggs",), "keyword"),
    EvalQuery("how AI changes the workweek", ("english-ai-workweek", "work-ai-vacation"), "english"),
    EvalQuery("local vector database for semantic search", ("english-vector-db", "pgvector-search"), "english"),
    EvalQuery("RSS summary workflow with AI", ("mixed-rss-ai", "rss-reading-flow"), "english"),
    EvalQuery("写测试数据验证搜索质量", ("python-testing", "semantic-short-word"), "rewrite"),
    EvalQuery("浏览器里验证搜索和筛选", ("browser-automation",), "rewrite"),
    EvalQuery("地下停车场潮湿除味方案", tuple(), "unrelated"),
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed and run Reader semantic search evaluation.")
    parser.add_argument("command", choices=("seed", "run", "seed-and-run"))
    args = parser.parse_args()

    if args.command in {"seed", "seed-and-run"}:
        seed()
    if args.command in {"run", "seed-and-run"}:
        run()


def seed() -> None:
    settings = Settings()
    reset_database(settings)
    settings.archive_dir.mkdir(parents=True, exist_ok=True)

    repository = ArchiveTaskRepository(settings.database_url)
    preparer = SemanticDocumentPreparer(
        min_chars=settings.semantic_chunk_min_chars,
        max_chars=settings.semantic_chunk_max_chars,
        overlap_chars=settings.semantic_chunk_overlap_chars,
    )
    provider = LocalEmbeddingProvider(settings)
    provider.preload()

    seeded = 0
    chunks_total = 0
    for article in ARTICLES:
        output_file = f"{article.task_id}.html"
        path = settings.archive_dir / output_file
        path.write_text(render_article_html(article), encoding="utf-8")

        repository.create(
            article.task_id,
            article.url,
            output_file,
            normalized_url=article.url,
            source_type=article.source_type,
            source_title=article.source_title,
            entry_title=article.title,
        )
        repository.mark_running(article.task_id)
        repository.mark_succeeded(article.task_id)
        repository.replace_task_tags(article.task_id, list(article.tags))

        prepared = preparer.prepare(path)
        if prepared is None:
            raise RuntimeError(f"Failed to prepare semantic chunks for {article.task_id}")
        texts = semantic_texts_for_embedding(article.title, prepared.chunks)
        embeddings = embed_batches(provider, texts, settings.semantic_batch_size)
        if len(embeddings) != len(prepared.chunks):
            raise RuntimeError(f"Embedding count mismatch for {article.task_id}")
        repository.replace_semantic_chunks(
            article.task_id,
            provider.model_name,
            settings.semantic_embedding_dimensions,
            settings.semantic_text_version,
            prepared.document_hash,
            prepared.chunks,
            embeddings,
        )
        seeded += 1
        chunks_total += len(prepared.chunks)

    print(json.dumps({"seeded_articles": seeded, "semantic_chunks": chunks_total}, ensure_ascii=False))


def run() -> None:
    base_url = os.environ.get("READER_EVAL_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    username = os.environ.get("READER_EVAL_USERNAME", "admin")
    password = os.environ.get("READER_EVAL_PASSWORD", "change-me")
    results_dir = Path(os.environ.get("READER_EVAL_RESULTS_DIR", "/app/eval-results"))
    results_dir.mkdir(parents=True, exist_ok=True)

    client = EvalHttpClient(base_url)
    client.login(username, password)

    case_results = []
    durations = []
    for query in QUERIES:
        started = time.perf_counter()
        results = client.search(query.query)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        durations.append(duration_ms)
        case_results.append(evaluate_case(query, results, duration_ms))

    summary = build_summary(case_results, durations)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "article_count": len(ARTICLES),
        "query_count": len(QUERIES),
        "summary": summary,
        "cases": case_results,
    }
    (results_dir / "semantic-eval.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (results_dir / "semantic-eval.md").write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


def reset_database(settings: Settings) -> None:
    engine = get_engine(settings.database_url)
    with Session(engine) as session:
        session.execute(
            text(
                """
                TRUNCATE TABLE
                    reader_archive_semantic_chunks,
                    reader_archive_semantic_indexes,
                    reader_archive_task_tags,
                    reader_archive_files,
                    reader_rss_entries,
                    reader_rss_sources,
                    reader_archive_tasks,
                    reader_tags
                RESTART IDENTITY CASCADE
                """
            )
        )
        session.commit()

    if settings.archive_dir.exists():
        for path in settings.archive_dir.glob("*.html"):
            path.unlink(missing_ok=True)


def embed_batches(
    provider: LocalEmbeddingProvider,
    chunks: list[str],
    batch_size: int,
) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for index in range(0, len(chunks), batch_size):
        embeddings.extend(provider.embed(chunks[index : index + batch_size]))
    return embeddings


def render_article_html(article: EvalArticle) -> str:
    body = "\n".join(f"<p>{escape(paragraph)}</p>" for paragraph in article.paragraphs)
    return (
        "<!doctype html><html><head>"
        f"<meta charset=\"utf-8\"><title>{escape(article.title)}</title>"
        "</head><body>"
        f"<article><h1>{escape(article.title)}</h1>{body}</article>"
        "</body></html>"
    )


class EvalHttpClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.cookie_jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.access_token: str | None = None

    def login(self, username: str, password: str) -> None:
        response = self.request_json(
            "POST",
            "/api/v1/auth/login",
            {"username": username, "password": password},
            authorize=False,
        )
        self.access_token = str(response["access_token"])

    def search(self, query: str) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode(
            {
                "include_read": "true",
                "limit": "50",
                "q": query,
            }
        )
        response = self.request_json("GET", f"/api/v1/archive-tasks?{params}")
        if not isinstance(response, list):
            raise RuntimeError("Search endpoint returned a non-list response.")
        return response

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        authorize: bool = True,
    ) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if authorize and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} for {method} {path}: {detail}") from exc


def evaluate_case(
    query: EvalQuery,
    results: list[dict[str, Any]],
    duration_ms: float,
) -> dict[str, Any]:
    top_results = [
        {
            "rank": index + 1,
            "task_id": str(item["task_id"]),
            "title": str(item.get("display_title") or ""),
            "excerpt": str((item.get("search_match") or {}).get("excerpt") or ""),
        }
        for index, item in enumerate(results[:5])
    ]
    top_ids = [item["task_id"] for item in top_results]
    expected_ranks = {
        expected_id: (top_ids.index(expected_id) + 1 if expected_id in top_ids else None)
        for expected_id in query.expected
    }

    if query.kind == "unrelated":
        passed = len(top_results) == 0
        reason = "no results" if passed else "unexpected results"
    elif query.kind == "keyword":
        passed = bool(top_results and top_results[0]["task_id"] == query.expected[0])
        reason = "primary result is first" if passed else "primary result is not first"
    else:
        top3 = set(top_ids[:3])
        passed = all(expected_id in top3 for expected_id in query.expected)
        reason = "all expected results are in top 3" if passed else "expected result missing from top 3"

    return {
        "query": query.query,
        "kind": query.kind,
        "expected": list(query.expected),
        "expected_ranks": expected_ranks,
        "duration_ms": duration_ms,
        "passed": passed,
        "reason": reason,
        "top_results": top_results,
    }


def build_summary(case_results: list[dict[str, Any]], durations: list[float]) -> dict[str, Any]:
    expected_cases = [case for case in case_results if case["kind"] != "unrelated"]
    top1_hits = 0
    top3_hits = 0
    for case in expected_cases:
        expected = case["expected"]
        top_ids = [result["task_id"] for result in case["top_results"]]
        if expected and top_ids and top_ids[0] == expected[0]:
            top1_hits += 1
        if expected and expected[0] in top_ids[:3]:
            top3_hits += 1

    unrelated_cases = [case for case in case_results if case["kind"] == "unrelated"]
    unrelated_false_positives = sum(1 for case in unrelated_cases if case["top_results"])
    passed_cases = sum(1 for case in case_results if case["passed"])
    return {
        "passed_cases": passed_cases,
        "failed_cases": len(case_results) - passed_cases,
        "top1_accuracy": round(top1_hits / len(expected_cases), 4) if expected_cases else 0,
        "top3_accuracy": round(top3_hits / len(expected_cases), 4) if expected_cases else 0,
        "unrelated_false_positives": unrelated_false_positives,
        "average_duration_ms": round(sum(durations) / len(durations), 2) if durations else 0,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Reader Semantic Search Evaluation",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Articles: `{payload['article_count']}`",
        f"- Queries: `{payload['query_count']}`",
        f"- Passed cases: `{summary['passed_cases']}`",
        f"- Failed cases: `{summary['failed_cases']}`",
        f"- Top 1 accuracy: `{summary['top1_accuracy']}`",
        f"- Top 3 accuracy: `{summary['top3_accuracy']}`",
        f"- Unrelated false positives: `{summary['unrelated_false_positives']}`",
        f"- Average duration: `{summary['average_duration_ms']} ms`",
        "",
        "| Query | Expected | Top results | Pass | Reason |",
        "|---|---|---|---|---|",
    ]
    for case in payload["cases"]:
        top_results = "<br>".join(
            f"{result['rank']}. {result['task_id']} — {escape_markdown(result['excerpt'][:90])}"
            for result in case["top_results"]
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_markdown(case["query"]),
                    ", ".join(case["expected"]) or "(none)",
                    top_results or "(none)",
                    "yes" if case["passed"] else "no",
                    escape_markdown(case["reason"]),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def escape_markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    main()
