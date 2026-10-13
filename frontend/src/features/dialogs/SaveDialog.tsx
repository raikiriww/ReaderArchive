import { type FormEvent, type KeyboardEvent, useEffect, useState } from "react";
import { Layers, Link as LinkIcon, X } from "lucide-react";
import type { ArchiveTag } from "../../types/domain";
import { hostSourceLabel } from "../../utils/format";
import { DialogOverlay } from "./ConfirmDialog";

export interface SaveDialogPayload {
  url: string;
  tags: string[];
  prepareManually: boolean;
}

export interface SaveDialogProps {
  initialUrl: string;
  /** Returns how many times this exact URL was saved before (count 0 = never). */
  existingUrls?: (url: string) => { count: number; latestAt?: string };
  tags: ArchiveTag[];
  /** Create the task. Throw to keep the dialog open with the URL intact (caller shows the error). */
  onSubmit: (payload: SaveDialogPayload) => Promise<void>;
  onClose: () => void;
}

/** http(s) URL with a host. */
export function isSavableUrl(value: string): boolean {
  const text = value.trim();
  if (!text || /\s/.test(text)) return false;
  try {
    const url = new URL(text);
    return (
      (url.protocol === "http:" || url.protocol === "https:") &&
      url.hostname.length > 0
    );
  } catch {
    return false;
  }
}

/** Short source label for a URL: known platforms by name, otherwise the hostname. */

function savedDateLabel(value: string | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const sameYear = date.getFullYear() === new Date().getFullYear();
  const day = `${date.getMonth() + 1}月${date.getDate()}日`;
  return sameYear ? day : `${date.getFullYear()}年${day}`;
}

export function modKeyLabel(): string {
  if (typeof navigator === "undefined") return "⌘";
  return /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent)
    ? "⌘"
    : "Ctrl";
}

export function SaveDialog({
  initialUrl,
  existingUrls,
  tags,
  onSubmit,
  onClose,
}: SaveDialogProps): JSX.Element {
  const [url, setUrl] = useState(initialUrl);
  const [prepareManually, setPrepareManually] = useState(false);
  const [chosenTags, setChosenTags] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setUrl(initialUrl);
  }, [initialUrl]);

  const clean = url.trim();
  const valid = isSavableUrl(clean);
  const existing = valid && existingUrls ? existingUrls(clean) : { count: 0 };
  const latest = savedDateLabel(existing.latestAt);
  const availableTags = tags.filter((tag) => !chosenTags.includes(tag.name));

  async function submit(): Promise<void> {
    if (!valid || busy) return;
    setBusy(true);
    try {
      await onSubmit({ url: clean, tags: chosenTags, prepareManually });
    } catch {
      // Keep the URL for retry; the caller presents the error.
    } finally {
      setBusy(false);
    }
  }

  function formSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    void submit();
  }

  function keyDown(event: KeyboardEvent<HTMLFormElement>): void {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <DialogOverlay onClose={onClose} placement="top" labelledBy="dlgSaveTitle">
      <form
        className="dlg-dialog dlg-save"
        autoComplete="off"
        onSubmit={formSubmit}
        onKeyDown={keyDown}
      >
        <h2 id="dlgSaveTitle">保存网页</h2>
        <div className={`dlg-url-field ${clean && !valid ? "dlg-bad" : ""}`}>
          <LinkIcon size={16} aria-hidden="true" />
          <input
            // biome-ignore lint/a11y/noAutofocus: the dialog opens to receive a URL
            autoFocus
            aria-label="网址"
            name="url"
            placeholder="粘贴网址"
            value={url}
            readOnly={busy}
            onChange={(event) => setUrl(event.target.value)}
          />
        </div>
        {clean && !valid ? (
          <p className="dlg-error">
            这不像一个完整的网址，请以 http:// 或 https:// 开头。
          </p>
        ) : null}
        {valid ? (
          <div className="dlg-detect">
            <span className="dlg-src-chip">{hostSourceLabel(clean)}</span>
            {existing.count > 0 ? (
              <span className="dlg-dup">
                <Layers size={13} aria-hidden="true" />
                这个网址已保存过 {existing.count} 次
                {latest ? `（最近 ${latest}）` : ""}，会另存一个新版本
              </span>
            ) : null}
          </div>
        ) : (
          <p className="dlg-help">
            也可以在任意位置直接按 {modKeyLabel()}V 粘贴网址。
          </p>
        )}
        {valid ? (
          <div className="dlg-save-tags">
            <span className="dlg-save-label">标签</span>
            {chosenTags.map((tag) => (
              <button
                key={tag}
                type="button"
                className="dlg-chip dlg-chip-on"
                title="移除"
                onClick={() =>
                  setChosenTags((items) => items.filter((item) => item !== tag))
                }
              >
                #{tag}
                <X size={11} aria-hidden="true" />
              </button>
            ))}
            {availableTags.length ? (
              <select
                className="dlg-tag-select"
                aria-label="添加标签"
                value=""
                onChange={(event) => {
                  const name = event.target.value;
                  if (name)
                    setChosenTags((items) =>
                      items.includes(name) ? items : [...items, name],
                    );
                }}
              >
                <option value="">
                  {chosenTags.length ? "再加一个…" : "添加标签（可选）"}
                </option>
                {availableTags.map((tag) => (
                  <option key={tag.name} value={tag.name}>
                    {tag.name}
                  </option>
                ))}
              </select>
            ) : chosenTags.length === 0 ? (
              <span className="dlg-quiet">还没有标签</span>
            ) : null}
          </div>
        ) : null}
        <label className="dlg-check dlg-prepare">
          <input
            type="checkbox"
            checked={prepareManually}
            disabled={busy}
            onChange={(event) => setPrepareManually(event.target.checked)}
          />
          <span>
            保存前手动处理
            <small>
              先在内置浏览器里关弹窗、展开全文或登录，再保存那个页面。只对这一次保存生效。
            </small>
          </span>
        </label>
        <div className="dlg-actions">
          <button className="dlg-btn" type="button" onClick={onClose}>
            取消
          </button>
          <button
            className="dlg-btn dlg-btn-primary"
            type="submit"
            disabled={!valid || busy}
          >
            {busy ? "提交中…" : prepareManually ? "打开并等待处理" : "保存"}
            {busy ? null : <kbd className="dlg-kbd">{modKeyLabel()}↩</kbd>}
          </button>
        </div>
      </form>
    </DialogOverlay>
  );
}
