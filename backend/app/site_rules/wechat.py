from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from app.models import (
    ManualActionKind,
    ManualActionRead,
    ManualActionResume,
    ManualActionTarget,
)
from app.site_rules.base import ArchiveInspection

MAX_INSPECTION_BYTES = 2 * 1024 * 1024


class _WeChatSignalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.element_ids: set[str] = set()
        self.text_parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        for name, value in attrs:
            if name == "id" and value:
                self.element_ids.add(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.text_parts.append(data)


class WeChatArticleRule:
    rule_id = "wechat.mp_article"

    def matches_url(self, url: str) -> bool:
        return (urlparse(url).hostname or "").lower() == "mp.weixin.qq.com"

    def prepare_archive(self, url: str, archive_path: Path) -> None:
        # Normal articles use the same SingleFile capture path as every other site.
        return None

    def inspect(self, url: str, archive_path: Path) -> ArchiveInspection | None:
        parser = _WeChatSignalParser()
        content = archive_path.read_bytes()[:MAX_INSPECTION_BYTES]
        parser.feed(content.decode("utf-8", errors="replace"))
        text = " ".join(" ".join(parser.text_parts).split())

        has_verification_message = (
            "环境异常" in text and "完成验证后即可继续访问" in text
        )
        has_verification_control = "js_verify" in parser.element_ids or any(
            element_id.startswith("tcaptcha_") for element_id in parser.element_ids
        )
        captcha_path = urlparse(url).path.rstrip("/") == "/mp/wappoc_appmsgcaptcha"
        if (has_verification_message and has_verification_control) or captcha_path:
            return ArchiveInspection(
                manual_actions=(
                    ManualActionRead(
                        code="wechat_article_verification",
                        kind=ManualActionKind.VERIFICATION,
                        target=ManualActionTarget.PAGE,
                        message="微信要求完成访问验证，正文尚未保存。",
                        resume=ManualActionResume.RETRY_PAGE,
                        rule_id=f"{self.rule_id}.verification",
                    ),
                )
            )

        if "此内容暂时无法查看" in text:
            return ArchiveInspection(error="微信文章内容暂时无法查看。")
        return None
