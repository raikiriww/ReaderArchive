import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

export type ToastFn = (message: string, undo?: () => void) => void;

interface ToastState {
  id: number;
  message: string;
  undo?: () => void;
}

const fallbackToast: ToastFn = () => undefined;
const ToastContext = createContext<ToastFn>(fallbackToast);

export function ToastView({ message, onUndo }: { message: string; onUndo?: () => void }): JSX.Element {
  return (
    <div className={`app-toast ${message ? "visible" : ""}`} role="status" aria-live="polite">
      <span>{message}</span>
      {onUndo ? (
        <button type="button" className="app-toast-undo" onClick={onUndo}>
          撤销
        </button>
      ) : null}
    </div>
  );
}

/** Mount once at the app root. The toast sits above dialogs (z-index > 55). */
export function ToastProvider({ children }: { children?: ReactNode }): JSX.Element {
  const [toast, setToast] = useState<ToastState | null>(null);
  const timer = useRef<number | null>(null);
  const nextId = useRef(1);

  const show = useCallback<ToastFn>((message, undo) => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    setToast({ id: nextId.current++, message, undo });
    timer.current = window.setTimeout(() => setToast(null), undo ? 5200 : 3200);
  }, []);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const undo = toast?.undo;
  return (
    <ToastContext.Provider value={show}>
      {children}
      <ToastView
        key={toast?.id ?? 0}
        message={toast?.message ?? ""}
        onUndo={
          undo
            ? () => {
                setToast(null);
                undo();
              }
            : undefined
        }
      />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastFn {
  return useContext(ToastContext);
}
