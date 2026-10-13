// Shortcut table and helpers for the list shell. See docs/frontend-redesign-plan.md §1.1 「快捷键」.

export type ShortcutAction =
  | "next"
  | "prev"
  | "open"
  | "openTab"
  | "toggleRead"
  | "focusTags"
  | "rename"
  | "toggleMode"
  | "toggleDetails"
  | "openOriginal"
  | "save"
  | "search"
  | "help";

interface KeyLike {
  key: string;
  shiftKey?: boolean;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
}

/** True when keystrokes belong to a text field rather than the app. */
export function isTypingTarget(target: EventTarget | Element | null | undefined): boolean {
  if (!target || typeof target !== "object") return false;
  const element = target as { tagName?: unknown; isContentEditable?: unknown };
  if (element.isContentEditable === true) return true;
  const tag = typeof element.tagName === "string" ? element.tagName.toUpperCase() : "";
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

/** ⌘K / Ctrl-K. */
export function isSearchChord(event: KeyLike): boolean {
  return Boolean(event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "k";
}

/** Maps an unmodified key press to an app action. Returns null for anything else. */
export function shortcutFor(event: KeyLike): ShortcutAction | null {
  if (event.metaKey || event.ctrlKey || event.altKey) return null;
  const key = event.key;
  if (key === "Enter") return event.shiftKey ? "openTab" : "open";
  if (key === "?") return "help";
  if (key === "/") return "search";
  if (key === "ArrowDown") return "next";
  if (key === "ArrowUp") return "prev";
  switch (key.toLowerCase()) {
    case "j":
      return "next";
    case "k":
      return "prev";
    case "e":
      return "toggleRead";
    case "t":
      return "focusTags";
    case "r":
      return "rename";
    case "v":
      return "toggleMode";
    case "i":
      return "toggleDetails";
    case "o":
      return "openOriginal";
    case "n":
      return "save";
    default:
      return null;
  }
}

/** Returns the pasted text when it is a single http(s) URL, otherwise null. */
export function extractPastedUrl(text: string | null | undefined): string | null {
  const value = (text || "").trim();
  if (!/^https?:\/\/\S+$/i.test(value)) return null;
  try {
    const url = new URL(value);
    return url.hostname ? value : null;
  } catch {
    return null;
  }
}

/** ⌘/Ctrl-click and middle-click open the standalone reader in a new tab. */
export function wantsNewTab(event: { metaKey?: boolean; ctrlKey?: boolean; button?: number }): boolean {
  return Boolean(event.metaKey || event.ctrlKey) || event.button === 1;
}

export function readerTabUrl(taskId: string, query?: string): string {
  const params = new URLSearchParams({ read: taskId });
  const q = query?.trim();
  if (q) params.set("q", q);
  return `/?${params.toString()}`;
}
