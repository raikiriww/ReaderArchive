#!/usr/bin/env node
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import net from "node:net";
import crypto from "node:crypto";

const baseUrl = (process.env.READER_SMOKE_BASE_URL || process.argv[2] || "http://127.0.0.1:8000").replace(/\/$/, "");
const username = process.env.READER_SMOKE_USERNAME || process.argv[3] || "admin";
const password = process.env.READER_SMOKE_PASSWORD || process.argv[4] || "change-me";
const chromePath = process.env.READER_CHROME_PATH || process.env.CHROME_PATH || "/usr/bin/google-chrome";
const removedBusinessPaths = ["/auth", "/archive-tasks", "/archive-tags", "/rss-feeds", "/users", "/app-config", "/health"];

let closed = false;

async function main() {
  const profileDir = await mkdtemp(path.join(tmpdir(), "reader-smoke-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--no-first-run",
    "--disable-background-networking",
    `--user-data-dir=${profileDir}`,
    "--remote-debugging-port=0",
    "about:blank",
  ], { stdio: "ignore" });

  closed = false;
  chrome.once("exit", () => {
    closed = true;
  });

  try {
    const port = await waitForDevToolsPort(profileDir);
    const version = await fetchJson(`http://127.0.0.1:${port}/json/version`);
    const client = await CdpClient.connect(version.webSocketDebuggerUrl);
    const requests = [];
    client.on("Network.requestWillBeSent", (event) => requests.push(event.request.url));

    const { targetId } = await client.send("Target.createTarget", { url: `${baseUrl}/login` });
    const { sessionId } = await client.send("Target.attachToTarget", { targetId, flatten: true });
    await client.send("Page.enable", {}, sessionId);
    await client.send("Runtime.enable", {}, sessionId);
    await client.send("Network.enable", {}, sessionId);

    await waitFor(client, sessionId, "document.querySelector('#loginUsername') && document.querySelector('#loginPassword')");
    await setInputValue(client, sessionId, "#loginUsername", username);
    await setInputValue(client, sessionId, "#loginPassword", password);
    await evaluate(client, sessionId, "document.querySelector('.login-panel button[type=\"submit\"]').click()");

    await waitFor(client, sessionId, "location.pathname === '/' && document.body.textContent.includes('Reader Archive')");
    await waitFor(client, sessionId, "document.querySelector('#urlInput') && document.body.textContent.includes('设置')");
    await waitFor(client, sessionId, "!document.body.textContent.includes('服务运行中') && !document.body.textContent.includes('服务不可用') && !document.body.textContent.includes('存档目录：')");
    await waitFor(client, sessionId, "document.body.textContent.includes('admin · 管理员')");

    await clickButtonByText(client, sessionId, "全部");
    await waitFor(client, sessionId, "document.querySelector('[aria-labelledby=\"taskPaneTitle\"] h1')?.textContent?.includes('全部')");
    await waitFor(client, sessionId, "document.querySelector('#taskSearchInput')");
    await setInputValue(client, sessionId, "#taskSearchInput", "zz-reader-no-match");
    await waitFor(client, sessionId, "document.body.textContent.includes('没有匹配的存档记录')");
    await evaluate(client, sessionId, "document.querySelector('button[aria-label=\"清空搜索\"]')?.click()");
    await waitFor(client, sessionId, "document.querySelector('#taskSearchInput')?.value === ''");

    const selectedDetail = await evaluate(client, sessionId, `
      (() => {
        const task = [...document.querySelectorAll('.task-item')][0];
        if (!task) return false;
        task.click();
        return true;
      })()
    `);
    if (selectedDetail) {
      await waitFor(client, sessionId, "document.querySelector('.detail-pane h2') && document.body.textContent.includes('任务信息')");
    }

    await clickButtonByText(client, sessionId, "设置");
    await waitFor(client, sessionId, "document.querySelector('[role=\"dialog\"][aria-modal=\"true\"]')");
    await waitFor(client, sessionId, "document.querySelector('[role=\"dialog\"]').contains(document.activeElement)");
    await waitFor(client, sessionId, "document.querySelector('#pollIntervalSeconds') && document.querySelector('#rssIntervalMinutes')");
    const originalPollSeconds = await getInputValue(client, sessionId, "#pollIntervalSeconds");
    const originalRssMinutes = await getInputValue(client, sessionId, "#rssIntervalMinutes");
    const nextPollSeconds = String(Number(originalPollSeconds) === 5 ? 6 : 5);
    const nextRssMinutes = String(Number(originalRssMinutes) === 30 ? 31 : 30);
    await setInputValue(client, sessionId, "#pollIntervalSeconds", nextPollSeconds);
    await setInputValue(client, sessionId, "#rssIntervalMinutes", nextRssMinutes);
    await clickButtonByText(client, sessionId, "保存设置");
    await waitFor(client, sessionId, "[...document.querySelectorAll('button')].some((item) => item.textContent.trim() === '保存设置' && !item.disabled)");
    await waitFor(client, sessionId, "document.body.textContent.includes('设置已保存')");
    await setInputValue(client, sessionId, "#pollIntervalSeconds", originalPollSeconds);
    await setInputValue(client, sessionId, "#rssIntervalMinutes", originalRssMinutes);
    await clickButtonByText(client, sessionId, "保存设置");
    await waitFor(client, sessionId, "[...document.querySelectorAll('button')].some((item) => item.textContent.trim() === '保存设置' && !item.disabled)");
    await waitFor(client, sessionId, "document.querySelector('#pollIntervalSeconds')?.value === " + JSON.stringify(originalPollSeconds));
    await clickButtonByText(client, sessionId, "用户管理");
    await waitFor(client, sessionId, "document.querySelector('#newUserUsername') && document.querySelector('#newUserPassword')");
    await client.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 }, sessionId);
    await client.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 }, sessionId);
    await waitFor(client, sessionId, "!document.querySelector('[role=\"dialog\"]')");

    const removedPathRequests = requests.filter((url) => isRemovedBusinessUrl(url));
    if (removedPathRequests.length) {
      throw new Error(`Removed business API requests found: ${removedPathRequests.join(", ")}`);
    }

    client.close();
    console.log("frontend smoke check passed");
  } finally {
    if (!closed) {
      chrome.kill("SIGTERM");
      await waitForChromeExit(chrome, 5000);
    }
    if (!closed) {
      chrome.kill("SIGKILL");
      await waitForChromeExit(chrome, 3000);
    }
    await removeProfile(profileDir);
  }
}

