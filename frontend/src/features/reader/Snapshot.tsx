import { FileX } from "lucide-react";
import type { SyntheticEvent } from "react";
import type { ArchiveTask } from "../../types/domain";

export type SnapshotSource =
  | { kind: "page"; src: string }
  | { kind: "pdf"; src: string }
  | { kind: "video"; src: string }
  | { kind: "none" };

/**
 * Files are always read through `/files/{name}`. `result.view_url` must never be used here:
 * it points at the file index, which marks the task as read on the server.
 */
export function archiveFileUrl(taskId: string, fileName: string): string {
  return `/api/v1/archive-tasks/${encodeURIComponent(taskId)}/files/${encodeURIComponent(fileName)}`;
}

export function snapshotSource(task: ArchiveTask): SnapshotSource {
  const fileName = task.result?.file_name;
  if (fileName) {
    const src = archiveFileUrl(task.task_id, fileName);
    return /\.pdf$/i.test(fileName) ? { kind: "pdf", src } : { kind: "page", src };
  }
  const videoName = task.result?.video_file_name;
  if (videoName) return { kind: "video", src: archiveFileUrl(task.task_id, videoName) };
  return { kind: "none" };
}

function isEditable(target: EventTarget | null): boolean {
  const element = target as { tagName?: unknown; isContentEditable?: unknown } | null;
  if (!element) return false;
  if (element.isContentEditable === true) return true;
  const tag = typeof element.tagName === "string" ? element.tagName.toUpperCase() : "";
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

/** Re-dispatches keydown from the snapshot document on `window` so shortcuts keep working. */
function forwardKeys(event: SyntheticEvent<HTMLIFrameElement>): void {
  let doc: Document | null = null;
  try {
    doc = event.currentTarget.contentDocument;
  } catch {
    doc = null;
  }
  if (!doc) return;
  doc.addEventListener("keydown", (inner) => {
    if (inner.defaultPrevented || isEditable(inner.target)) return;
    window.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: inner.key,
        code: inner.code,
        metaKey: inner.metaKey,
        ctrlKey: inner.ctrlKey,
        altKey: inner.altKey,
        shiftKey: inner.shiftKey,
        bubbles: true,
        cancelable: true,
      }),
    );
  });
}

export function Snapshot({ task }: { task: ArchiveTask }): JSX.Element {
  const source = snapshotSource(task);
  if (source.kind === "page") {
    return (
      <iframe
        key={source.src}
        className="rd-frame"
        title="存档原貌"
        sandbox="allow-same-origin"
        src={source.src}
        onLoad={forwardKeys}
      />
    );
  }
  if (source.kind === "pdf") {
    return <iframe key={source.src} className="rd-frame" title="存档 PDF" src={source.src} onLoad={forwardKeys} />;
  }
  if (source.kind === "video") {
    return (
      <div className="rd-video-wrap">
        {/* biome-ignore lint/a11y/useMediaCaption: archived videos have no caption track */}
        <video key={source.src} className="rd-video" controls preload="metadata" src={source.src} />
      </div>
    );
  }
  return (
    <div className="rd-snap-empty">
      <FileX size={28} aria-hidden="true" />
      <p>这条存档没有可以显示的文件。</p>
      <small>可以在「详情」里上传文件，或者重新归档。</small>
    </div>
  );
}
