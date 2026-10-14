# 文档索引

`docs/` 是项目说明的唯一来源。新增、移动或删除文档时，同步更新本页。

## 文档

| 文档 | 内容 |
|---|---|
| [product/interface.md](product/interface.md) | 当前界面规则：侧栏、未读、筛选、阅读窗口、已读、快捷键、保存、订阅源 |
| [design/search/](design/search/README.md) | 搜索升级的方案与验收（已实施） |
| [design/pdf-archive/](design/pdf-archive/README.md) | PDF 直链归档（已实施） |
| [design/manual-action/](design/manual-action/README.md) | 手动处理状态与网站规则（已实施） |
| [acceptance/release-20260905.md](acceptance/release-20260905.md) | 2026-09-05 本地发版验收 |
| [releases/](releases/) | 各版本的发布说明 |
| [images/](images/) | README 截图（只用示例数据） |
| [../designs/reader/](../designs/reader/README.md) | 可交互界面原型 |

## 阅读路线

| 你要做什么 | 先读 |
|---|---|
| 修改界面 | [product/interface.md](product/interface.md)、[designs/reader/AGENTS.md](../designs/reader/AGENTS.md) |
| 修改搜索或语义检索 | [design/search/](design/search/README.md) |
| 修改保存流程、网站规则、手动处理 | [design/manual-action/](design/manual-action/README.md)、[design/pdf-archive/](design/pdf-archive/README.md) |
| 修改 Docker 镜像或 compose | 根目录 [AGENTS.md](../AGENTS.md) 的 Docker 规则 |
| 发布新版本 | [acceptance/](acceptance/release-20260905.md)、[releases/](releases/) |

## 写作规则

- **一个主题一篇文档。** 多篇文档的主题放进 `design/<主题>/`，用 `README.md` 做入口并写明状态（方案稿、实施中、已实施）。
- **一件事只写在一处。** 其他地方链接过去，不复制。
- **整合，不追加。** 规则变了就改原文，不在末尾追加「更新」。
- **写规则，不写过程。** 讨论过程和历史留在 git 和 PR 里。验收记录除外，它本身就是结果。
- **放置**：当前产品行为放 `product/`，方案和实施记录放 `design/<主题>/`，验收结果放 `acceptance/`，发布说明放 `releases/`。
- **待定问题写在文档末尾**，用「待定」小节列出，确定后并入正文。
- 文档、截图和原型都不能包含真实用户数据。
