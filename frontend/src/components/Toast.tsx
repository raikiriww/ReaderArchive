export function Toast({ message }: { message: string }): JSX.Element {
  return (
    <div className={`toast ${message ? "visible" : ""}`} role="status" aria-live="polite">
      {message}
    </div>
  );
}
