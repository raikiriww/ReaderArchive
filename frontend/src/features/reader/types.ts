import type { ReactNode, RefObject } from "react";
import type { ArchiveTag, ArchiveTask } from "../../types/domain";

// Contract shared by the shell/list workstream and the reader workstream.
// See docs/frontend-redesign-plan.md §3.2 before changing it.

/** "video" is offered only when a page snapshot also has a downloaded video. */
export type ReaderMode = "archive" | "text" | "video";

export interface ReaderNav {
  label: string;
  index: number;
  total: number;
  onPrev(): void;
  onNext(): void;
}

export interface ReaderActions {
  toggleRead(task: ArchiveTask): void;
  rename(task: ArchiveTask, title: string | null): Promise<void>;
  setTags(task: ArchiveTask, tags: string[]): void;
  rearchive(task: ArchiveTask, prepareManually: boolean): void;
  /** Asks for confirmation itself. Resolves true when the task was deleted. */
  remove(task: ArchiveTask): Promise<boolean>;
  openManualAction(task: ArchiveTask, code: string): void;
  resumeManualAction(task: ArchiveTask, code: string): Promise<void>;
  uploadFile(task: ArchiveTask, file: File): void;
  renameFile(task: ArchiveTask, fileName: string, displayName: string): Promise<void>;
  /** Asks for confirmation itself. */
  deleteFile(task: ArchiveTask, fileName: string, displayName: string): void;
  toast(message: string, undo?: () => void): void;
}

export interface ReaderProps {
  task: ArchiveTask;
  container: "popup" | "page";
  nav?: ReaderNav;
  searchQuery?: string;
  allTags: ArchiveTag[];
  mode: ReaderMode;
  onModeChange(mode: ReaderMode): void;
  detailsOpen: boolean;
  onDetailsOpenChange(open: boolean): void;
  /** Incremented by the owner when the R shortcut is pressed. */
  titleEditSignal: number;
  tagInputRef: RefObject<HTMLInputElement | null>;
  onClose?(): void;
  onOpenInTab?(): void;
  onSwitchVersion(taskId: string): void;
  actions: ReaderActions;
}

export interface ReaderPopupProps {
  onClose(): void;
  children: ReactNode;
}
