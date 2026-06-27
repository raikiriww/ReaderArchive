import { beforeEach, describe, expect, test } from "bun:test";

const store = new Map<string, string>();
const locationState = {
  pathname: "/archive",
  search: "?tag=work",
  href: "http://reader.local/archive?tag=work",
};

Object.defineProperty(globalThis, "window", {
  configurable: true,
  value: {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
      removeItem: (key: string) => {
        store.delete(key);
      },
    },
    location: locationState,
  },
});

const { ApiError, TOKEN_KEY, getAccessToken, readGenerated, setAccessToken } = await import("../src/api/client");

describe("frontend API client helpers", () => {
  beforeEach(() => {
    store.clear();
    locationState.pathname = "/archive";
    locationState.search = "?tag=work";
    locationState.href = "http://reader.local/archive?tag=work";
  });

  test("stores and clears access tokens", () => {
    setAccessToken("token-1");
    expect(getAccessToken()).toBe("token-1");
    expect(store.get(TOKEN_KEY)).toBe("token-1");

    setAccessToken("");
    expect(getAccessToken()).toBe("");
    expect(store.has(TOKEN_KEY)).toBe(false);
  });

  test("returns generated data and accepts empty 204 responses", async () => {
    await expect(readGenerated(generatedResult({ ok: true }, 200))).resolves.toEqual({ ok: true });
    await expect(readGenerated(generatedResult(undefined, 204))).resolves.toBeUndefined();
  });

  test("throws API errors and redirects authentication failures to login", async () => {
    setAccessToken("token-2");

    await expect(readGenerated(generatedResult(undefined, 401, { detail: "未登录" }))).rejects.toEqual(
      new ApiError("未登录", 401),
    );

    expect(getAccessToken()).toBe("");
    expect(locationState.href).toBe("/login?next=%2Farchive%3Ftag%3Dwork");
  });
});

function generatedResult<T>(data: T | undefined, status: number, error?: unknown) {
  return Promise.resolve({
    data,
    error,
    request: new Request("http://reader.local/api"),
    response: new Response(null, { status }),
  });
}
