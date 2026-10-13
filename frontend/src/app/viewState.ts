import { useCallback, useEffect, useState } from "react";
import type { ArchiveTask } from "../types/domain";

export type ViewKind = "unread" | "all" | "tag";
export type SourceFilter = "all" | "manual" | "rss";
export type StatusFilter = "all" | "unread" | "problem";

export interface ViewState {
  kind: ViewKind;
  /** Tag view only; combined with AND. */
  tags: string[];
  /** All-archives view only. */
  source: SourceFilter;
  status: StatusFilter;
}

export const defaultView: ViewState = { kind: "unread", tags: [], source: "all", status: "all" };

const attentionStatuses = new Set(["queued", "running", "manual_action_required", "failed"]);
const problemStatuses = new Set(["manual_action_required", "failed"]);

export function needsAttention(task: Pick<ArchiveTask, "status">): boolean {
  return attentionStatuses.has(task.status);
}

export function hasProblem(task: Pick<ArchiveTask, "status">): boolean {
  return problemStatuses.has(task.status);
}

export function readViewState(href: string = window.location.href): ViewState {
  let params: URLSearchParams;
  try {
    params = new URL(href).searchParams;
  } catch {
    return defaultView;
  }
  const kind = params.get("view");
  const tags = (params.get("tags") || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
  if (kind === "tag" && tags.length) return { ...defaultView, kind: "tag", tags };
  if (kind === "all") {
    const source = params.get("source");
    const status = params.get("status");
    return {
      ...defaultView,
      kind: "all",
      source: source === "manual" || source === "rss" ? source : "all",
      status: status === "unread" || status === "problem" ? status : "all",
    };
  }
  return defaultView;
}

/** Writes the view into the current URL; keeps unrelated params (e.g. reader_search). */
export function viewHref(view: ViewState, href: string = window.location.href): string {
  const url = new URL(href);
  for (const key of ["view", "tags", "source", "status"]) url.searchParams.delete(key);
  if (view.kind === "tag") {
    url.searchParams.set("view", "tag");
    url.searchParams.set("tags", view.tags.join(","));
  } else if (view.kind === "all") {
    url.searchParams.set("view", "all");
    if (view.source !== "all") url.searchParams.set("source", view.source);
    if (view.status !== "all") url.searchParams.set("status", view.status);
  }
  return url.toString();
}

export function sameView(a: ViewState, b: ViewState): boolean {
  return (
    a.kind === b.kind &&
    a.source === b.source &&
    a.status === b.status &&
    a.tags.length === b.tags.length &&
    a.tags.every((tag, index) => tag === b.tags[index])
  );
}

export function viewLabel(view: ViewState): string {
  if (view.kind === "unread") return "未读";
  if (view.kind === "all") return "全部存档";
  return view.tags.join(" + ");
}

/** Whether a task belongs to the view (used to drop the pinned item when the reader closes). */
export function taskInView(task: ArchiveTask, view: ViewState): boolean {
  if (view.kind === "unread") return !task.is_read || needsAttention(task);
  if (view.kind === "tag") {
    const own = new Set(task.tags.map((tag) => tag.toLowerCase()));
    return view.tags.every((tag) => own.has(tag.toLowerCase()));
  }
  if (view.source !== "all" && task.source_type !== view.source) return false;
  if (view.status === "unread") return !task.is_read;
  if (view.status === "problem") return hasProblem(task);
  return true;
}

/** View state synced with ?view=&tags=&source=&status= (back/forward work). */
export function useViewState(): [ViewState, (next: ViewState) => void] {
  const [view, setViewState] = useState<ViewState>(() => readViewState());

  useEffect(() => {
    const restore = () => setViewState((current) => {
      const next = readViewState();
      return sameView(current, next) ? current : next;
    });
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);

  const setView = useCallback((next: ViewState) => {
    setViewState(next);
    const href = viewHref(next);
    if (href !== window.location.href) window.history.pushState({ ...window.history.state }, "", href);
  }, []);

  return [view, setView];
}
