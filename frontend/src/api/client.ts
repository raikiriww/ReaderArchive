import { client } from "@/client/client.gen";
import {
  authLogout,
  authReadCurrentUser,
  archiveTasksContinueArchiveVideo,
  archiveTasksCreateArchiveTask,
  archiveTasksDeleteArchiveTask,
  archiveTasksDeleteArchiveTaskFile,
  archiveTasksListArchiveTags,
  archiveTasksListArchiveTaskFiles,
  archiveTasksListArchiveTasks,
  archiveTasksMarkArchiveTaskRead,
  archiveTasksOpenArchiveTaskInBrowser,
  archiveTasksOpenManualActionInBrowser,
  archiveTasksResumeManualAction,
  archiveTasksUpdateArchiveTask,
  archiveTasksUpdateArchiveTaskFile,
  configReadAppConfig,
  configUpdateAppConfig,
  loginLoginAccessToken,
  loginTestToken,
  loginLoginJson,
  rssFeedsCreateRssFeed,
  rssFeedsDeleteRssFeed,
  rssFeedsListRssFeeds,
  rssFeedsRefreshRssFeed,
  rssFeedsUpdateRssFeed,
  usersCreateUser,
  usersDeleteUser,
  usersListUsers,
  usersResetUserPassword,
  usersUpdateUser,
  loginChangePassword,
} from "@/client/sdk.gen";
import type {
  AppConfigRead,
  AppConfigUpdate,
  ArchiveTagRead,
  ArchiveTaskCreated,
  ArchiveTaskFileRead,
  ArchiveTaskListRead,
  ArchiveTaskRead,
  ArchiveTaskUpdate,
  AuthSessionRead,
  LoginChangePasswordData,
  RssFeedRead,
  RssFeedRefreshResult,
  RssFeedUpdate,
  Token,
  UserCreate,
  UserPasswordReset,
  UserRead,
  UserUpdate,
} from "@/client/types.gen";

export const TOKEN_KEY = "access_token";

client.setConfig({
  auth: () => window.localStorage.getItem(TOKEN_KEY) || undefined,
});

export function getAccessToken(): string {
  return window.localStorage.getItem(TOKEN_KEY) || "";
}

export function setAccessToken(token: string): void {
  if (token) {
    window.localStorage.setItem(TOKEN_KEY, token);
  } else {
    window.localStorage.removeItem(TOKEN_KEY);
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

type GeneratedResult<T> = Promise<
  | {
      data: T | undefined;
      error: undefined;
      request: Request;
      response: Response;
    }
  | {
      data: undefined;
      error: unknown;
      request: Request;
      response: Response;
    }
>;

export function redirectToLogin(): void {
  setAccessToken("");
  const next = window.location.pathname + window.location.search;
  window.location.href = `/login?next=${encodeURIComponent(next)}`;
}

export async function readGenerated<T>(request: GeneratedResult<T>): Promise<T> {
  const result = await request;
  if ("error" in result && result.error !== undefined) {
    const message = parseErrorMessage(result.error, result.response.status);
    if (result.response.status === 401 || result.response.status === 403) {
      redirectToLogin();
    }
    throw new ApiError(message, result.response.status);
  }
  if (result.data === undefined) {
    if (result.response.status === 204) {
      return undefined as T;
    }
    throw new ApiError(`请求失败：${result.response.status}`, result.response.status);
  }
  return result.data as T;
}

export async function login(username: string, password: string): Promise<Token> {
  const token = await readGenerated<Token>(
    loginLoginAccessToken({
      body: {
        username,
        password,
      },
    }),
  );
  setAccessToken(token.access_token);
  return token;
}

export async function loginWithJson(username: string, password: string): Promise<Token> {
  const token = await readGenerated<Token>(loginLoginJson({ body: { username, password } }));
  setAccessToken(token.access_token);
  return token;
}

export async function testToken(): Promise<UserRead> {
  return readGenerated<UserRead>(loginTestToken());
}

export async function logout(): Promise<void> {
  await readGenerated(authLogout());
  setAccessToken("");
}

export async function readCurrentUser(): Promise<AuthSessionRead> {
  return readGenerated<AuthSessionRead>(authReadCurrentUser());
}

export async function readAppConfig(): Promise<AppConfigRead> {
  return readGenerated<AppConfigRead>(configReadAppConfig());
}

export async function updateAppConfig(payload: AppConfigUpdate): Promise<AppConfigRead> {
  return readGenerated<AppConfigRead>(configUpdateAppConfig({ body: payload }));
}

export async function listArchiveTasks(options: {
  includeRead: boolean;
  limit: number;
  offset?: number;
  status?: "running" | "failed";
  tags: string[];
  q?: string;
  title?: string;
}): Promise<ArchiveTaskListRead> {
  return readGenerated<ArchiveTaskListRead>(
    archiveTasksListArchiveTasks({
      query: {
        include_read: options.includeRead,
        limit: options.limit,
        offset: options.offset ?? 0,
        status: options.status || null,
        tags: options.tags.length ? options.tags : null,
        q: options.q || null,
        title: options.title || null,
      },
    }),
  );
}

export async function createArchiveTask(url: string): Promise<ArchiveTaskCreated> {
  return readGenerated<ArchiveTaskCreated>(archiveTasksCreateArchiveTask({ body: { url } }));
}

export async function listArchiveTags(): Promise<ArchiveTagRead[]> {
  return readGenerated<ArchiveTagRead[]>(archiveTasksListArchiveTags());
}

export async function updateArchiveTask(taskId: string, payload: ArchiveTaskUpdate): Promise<ArchiveTaskRead> {
  return readGenerated<ArchiveTaskRead>(
    archiveTasksUpdateArchiveTask({
      path: { task_id: taskId },
      body: payload,
    }),
  );
}

export async function deleteArchiveTask(taskId: string): Promise<void> {
  await readGenerated(archiveTasksDeleteArchiveTask({ path: { task_id: taskId } }));
}

export async function listArchiveTaskFiles(taskId: string): Promise<ArchiveTaskFileRead[]> {
  return readGenerated<ArchiveTaskFileRead[]>(archiveTasksListArchiveTaskFiles({ path: { task_id: taskId } }));
}

export async function markArchiveTaskRead(taskId: string): Promise<void> {
  await readGenerated(archiveTasksMarkArchiveTaskRead({ path: { task_id: taskId } }));
}

export async function rearchiveTask(taskId: string): Promise<ArchiveTaskRead> {
  const url = client.buildUrl({
    url: "/api/v1/archive-tasks/{task_id}/rearchive",
    path: { task_id: taskId },
  });
  const response = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${getAccessToken()}`,
    },
  });
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      redirectToLogin();
    }
    const error = await parseResponseError(response);
    throw new ApiError(error, response.status);
  }
  return (await response.json()) as ArchiveTaskRead;
}

export async function continueArchiveVideo(taskId: string): Promise<void> {
  await readGenerated(archiveTasksContinueArchiveVideo({ path: { task_id: taskId } }));
}

export async function resumeManualAction(taskId: string, code: string): Promise<ArchiveTaskRead> {
  return readGenerated<ArchiveTaskRead>(
    archiveTasksResumeManualAction({
      path: { task_id: taskId },
      body: { code },
    }),
  );
}

export async function openArchiveTaskInBrowser(taskId: string, actionCode?: string): Promise<{ desktop_url?: string }> {
  const request = actionCode
    ? archiveTasksOpenManualActionInBrowser({ path: { task_id: taskId, action_code: actionCode } })
    : archiveTasksOpenArchiveTaskInBrowser({ path: { task_id: taskId } });
  return readGenerated<{ desktop_url?: string }>(request);
}

export async function uploadArchiveTaskFile(taskId: string, file: File): Promise<void> {
  const url = client.buildUrl({
    url: "/api/v1/archive-tasks/{task_id}/files",
    path: { task_id: taskId },
    query: { file_name: file.name },
  });
  const response = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${getAccessToken()}`,
      "Content-Type": file.type || "application/octet-stream",
    },
    body: file,
  });
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      redirectToLogin();
    }
    const error = await parseResponseError(response);
    throw new ApiError(error, response.status);
  }
}

