import {
  createContext,
  type FormEvent,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

/* ---------- shared overlay ---------- */

interface DialogOverlayProps {
  onClose: () => void;
  children: ReactNode;
  /** "top" pins the dialog near the top of the viewport (save dialog); "center" centers it. */
  placement?: "top" | "center";
  /** Raise above other dialogs (used by confirm/input prompts stacked over feeds/settings). */
  stacked?: boolean;
  labelledBy?: string;
}

/**
 * Backdrop + Escape handling shared by every dialog in this folder.
 * Escape is stopped here so window-level shortcut handlers do not also react to it.
 */
export function DialogOverlay({
  onClose,
  children,
  placement = "center",
  stacked = false,
  labelledBy,
}: DialogOverlayProps): JSX.Element {
  const overlayRef = useRef<HTMLDivElement | null>(null);
  // Captured during the first render, before autoFocus inside the dialog moves focus.
  const previousFocus = useRef<Element | null>(
    typeof document === "undefined" ? null : document.activeElement,
  );

  useEffect(() => {
    const previous =
      previousFocus.current instanceof HTMLElement
        ? previousFocus.current
        : null;
    const overlay = overlayRef.current;
    if (overlay && !overlay.contains(document.activeElement)) overlay.focus();
    return () => {
      if (previous?.isConnected) previous.focus();
    };
  }, []);

  function mouseDown(event: MouseEvent<HTMLDivElement>): void {
    if (event.target === event.currentTarget) onClose();
  }

  function keyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
    }
  }

  return (
    <div
      ref={overlayRef}
      className={`dlg-overlay ${placement === "top" ? "dlg-overlay-top" : ""} ${stacked ? "dlg-overlay-stacked" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-labelledby={labelledBy}
      tabIndex={-1}
      onMouseDown={mouseDown}
      onKeyDown={keyDown}
    >
      {children}
    </div>
  );
}

/* ---------- confirm / input ---------- */

export interface ConfirmRequest {
  kind?: "confirm" | "input";
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  /** input kind: field label */
  label?: string;
  /** input kind: input type, e.g. "password" */
  inputType?: string;
  /** input kind: minimum trimmed length (default 1) */
  minLength?: number;
}

/** confirm kind resolves true/false; input kind resolves the trimmed string or null when cancelled. */
export type ConfirmResult = boolean | string | null;
export type AskFn = (request: ConfirmRequest) => Promise<ConfirmResult>;

interface ConfirmDialogProps {
  request: ConfirmRequest;
  onDone: (result: ConfirmResult) => void;
}

export function ConfirmDialog({
  request,
  onDone,
}: ConfirmDialogProps): JSX.Element {
  const isInput = request.kind === "input";
  const minLength = Math.max(1, request.minLength ?? 1);
  const [value, setValue] = useState("");
  const trimmed = value.trim();
  const ok = isInput ? trimmed.length >= minLength : true;
  const tooShort = isInput && value.length > 0 && !ok;

  function cancel(): void {
    onDone(isInput ? null : false);
  }

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!ok) return;
    onDone(isInput ? trimmed : true);
  }

  return (
    <DialogOverlay onClose={cancel} stacked labelledBy="dlgConfirmTitle">
      <form className="dlg-dialog dlg-confirm" onSubmit={submit}>
        <h2 id="dlgConfirmTitle">{request.title}</h2>
        {request.message ? <p className="dlg-help">{request.message}</p> : null}
        {isInput ? (
          <label className="dlg-field">
            {request.label || "内容"}
            <input
              // biome-ignore lint/a11y/noAutofocus: the prompt exists to collect this value
              autoFocus
              type={request.inputType || "text"}
              autoComplete={
                request.inputType === "password" ? "new-password" : "off"
              }
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
            {request.minLength ? (
              <small className={tooShort ? "dlg-field-bad" : ""}>
                至少 {request.minLength} 位
              </small>
            ) : null}
          </label>
        ) : null}
        <div className="dlg-actions">
          <button className="dlg-btn" type="button" onClick={cancel}>
            {request.cancelLabel || "取消"}
          </button>
          <button
            className={`dlg-btn ${request.danger ? "dlg-btn-danger" : "dlg-btn-primary"}`}
            type="submit"
            // biome-ignore lint/a11y/noAutofocus: Enter confirms a plain confirmation
            autoFocus={!isInput}
            disabled={!ok}
          >
            {request.confirmLabel || "确定"}
          </button>
        </div>
      </form>
    </DialogOverlay>
  );
}

/* ---------- provider + hook ---------- */

interface PendingRequest {
  id: number;
  request: ConfirmRequest;
  resolve: (result: ConfirmResult) => void;
}

const fallbackAsk: AskFn = async (request) => {
  // Used only when no ConfirmProvider is mounted (e.g. isolated tests).
  if (typeof window === "undefined")
    return request.kind === "input" ? null : false;
  if (request.kind === "input") {
    const value = window.prompt(
      [request.title, request.message].filter(Boolean).join("\n"),
    );
    const trimmed = value?.trim() ?? "";
    return trimmed.length >= Math.max(1, request.minLength ?? 1)
      ? trimmed
      : null;
  }
  return window.confirm(
    [request.title, request.message].filter(Boolean).join("\n"),
  );
};

const ConfirmContext = createContext<AskFn>(fallbackAsk);

/**
 * Renders children plus the active confirm/input dialog. Requests are queued; the first one is shown.
 * Mount once near the app root (outside transformed containers, since the overlay is position: fixed).
 */
export function ConfirmProvider({
  children,
}: {
  children?: ReactNode;
}): JSX.Element {
  const [queue, setQueue] = useState<PendingRequest[]>([]);
  const nextId = useRef(1);

  const ask = useCallback<AskFn>(
    (request) =>
      new Promise<ConfirmResult>((resolve) => {
        const id = nextId.current++;
        setQueue((items) => [...items, { id, request, resolve }]);
      }),
    [],
  );

  const active = queue[0] ?? null;

  const done = useCallback(
    (result: ConfirmResult) => {
      if (!active) return;
      active.resolve(result);
      setQueue((items) => items.filter((item) => item.id !== active.id));
    },
    [active],
  );

  return (
    <ConfirmContext.Provider value={ask}>
      {children}
      {active ? (
        <ConfirmDialog key={active.id} request={active.request} onDone={done} />
      ) : null}
    </ConfirmContext.Provider>
  );
}

export type ConfirmHandle = AskFn & { ask: AskFn };

/**
 * Returns `ask(request)`: confirm → Promise<boolean>, input → Promise<string | null>.
 * Works both as `const ask = useConfirm()` and `const { ask } = useConfirm()`.
 */
export function useConfirm(): ConfirmHandle {
  const ask = useContext(ConfirmContext);
  return useMemo(() => {
    const handle = ((request: ConfirmRequest) => ask(request)) as ConfirmHandle;
    handle.ask = handle;
    return handle;
  }, [ask]);
}
