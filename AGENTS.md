# AGENTS.md

## 按需阅读

| 你要做什么 | 先读 |
|---|---|
| 了解有哪些文档 | [docs/README.md](docs/README.md) |
| 修改界面 | [docs/product/interface.md](docs/product/interface.md)、[designs/reader/AGENTS.md](designs/reader/AGENTS.md) |
| 修改搜索 | [docs/design/search/](docs/design/search/README.md) |
| 修改保存流程或网站规则 | [docs/design/manual-action/](docs/design/manual-action/README.md)、[docs/design/pdf-archive/](docs/design/pdf-archive/README.md) |
| 写或改文档 | [docs/README.md](docs/README.md) 的写作规则 |
| 修改 Docker 镜像或 compose | 下面的 Docker/部署兼容性 |

本仓库是公开的。代码、文档、截图和原型都不能包含真实用户数据。

## Docker/部署兼容性

修改容器运行行为时，优先把默认值放进镜像或应用自身，不要只依赖 compose 文件新增环境变量或启动参数。

如果一个改动只是增加默认参数、默认路径、默认端口、默认开关，那么用户拉取新镜像后应当尽量直接生效，不应该强制用户同步新版 compose 文件。

compose 文件里的配置应主要作为“覆盖默认值”的入口，而不是让新功能能否工作所必需的条件。

如果确实必须修改 compose 文件才能生效，需要在交付前明确说明原因、影响范围和用户需要执行的具体操作。
