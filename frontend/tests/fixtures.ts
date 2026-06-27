import type { ArchiveFile, ArchiveTag, ArchiveTask } from "../src/types/domain";

export function archiveTask(overrides: Partial<ArchiveTask> = {}): ArchiveTask {
  return {
    task_id: "task-1",
    url: "https://example.com/articles/reader",
    status: "succeeded",
    is_read: false,
    created_at: "2026-06-21T08:30:00Z",
    started_at: "2026-06-21T08:30:02Z",
    finished_at: "2026-06-21T08:30:08Z",
    current_step: null,
    source_type: "manual",
    source_feed_id: null,
    source_title: null,
    entry_title: null,
    video_title: null,
    custom_title: null,
    display_title: "Reader article",
    tags: [],
    search_match: null,
    result: {
      file_name: "reader.html",
      download_url: "/api/v1/archive-tasks/task-1/files/reader.html/download",
      view_url: "/api/v1/archive-tasks/task-1/files/reader.html/view",
      video_file_name: null,
      video_download_url: null,
      video_error: null,
      page_error: null,
    },
    error: null,
    ...overrides,
  };
}

export function archiveFile(overrides: Partial<ArchiveFile> = {}): ArchiveFile {
  return {
    file_name: "reader.html",
    display_name: "Reader saved page.html",
    tool: "singlefile",
    source_type: "archive",
    size_bytes: 1536,
    view_url: "/files/reader.html",
    download_url: "/files/reader.html?download=1",
    ...overrides,
  };
}

export function archiveTag(name: string, taskCount = 1): ArchiveTag {
  return { name, task_count: taskCount };
}
