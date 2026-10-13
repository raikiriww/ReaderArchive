import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

export interface PopoverHandle<T extends string> {
  open: T | null;
  setOpen(next: T | null): void;
  toggle(id: T): void;
  /** Attach to the element that wraps both the trigger and the open popover. */
  anchorRef: RefObject<HTMLDivElement | null>;
}

/**
 * Small popover state: closes on mousedown outside the open popover + its trigger,
 * on Escape (without letting Escape reach other handlers) and on window blur
 * (clicks inside the snapshot iframe never reach this window; it only blurs).
 */
export function usePopover<T extends string = string>(): PopoverHandle<T> {
  const [open, setOpen] = useState<T | null>(null);
  const anchorRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const mouseDown = (event: MouseEvent) => {
      const anchor = anchorRef.current;
      if (anchor && event.target instanceof Node && anchor.contains(event.target)) return;
      setOpen(null);
    };
    const keyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(null);
    };
    const blur = () => setOpen(null);
    window.addEventListener("mousedown", mouseDown);
    window.addEventListener("keydown", keyDown, true);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("mousedown", mouseDown);
      window.removeEventListener("keydown", keyDown, true);
      window.removeEventListener("blur", blur);
    };
  }, [open]);

  const toggle = useCallback((id: T) => setOpen((current) => (current === id ? null : id)), []);

  return { open, setOpen, toggle, anchorRef };
}
