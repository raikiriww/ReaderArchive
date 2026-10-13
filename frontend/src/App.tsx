import { useQuery } from "@tanstack/react-query";
import { readAppConfig, readCurrentUser } from "./api/client";
import { AppShell } from "./app/AppShell";
import { LoginPage } from "./features/auth/LoginPage";
import type { AppConfig } from "./types/domain";

export const defaultConfig: AppConfig = {
  desktop_url: "/browser/",
  archive_dir: "data/archive",
  poll_interval_ms: 4000,
  rss_refresh_interval_seconds: 1800,
  semantic_search: null,
};

export function LoginRoute(): JSX.Element {
  return <LoginPage />;
}

export function MainApp(): JSX.Element | null {
  const currentUserQuery = useQuery({ queryKey: ["current-user"], queryFn: readCurrentUser, retry: false });
  const currentUser = currentUserQuery.data?.user ?? null;
  const configQuery = useQuery({ queryKey: ["app-config"], queryFn: readAppConfig, enabled: Boolean(currentUser) });
  if (!currentUser) return null;
  return <AppShell currentUser={currentUser} config={configQuery.data ?? defaultConfig} />;
}
