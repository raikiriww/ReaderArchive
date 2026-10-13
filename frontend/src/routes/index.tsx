import { createFileRoute } from "@tanstack/react-router";
import { useSyncExternalStore } from "react";
import { MainApp } from "../App";
import { ReaderPage } from "../features/reader/ReaderPage";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

function readSearch(): string {
  return window.location.search;
}

function IndexRoute(): JSX.Element {
  const search = useSyncExternalStore(subscribe, readSearch, () => "");
  const params = new URLSearchParams(search);
  const readId = params.get("read");
  if (readId) return <ReaderPage key={readId} taskId={readId} query={params.get("q") ?? ""} />;
  return <MainApp />;
}

export const Route = createFileRoute("/")({
  component: IndexRoute,
});