async function waitForDevToolsPort(dir) {
  const file = path.join(dir, "DevToolsActivePort");
  const started = Date.now();
  while (Date.now() - started < 15000) {
    try {
      const [port] = (await readFile(file, "utf8")).trim().split("\n");
      if (port) return port;
    } catch {
      await sleep(100);
    }
  }
  throw new Error("Chrome DevTools port was not created.");
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Request failed: ${url}`);
  return response.json();
}

async function waitFor(client, sessionId, expression) {
  const started = Date.now();
  while (Date.now() - started < 15000) {
    const result = await evaluate(client, sessionId, `Boolean(${expression})`);
    if (result) return;
    await sleep(150);
  }
  throw new Error(`Timed out waiting for: ${expression}`);
}

async function clickButtonByText(client, sessionId, text) {
  const clicked = await evaluate(client, sessionId, `
    (() => {
      const button = [...document.querySelectorAll('button')].find((item) => item.textContent.trim() === ${JSON.stringify(text)});
      if (!button) return false;
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Button not found: ${text}`);
}

async function setInputValue(client, sessionId, selector, value) {
  await evaluate(client, sessionId, `
    (() => {
      const input = document.querySelector(${JSON.stringify(selector)});
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, ${JSON.stringify(value)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()
  `);
}

async function getInputValue(client, sessionId, selector) {
  return evaluate(client, sessionId, `document.querySelector(${JSON.stringify(selector)})?.value || ""`);
}

async function evaluate(client, sessionId, expression) {
  const result = await client.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }, sessionId);
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Runtime evaluation failed.");
  return result.result.value;
}

function isRemovedBusinessUrl(value) {
  const url = new URL(value);
  if (url.origin !== baseUrl) return false;
  return removedBusinessPaths.some((prefix) => url.pathname === prefix || url.pathname.startsWith(`${prefix}/`));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function removeProfile(dir) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      await rm(dir, { recursive: true, force: true });
      return;
    } catch (error) {
      if (error?.code !== "ENOTEMPTY" && error?.code !== "EBUSY") throw error;
      await sleep(250);
    }
  }
  await rm(dir, { recursive: true, force: true });
}

function waitForChromeExit(process, timeoutMs) {
  if (closed) return Promise.resolve();
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, timeoutMs);
    process.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

class CdpClient {
  static async connect(url) {
    return new CdpClient(await openWebSocket(url));
  }

  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    this.handlers = new Map();
    socket.addEventListener("message", (message) => this.handleMessage(message));
  }

  on(method, handler) {
    this.handlers.set(method, handler);
  }

  send(method, params = {}, sessionId = undefined) {
    const id = this.nextId++;
    this.socket.send(JSON.stringify({ id, method, params, sessionId }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
  }

  handleMessage(message) {
    const payload = JSON.parse(message.data);
    if (payload.id) {
      const pending = this.pending.get(payload.id);
      if (!pending) return;
      this.pending.delete(payload.id);
      if (payload.error) pending.reject(new Error(payload.error.message));
      else pending.resolve(payload.result || {});
      return;
    }
    const handler = this.handlers.get(payload.method);
    if (handler) handler(payload.params || {});
  }

  close() {
    this.socket.close();
  }
}

function openWebSocket(url) {
  if (typeof WebSocket !== "undefined") {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url);
      socket.addEventListener("open", () => resolve(socket));
      socket.addEventListener("error", reject);
    });
  }
  return BasicWebSocket.connect(url);
}

class BasicWebSocket {
  static connect(value) {
    return new Promise((resolve, reject) => {
      const url = new URL(value);
      const key = crypto.randomBytes(16).toString("base64");
      const socket = net.connect(Number(url.port), url.hostname);
      const wrapper = new BasicWebSocket(socket);
      let handshake = Buffer.alloc(0);

      socket.once("connect", () => {
        socket.write([
          `GET ${url.pathname}${url.search} HTTP/1.1`,
          `Host: ${url.host}`,
          "Upgrade: websocket",
          "Connection: Upgrade",
          `Sec-WebSocket-Key: ${key}`,
          "Sec-WebSocket-Version: 13",
          "\r\n",
        ].join("\r\n"));
      });

      socket.on("data", function onHandshake(chunk) {
        handshake = Buffer.concat([handshake, chunk]);
        const end = handshake.indexOf("\r\n\r\n");
        if (end === -1) return;
        socket.off("data", onHandshake);
        const header = handshake.subarray(0, end).toString("utf8");
        if (!header.startsWith("HTTP/1.1 101")) {
          reject(new Error("Chrome did not accept WebSocket connection."));
          return;
        }
        const remaining = handshake.subarray(end + 4);
        if (remaining.length) wrapper.receive(remaining);
        socket.on("data", (data) => wrapper.receive(data));
        resolve(wrapper);
      });

      socket.once("error", reject);
    });
  }

  constructor(socket) {
    this.socket = socket;
    this.listeners = new Map();
    this.buffer = Buffer.alloc(0);
  }

  addEventListener(type, handler) {
    this.listeners.set(type, handler);
  }

  send(value) {
    const payload = Buffer.from(value);
    const mask = crypto.randomBytes(4);
    let header;
    if (payload.length < 126) {
      header = Buffer.from([0x81, 0x80 | payload.length]);
    } else if (payload.length < 65536) {
      header = Buffer.alloc(4);
      header[0] = 0x81;
      header[1] = 0x80 | 126;
      header.writeUInt16BE(payload.length, 2);
    } else {
      throw new Error("WebSocket payload is too large.");
    }
    const masked = Buffer.alloc(payload.length);
    for (let index = 0; index < payload.length; index += 1) {
      masked[index] = payload[index] ^ mask[index % 4];
    }
    this.socket.write(Buffer.concat([header, mask, masked]));
  }

  receive(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (this.buffer.length >= 2) {
      const first = this.buffer[0];
      const second = this.buffer[1];
      let length = second & 0x7f;
      let offset = 2;
      if (length === 126) {
        if (this.buffer.length < 4) return;
        length = this.buffer.readUInt16BE(2);
        offset = 4;
      } else if (length === 127) {
        throw new Error("Large WebSocket frames are not supported.");
      }
      if (this.buffer.length < offset + length) return;
      const payload = this.buffer.subarray(offset, offset + length);
      this.buffer = this.buffer.subarray(offset + length);
      const opcode = first & 0x0f;
      if (opcode === 0x1) this.listeners.get("message")?.({ data: payload.toString("utf8") });
      if (opcode === 0x8) this.close();
    }
  }

  close() {
    this.socket.end();
  }
}

await main();
