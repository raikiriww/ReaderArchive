import { useQuery } from "@tanstack/react-query";
import { Check, History, Layers } from "lucide-react";
import type { RefObject } from "react";
import { listArchiveTaskVersions } from "../../api/client";
import { usePopover } from "../../components/Popover";
import type { ArchiveTask } from "../../types/domain";
import { formatDate } from "../../utils/format";

export interface ArchiveVersion {
  task_id: string;
  created_at: string;
  status: string;
}

/** Saved versions of the same URL that can be read (succeeded), always keeping the current one. */
export function readableVersions(versions: ArchiveVersion[], currentId: string): ArchiveVersion[] {
  return versions.filter((version) => version.status === "succeeded" || version.task_id === currentId);
}

interface VersionsMenuViewProps {
  currentId: string;
  versions: ArchiveVersion[];
  open: boolean;
  onToggle(): void;
  onPick(taskId: string): void;
  anchorRef?: RefObject<HTMLDivElement | null>;
}

/** Renders nothing unless there is more than one version. */
export function VersionsMenuView({
  currentId,
  versions,
  open,
  onToggle,
  onPick,
  anchorRef,
}: VersionsMenuViewProps): JSX.Element | null {
  if (versions.length <= 1) return null;
  return (
    <div className="rd-anchor" ref={anchorRef}>
      <button
        type="button"
        className={`rd-chip ${open ? "on" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        title="同一网址的保存版本"
        onClick={onToggle}
      >
        <Layers size={13} aria-hidden="true" />
        {versions.length} 个版本
      </button>
      {open ? (
        <div className="rd-menu" role="menu">
          <div className="rd-menu-title">同一网址的保存版本</div>
          {versions.map((version, index) => {
            const current = version.task_id === currentId;
            return (
              <button
                key={version.task_id}
                type="button"
                role="menuitem"
                className={current ? "on" : ""}
                onClick={() => onPick(version.task_id)}
              >
                {current ? <Check size={14} aria-hidden="true" /> : <History size={14} aria-hidden="true" />}
                {formatDate(version.created_at)}
                {index === 0 ? <span className="rd-menu-note">最新</span> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

export function VersionsMenu({
  task,
  onSwitchVersion,
}: {
  task: ArchiveTask;
  onSwitchVersion(taskId: string): void;
}): JSX.Element | null {
  const popover = usePopover<"versions">();
  const versionsQuery = useQuery({
    queryKey: ["archive-versions", task.task_id],
    queryFn: () => listArchiveTaskVersions(task.task_id),
    enabled: task.status === "succeeded",
    staleTime: 30_000,
  });
  const versions = readableVersions(versionsQuery.data ?? [], task.task_id);
  const open = popover.open === "versions";
  return (
    <VersionsMenuView
      currentId={task.task_id}
      versions={versions}
      open={open}
      anchorRef={popover.anchorRef}
      onToggle={() => popover.toggle("versions")}
      onPick={(taskId) => {
        popover.setOpen(null);
        if (taskId !== task.task_id) onSwitchVersion(taskId);
      }}
    />
  );
}
