import { Check, Clock, ExternalLink, Globe, Hand, LoaderCircle, RefreshCw, TriangleAlert } from "lucide-react";
import { useRef, useState } from "react";
import type { ArchiveTask } from "../../types/domain";
import { shortError, stepLabel } from "../../utils/format";
import type { ReaderActions } from "./types";

type ManualAction = ArchiveTask["manual_actions"][number];

interface StatusPanelProps {
  task: ArchiveTask;
  actions: ReaderActions;
}

export function StatusPanel({ task, actions }: StatusPanelProps): JSX.Element | null {
  if (task.status === "queued" || task.status === "running") return <ProgressPanel task={task} />;
  if (task.status === "manual_action_required") return <ManualPanel task={task} actions={actions} />;
  if (task.status === "failed") return <FailedPanel task={task} actions={actions} />;
  return null;
}

function ProgressPanel({ task }: { task: ArchiveTask }): JSX.Element {
  const queued = task.status === "queued";
  const current = stepLabel(task.current_step);
  const steps = ["排队中", current !== "—" && current !== "排队中" ? current : "保存网页", "提取正文、建立索引"];
  const now = queued ? 0 : 1;
  return (
    <div className="rd-status">
      {queued ? (
        <Clock size={26} className="rd-accent" aria-hidden="true" />
      ) : (
        <LoaderCircle size={26} className="rd-accent rd-spin" aria-hidden="true" />
      )}
      <h2>{queued ? "排队等待保存" : "正在保存"}</h2>
      <p className="rd-mono-url">{task.url}</p>
      <ol className="rd-steps">
        {steps.map((step, index) => (
          <li key={step} className={index < now ? "done" : index === now ? "now" : ""}>
            {step}
          </li>
        ))}
      </ol>
      <p className="rd-hint">不用等待，可以继续看别的。保存完成后，这一条会变成可以阅读的状态。</p>
    </div>
  );
}

function tabStateOf(action: ManualAction): "available" | "missing" | "not_opened" {
  const state = action.browser_tab_state;
  return state === "available" || state === "missing" ? state : "not_opened";
}

function ManualPanel({ task, actions }: StatusPanelProps): JSX.Element {
  const [resuming, setResuming] = useState<string | null>(null);
  const lock = useRef(false);
  const prepare = task.manual_actions.some((action) => action.code === "page.prepare_manually");
  const video = !prepare && task.manual_actions.some((action) => action.target === "video");

  async function resume(code: string): Promise<void> {
    if (lock.current) return;
    lock.current = true;
    setResuming(code);
    try {
      await actions.resumeManualAction(task, code);
    } finally {
      lock.current = false;
      setResuming(null);
    }
  }

  return (
    <div className="rd-status">
      <Hand size={26} className="rd-warn" aria-hidden="true" />
      <h2>
        {prepare ? "等你在内置浏览器里处理这个网页" : video ? "下载视频需要先登录" : "这个网站需要先登录"}
      </h2>
      <p>
        {prepare
          ? "关闭弹窗、展开全文或加载需要的内容后，回到这里点「处理完成」。Reader 会直接保存那个标签页当前的样子，不会重新加载。"
          : "在内置浏览器里登录这个网站，然后回到这里继续。登录状态会保留，以后保存同一个网站就不用再登录。"}
      </p>
      {task.manual_actions.map((action) => {
        const state = tabStateOf(action);
        const isPrepare = action.code === "page.prepare_manually";
        const resumeLabel = isPrepare
          ? "处理完成，保存当前页面"
          : action.resume === "continue_video"
            ? "已登录，继续下载视频"
            : "已登录，继续保存";
        return (
          <div className="rd-manual" key={action.code}>
            {!isPrepare && action.message ? <p className="rd-manual-msg">{action.message}</p> : null}
            <div className={`rd-tab-state ${state === "missing" ? "lost" : ""}`}>
              <span
                className={`rd-dot ${state === "missing" ? "bad" : state === "not_opened" ? "idle" : "ok"}`}
                aria-hidden="true"
              />
              {state === "missing"
                ? "原来的处理页面已经丢失，重新打开后要再处理一次"
                : state === "not_opened"
                  ? "处理页面还没打开"
                  : "处理页面已连接"}
            </div>
            <div className="rd-status-actions">
              <button className="rd-btn" type="button" onClick={() => actions.openManualAction(task, action.code)}>
                <Globe size={15} aria-hidden="true" />
                {state === "missing" ? "重新打开处理页面" : state === "not_opened" ? "打开处理页面" : "切回处理页面"}
              </button>
              <button
                className="rd-btn primary"
                type="button"
                disabled={state !== "available" || resuming !== null}
                onClick={() => void resume(action.code)}
              >
                <Check size={15} aria-hidden="true" />
                {resuming === action.code ? "正在提交…" : resumeLabel}
              </button>
            </div>
          </div>
        );
      })}
      <p className="rd-hint">
        等待手动处理的任务不占用超时时间，也不会挡住其他保存。关掉 Reader 页面后，它也会一直等在这里。
      </p>
      <button className="rd-link-danger" type="button" onClick={() => void actions.remove(task)}>
        取消等待并删除
      </button>
    </div>
  );
}

function FailedPanel({ task, actions }: StatusPanelProps): JSX.Element {
  return (
    <div className="rd-status">
      <TriangleAlert size={26} className="rd-danger" aria-hidden="true" />
      <h2>保存失败</h2>
      <p className="rd-err">{shortError(task.error)}</p>
      <div className="rd-status-actions">
        <button className="rd-btn primary" type="button" onClick={() => actions.rearchive(task, true)}>
          <Hand size={15} aria-hidden="true" />
          手动处理后重试
        </button>
        <button className="rd-btn" type="button" onClick={() => actions.rearchive(task, false)}>
          <RefreshCw size={15} aria-hidden="true" />
          直接重试
        </button>
        <a className="rd-btn" href={task.url} target="_blank" rel="noopener noreferrer">
          <ExternalLink size={15} aria-hidden="true" />
          原网页
        </a>
      </div>
      <button className="rd-link-danger" type="button" onClick={() => void actions.remove(task)}>
        删除这条记录
      </button>
    </div>
  );
}
