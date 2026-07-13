import type {
  AppConfigRead,
  AppConfigUpdate as GeneratedAppConfigUpdate,
  ArchiveTagRead,
  ArchiveTaskCreated,
  ArchiveTaskFileRead,
  ArchiveTaskRead,
  ArchiveTaskResult,
  AuthSessionRead,
  RssFeedRead,
  RssFeedRefreshResult,
  Token as GeneratedToken,
  UserRead,
} from "@/client/types.gen";

export type ArchiveTaskStatus = "queued" | "running" | "manual_action_required" | "succeeded" | "failed";
export type TaskFilter = "unread" | "all" | "running" | "failed";

export type { ArchiveTaskResult, ArchiveTaskCreated, RssFeedRefreshResult };

export type ArchiveTask = Omit<
  ArchiveTaskRead,
  "current_step" | "finished_at" | "is_read" | "source_type" | "started_at" | "status" | "tags"
> & {
  status: ArchiveTaskStatus;
  is_read: boolean;
  started_at: string | null;
  finished_at: string | null;
  current_step: string | null;
  source_type: "manual" | "rss";
  tags: string[];
  search_match?: {
    excerpt: string;
    score: number;
  } | null;
};

export interface ArchiveTaskListPage {
  items: ArchiveTask[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export type ArchiveFile = ArchiveTaskFileRead;
export type ArchiveTag = ArchiveTagRead;
export type RssFeed = RssFeedRead;
export type AppConfig = AppConfigRead;
export type AppConfigUpdate = GeneratedAppConfigUpdate;
export type User = UserRead;
export type AuthSession = AuthSessionRead;

export type Token = Omit<GeneratedToken, "token_type"> & {
  token_type: "bearer";
};