export async function updateArchiveTaskFile(taskId: string, fileName: string, displayName: string): Promise<void> {
  await readGenerated(
    archiveTasksUpdateArchiveTaskFile({
      path: { task_id: taskId, file_name: fileName },
      body: { display_name: displayName },
    }),
  );
}

export async function deleteArchiveTaskFile(taskId: string, fileName: string): Promise<void> {
  await readGenerated(archiveTasksDeleteArchiveTaskFile({ path: { task_id: taskId, file_name: fileName } }));
}

export async function listRssFeeds(): Promise<RssFeedRead[]> {
  return readGenerated<RssFeedRead[]>(rssFeedsListRssFeeds());
}

export async function createRssFeed(url: string): Promise<RssFeedRefreshResult> {
  return readGenerated<RssFeedRefreshResult>(rssFeedsCreateRssFeed({ body: { url } }));
}

export async function updateRssFeed(feedId: string, payload: RssFeedUpdate): Promise<RssFeedRead> {
  return readGenerated<RssFeedRead>(rssFeedsUpdateRssFeed({ path: { feed_id: feedId }, body: payload }));
}

export async function deleteRssFeed(feedId: string): Promise<void> {
  await readGenerated(rssFeedsDeleteRssFeed({ path: { feed_id: feedId } }));
}

export async function refreshRssFeed(feedId: string): Promise<RssFeedRefreshResult> {
  return readGenerated<RssFeedRefreshResult>(rssFeedsRefreshRssFeed({ path: { feed_id: feedId } }));
}

export async function listUsers(): Promise<UserRead[]> {
  return readGenerated<UserRead[]>(usersListUsers());
}

export async function createUser(payload: UserCreate): Promise<UserRead> {
  return readGenerated<UserRead>(usersCreateUser({ body: payload }));
}

export async function updateUser(userId: string, payload: UserUpdate): Promise<UserRead> {
  return readGenerated<UserRead>(usersUpdateUser({ path: { user_id: userId }, body: payload }));
}

export async function resetUserPassword(userId: string, payload: UserPasswordReset): Promise<UserRead> {
  return readGenerated<UserRead>(usersResetUserPassword({ path: { user_id: userId }, body: payload }));
}

export async function deleteUser(userId: string): Promise<void> {
  await readGenerated(usersDeleteUser({ path: { user_id: userId } }));
}

export async function changePassword(payload: LoginChangePasswordData["body"]): Promise<UserRead> {
  return readGenerated<UserRead>(loginChangePassword({ body: payload }));
}

function parseErrorMessage(error: unknown, status: number): string {
  if (typeof error === "object" && error !== null && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return `请求失败：${status}`;
}

async function parseResponseError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return parseErrorMessage(body, response.status);
  } catch {
    return `请求失败：${response.status}`;
  }
}
