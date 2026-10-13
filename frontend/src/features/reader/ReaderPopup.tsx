import type { ReaderPopupProps } from "./types";

/**
 * Overlay that hosts `<Reader container="popup">`. Clicking the backdrop closes it.
 * Keyboard handling (Esc etc.) belongs to the owner. z-index stays below dialogs (50/55).
 */
export function ReaderPopup({ onClose, children }: ReaderPopupProps): JSX.Element {
  return (
    <div
      className="rd-pop-layer"
      role="dialog"
      aria-modal="true"
      aria-label="阅读"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="rd-pop">
        {children}
      </div>
    </div>
  );
}
