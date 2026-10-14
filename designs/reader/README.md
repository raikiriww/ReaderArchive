# Reader 界面原型

这是 Reader Archive 网页界面的可交互原型，用 React 和浏览器内的 Babel 运行，不需要构建。界面规则以 [docs/product/interface.md](../../docs/product/interface.md) 为准。

## 运行

在仓库根目录执行：

```bash
python3 designs/serve_nocache.py 4311 designs
```

然后打开 <http://localhost:4311/reader/prototype.html>。`serve_nocache.py` 会禁用浏览器缓存，修改文件后刷新页面就能看到。Claude Code 的预览配置（`.claude/launch.json` 里的 `designs`）用的也是这个命令。

## 文件

| 文件 | 内容 |
|---|---|
| `prototype.html` | 入口页面 |
| `data.js` | 合成的示例存档 |
| `helpers.jsx` | 日期、来源、摘要等格式化函数 |
| `icons.jsx` | 图标 |
| `full-data.jsx` | 示例任务状态、订阅源、用户、设置，以及模拟搜索 |
| `full-ui.jsx` | 侧栏、列表、阅读窗口、示例快照、正文视图、状态面板 |
| `full-dialogs.jsx` | 保存网页、订阅源、设置、快捷键等弹窗 |
| `full-app.jsx` | 应用状态、快捷键、Tweaks |
| `base.css`、`proto.css` | 样式 |

## 模拟的部分

- 存档快照是示意页面，不是真实的 SingleFile 文件。
- 保存流程用定时器模拟。「意思可能相关」的搜索用二字词重叠近似。
- 数据保存在浏览器的 localStorage 里。右下角 Tweaks 里的「恢复原型数据」可以还原。
- Tweaks 里的打开方式、配色、密度开关只用来对比，正式界面只实现默认选项。
