import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef } from "react";
import { ApiError } from "../../api/client";
import type { ArchiveTask } from "../../types/domain";
import { taskTitle } from "../../utils/format";
import { readSearchText } from "../search/api";

const MISSING_TEXT = "这篇存档目前没有可阅读的正文。扫描版 PDF、视频不会提取文字，请看「原貌」。";

/** Removes surrounding quotes used for exact-phrase searches: "foo" → foo. */
export function cleanSearchQuery(query: string | null | undefined): string {
  const value = (query || "").trim();
  const match = /^["“”「『'](.+)["“”」』']$/.exec(value);
  return (match ? match[1] : value).trim();
}

/** Splits text around case-insensitive matches of `query`, wrapping hits in <mark>. No HTML injection. */
export function highlightText(text: string, query: string): ReactNode[] {
  if (!query) return [text];
  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();
  const parts: ReactNode[] = [];
  let start = 0;
  let index = lowerText.indexOf(lowerQuery);
  while (index >= 0 && lowerQuery.length > 0) {
    if (index > start) parts.push(text.slice(start, index));
    const end = index + query.length;
    parts.push(<mark key={index}>{text.slice(index, end)}</mark>);
    start = end;
    index = lowerText.indexOf(lowerQuery, start);
  }
  if (start < text.length) parts.push(text.slice(start));
  return parts;
}

export function countHitParagraphs(paragraphs: string[], query: string): number {
  if (!query) return 0;
  const lowerQuery = query.toLowerCase();
  return paragraphs.filter((paragraph) => paragraph.toLowerCase().includes(lowerQuery)).length;
}

interface TextViewProps {
  task: ArchiveTask;
  searchQuery?: string;
}

export function TextView({ task, searchQuery }: TextViewProps): JSX.Element {
  const ref = useRef<HTMLElement | null>(null);
  const query = cleanSearchQuery(searchQuery);
  const textQuery = useQuery({
    queryKey: ["archive-search-text", task.task_id],
    queryFn: ({ signal }) => readSearchText(task.task_id, signal),
  });
  const data = textQuery.data;
  const paragraphs = data?.paragraphs ?? [];
  const hits = countHitParagraphs(paragraphs, query);

  // A new query changes which text is marked, so scroll to the first match again.
  // biome-ignore lint/correctness/useExhaustiveDependencies: query is the re-scroll trigger.
  useEffect(() => {
    if (!data) return;
    const container = ref.current;
    const mark = container?.querySelector("mark");
    if (mark) mark.scrollIntoView({ block: "center" });
    else container?.scrollTo?.(0, 0);
  }, [data, query]);

  let body: ReactNode;
  if (textQuery.isPending) {
    body = <p className="rd-text-missing">正在读取正文…</p>;
  } else if (textQuery.isError) {
    const notFound = textQuery.error instanceof ApiError && textQuery.error.status === 404;
    body = notFound ? (
      <p className="rd-text-missing">{MISSING_TEXT}</p>
    ) : (
      <div className="rd-text-missing">
        <p>{textQuery.error instanceof Error ? textQuery.error.message : "暂时无法读取正文，请重试。"}</p>
        <button className="rd-text-btn" type="button" onClick={() => void textQuery.refetch()}>
          重试
        </button>
      </div>
    );
  } else if (!paragraphs.length) {
    body = <p className="rd-text-missing">{MISSING_TEXT}</p>;
  } else {
    body = paragraphs.map((paragraph, index) => (
      // biome-ignore lint/suspicious/noArrayIndexKey: paragraphs are static text with no stable id
      <p key={index}>{query ? highlightText(paragraph, query) : paragraph}</p>
    ));
  }

  return (
    <article className="rd-text" lang="zh" ref={ref}>
      {query && hits ? (
        <div className="rd-hit-note">
          「{query}」在正文中出现在 {hits} 段，已跳到第一处
        </div>
      ) : null}
      <h1>{data?.title || taskTitle(task)}</h1>
      {body}
      {paragraphs.length ? <p className="rd-text-end">正文由存档自动提取。图片和排版请切换到「原貌」查看。</p> : null}
    </article>
  );
}
