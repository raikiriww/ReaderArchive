import { X } from "lucide-react";
import { DialogOverlay } from "./ConfirmDialog";
import { modKeyLabel } from "./SaveDialog";

export function shortcutRows(mod = modKeyLabel()): Array<[string, string]> {
  return [
    ["J / K", "下一条 / 上一条"],
    ["Enter", "打开当前条目"],
    ["⇧ Enter", "在新标签页阅读"],
    ["Esc", "关闭阅读窗口 / 清除搜索"],
    ["E", "切换已读 / 未读"],
    ["T", "添加标签"],
    ["R", "修改名称"],
    ["V", "切换 原貌 / 正文"],
    ["I", "详情、文件、重新归档"],
    ["O", "打开原网页"],
    ["N", "保存网页"],
    [`${mod}V`, "在任意位置粘贴网址即可保存"],
    [`/ 或 ${mod}K`, "搜索"],
    ["?", "显示这个面板"],
  ];
}

export interface ShortcutHelpProps {
  onClose: () => void;
}

export function ShortcutHelp({ onClose }: ShortcutHelpProps): JSX.Element {
  return (
    <DialogOverlay onClose={onClose} labelledBy="dlgHelpTitle">
      <div className="dlg-dialog dlg-help-dialog">
        <header className="dlg-help-head">
          <h2 id="dlgHelpTitle">键盘快捷键</h2>
          <button
            className="dlg-icon-btn"
            type="button"
            aria-label="关闭"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </header>
        <dl>
          {shortcutRows().map(([keys, label]) => (
            <div className="dlg-help-row" key={keys}>
              <dt>
                <kbd className="dlg-kbd">{keys}</kbd>
              </dt>
              <dd>{label}</dd>
            </div>
          ))}
        </dl>
      </div>
    </DialogOverlay>
  );
}
