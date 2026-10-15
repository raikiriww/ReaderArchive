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
  const videoSrc = archivedVideoUrl(task);
  return videoSrc ? { kind: "video", src: videoSrc } : { kind: "none" };
}

/** The downloaded video for a task, or null when there is none. */
export function archivedVideoUrl(task: ArchiveTask): string | null {
  const videoName = task.result?.video_file_name;
  return videoName ? archiveFileUrl(task.task_id, videoName) : null;
}

/** Players whose controls sit on top of the video; the whole player is replaced. */
const PLAYER_SELECTORS = [
  "#movie_player", // YouTube
  ".bpx-player-container", // Bilibili
  "#bilibili-player",
  ".video-js", // video.js, used by Weibo and many others
  "#ACPlayer", // AcFun keeps no <video> in the snapshot
];

/** A snapshot <video> whose source was a stream the page's scripts fed and is now gone. */
export function isDeadVideoSource(src: string | null, sourceSrcs: (string | null)[]): boolean {
  const live = (value: string | null) => Boolean(value?.trim()) && !value?.trim().startsWith("blob:");
  return !live(src) && !sourceSrcs.some(live);
}

/**
 * Points the snapshot's own video player at the downloaded file, so pressing play plays it.
 * Returns false when the page has no player to reuse.
 */
export function attachArchivedVideo(doc: Document, src: string): boolean {
  if (doc.querySelector("video[data-reader-video]")) return true;
  const dead =
    Array.from(doc.querySelectorAll("video")).find((video) =>
      isDeadVideoSource(
        video.getAttribute("src"),
        Array.from(video.querySelectorAll("source")).map((source) => source.getAttribute("src")),
      ),
    ) ?? null;
  const selector = PLAYER_SELECTORS.join(",");
  const player = dead ? dead.closest(selector) : doc.querySelector(selector);
  if (!dead && !player) return false;

  const video = doc.createElement("video");
  video.dataset.readerVideo = "true";
  video.controls = true;
  video.preload = "metadata";
  video.src = src;
  const poster = dead?.getAttribute("poster");
  if (poster) video.poster = poster;

  // Snapshot elements belong to the iframe's window, so `instanceof HTMLElement` would be false.
  if (player) {
    const box = player as HTMLElement;
    const collapsed = box.getBoundingClientRect().height < 40;
    box.classList.remove("sf-hidden");
    box.replaceChildren(video);
    video.style.cssText = `display:block;width:100%;height:${collapsed ? "auto" : "100%"};aspect-ratio:${collapsed ? "16/9" : "auto"};background:#000;object-fit:contain`;
  } else if (dead) {
    for (const name of ["class", "style", "width", "height"]) {
      const value = dead.getAttribute(name);
      if (value !== null) video.setAttribute(name, value);
    }
    video.style.background = "#000";
    dead.replaceWith(video);
  }
  // Players saved mid-playback keep their auto-hide state, e.g. YouTube's
  // `.ytp-autohide { cursor: none }`, which the new video would inherit.
  video.style.setProperty("cursor", "auto", "important");
  return true;
}

function isEditable(target: EventTarget | null): boolean {
  const element = target as { tagName?: unknown; isContentEditable?: unknown } | null;
  if (!element) return false;
  if (element.isContentEditable === true) return true;
  const tag = typeof element.tagName === "string" ? element.tagName.toUpperCase() : "";
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

/**
 * Returns the URL a snapshot link should open in a new tab, or null to leave the click alone.
 * In-page `#anchor` links keep scrolling the snapshot; only http(s) links leave it.
 */
export function snapshotLinkTarget(rawHref: string | null, resolvedHref: string): string | null {
  if (rawHref === null || rawHref.trim().startsWith("#")) return null;
  return /^https?:\/\//i.test(resolvedHref) ? resolvedHref : null;
}

/** The sandbox blocks popups, so link clicks are opened in a new tab from the app instead. */
function openLinksInNewTab(doc: Document): void {
  const handle = (inner: MouseEvent) => {
    if (inner.defaultPrevented || (inner.type === "auxclick" && inner.button !== 1)) return;
    const target = inner.target as Element | null;
    const anchor = typeof target?.closest === "function" ? target.closest("a[href]") : null;
    if (!anchor) return;
    const url = snapshotLinkTarget(anchor.getAttribute("href"), (anchor as HTMLAnchorElement).href);
    if (!url) return;
    inner.preventDefault();
    window.open(url, "_blank", "noopener,noreferrer");
  };
  doc.addEventListener("click", handle);
  doc.addEventListener("auxclick", handle);
}

function isMedia(target: EventTarget | null): boolean {
  const tag = (target as { tagName?: unknown } | null)?.tagName;
  return typeof tag === "string" && (tag.toUpperCase() === "VIDEO" || tag.toUpperCase() === "AUDIO");
}

/**
 * Wires up the snapshot document: shortcuts keep working, links open in a new tab, and the
 * page's video player plays the downloaded video.
 */
function wireSnapshot(event: SyntheticEvent<HTMLIFrameElement>, videoSrc: string | null): void {
  let doc: Document | null = null;
  try {
    doc = event.currentTarget.contentDocument;
  } catch {
    doc = null;
  }
  if (!doc) return;
  openLinksInNewTab(doc);
  if (videoSrc) attachArchivedVideo(doc, videoSrc);
  // Re-dispatch keydown on `window` so shortcuts keep working while the snapshot has focus.
  // A focused video keeps its own keys (space, arrows).
  doc.addEventListener("keydown", (inner) => {
    if (inner.defaultPrevented || isEditable(inner.target) || isMedia(inner.target)) return;
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

export function VideoView({ src }: { src: string }): JSX.Element {
  return (
    <div className="rd-video-wrap">
      {/* biome-ignore lint/a11y/useMediaCaption: archived videos have no caption track */}
      <video key={src} className="rd-video" controls preload="metadata" src={src} />
    </div>
  );
}

export function Snapshot({ task }: { task: ArchiveTask }): JSX.Element {
  const source = snapshotSource(task);
  if (source.kind === "page") {
    const videoSrc = archivedVideoUrl(task);
    return (
      <iframe
        key={source.src}
        className="rd-frame"
        title="存档原貌"
        sandbox="allow-same-origin"
        allowFullScreen
        src={source.src}
        onLoad={(event) => wireSnapshot(event, videoSrc)}
      />
    );
  }
  if (source.kind === "pdf") {
    return (
      <iframe
        key={source.src}
        className="rd-frame"
        title="存档 PDF"
        src={source.src}
        onLoad={(event) => wireSnapshot(event, null)}
      />
    );
  }
  if (source.kind === "video") return <VideoView src={source.src} />;
  return (
    <div className="rd-snap-empty">
      <FileX size={28} aria-hidden="true" />
      <p>这条存档没有可以显示的文件。</p>
      <small>可以在「详情」里上传文件，或者重新归档。</small>
    </div>
  );
}
