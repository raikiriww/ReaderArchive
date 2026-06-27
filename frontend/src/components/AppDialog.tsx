import { type FormEvent, type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

export type AppDialogRequest =
  | {
      kind: "confirm";
      title: string;
      message: string;
      confirmLabel?: string;
      cancelLabel?: string;
      tone?: "default" | "danger";
      resolve: (value: boolean) => void;
    }
  | {
      kind: "input";
      title: string;
      message: string;
      label: string;
      confirmLabel?: string;
      cancelLabel?: string;
      inputType?: string;
      minLength?: number;
      resolve: (value: string | null) => void;
    };

interface AppDialogProps {
  request: AppDialogRequest | null;
  onClose: () => void;
}

export function AppDialog({ request, onClose }: AppDialogProps): JSX.Element | null {
  const cancelButtonRef = useRef<HTMLButtonElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [inputValue, setInputValue] = useState("");

  useEffect(() => {
    if (!request) return;
    setInputValue("");
    window.requestAnimationFrame(() => {
      if (request.kind === "input") inputRef.current?.focus();
      else cancelButtonRef.current?.focus();
    });
  }, [request]);

  const inputTooShort = useMemo(() => {
    if (request?.kind !== "input" || !request.minLength) return false;
    return inputValue.length > 0 && inputValue.length < request.minLength;
  }, [inputValue, request]);

  if (!request) return null;

  const cancelLabel = request.cancelLabel || "取消";
  const confirmLabel = request.confirmLabel || "确定";
  const isDanger = request.kind === "confirm" && request.tone === "danger";

  function cancel(): void {
    if (!request) return;
    if (request.kind === "confirm") request.resolve(false);
    else request.resolve(null);
    onClose();
  }

  function confirm(): void {
    if (!request) return;
    if (request.kind === "input") {
      const value = inputValue.trim();
      if (!value || (request.minLength && value.length < request.minLength)) return;
      request.resolve(value);
    } else {
      request.resolve(true);
    }
    onClose();
  }

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    confirm();
  }

  function keyDown(event: KeyboardEvent<HTMLElement>): void {
    if (event.key === "Escape") cancel();
  }

  return (
    <Dialog open onOpenChange={(open) => {
      if (!open) cancel();
    }}>
      <DialogPortal>
        <DialogOverlay className="modal-backdrop app-dialog-backdrop" onMouseDown={cancel} />
        <DialogContent
          className="app-dialog"
          aria-labelledby="appDialogTitle"
          aria-describedby="appDialogMessage"
          onKeyDown={keyDown}
          onMouseDown={(event) => event.stopPropagation()}
        >
        <form onSubmit={submit}>
          <div className="app-dialog-header">
            <span className={`app-dialog-icon ${isDanger ? "danger" : ""}`} aria-hidden="true">
              <AlertTriangle size={18} />
            </span>
            <div>
              <DialogTitle asChild>
                <h2 id="appDialogTitle">{request.title}</h2>
              </DialogTitle>
              <DialogDescription asChild>
                <p id="appDialogMessage">{request.message}</p>
              </DialogDescription>
            </div>
            <Button className="icon-button app-dialog-close" type="button" aria-label="关闭" onClick={cancel}>
              <X size={17} />
            </Button>
          </div>

          {request.kind === "input" ? (
            <label className="app-dialog-field" htmlFor="appDialogInput">
              {request.label}
              <Input
                ref={inputRef}
                id="appDialogInput"
                type={request.inputType || "text"}
                minLength={request.minLength}
                required
                value={inputValue}
                onChange={(event) => setInputValue(event.target.value)}
              />
              {inputTooShort ? <span>至少 {request.minLength} 位</span> : null}
            </label>
          ) : null}

          <div className="app-dialog-actions">
            <Button ref={cancelButtonRef} className="dialog-button secondary" type="button" onClick={cancel}>
              {cancelLabel}
            </Button>
            <Button
              className={`dialog-button primary ${isDanger ? "danger" : ""}`}
              type="submit"
              disabled={
                request.kind === "input" &&
                (!inputValue.trim() || Boolean(request.minLength && inputValue.trim().length < request.minLength))
              }
            >
              {confirmLabel}
            </Button>
          </div>
        </form>
        </DialogContent>
      </DialogPortal>
    </Dialog>
  );
}
