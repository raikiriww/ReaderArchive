import {
	captureMainDocument,
	getCurrentPdfUrl,
	getFetchHeaders
} from "file:///src/lib/cdp-client.js";
import { arrayBufferToBase64 } from "file:///src/lib/cdp-client-util.js";
import {
	FETCH_FUNCTION_NAME,
	RESOLVE_FETCH_FUNCTION_NAME,
	REJECT_FETCH_FUNCTION_NAME,
	initSingleFile
} from "file:///src/lib/single-file-script.js";

function assertEquals(actual, expected, message) {
	if (actual !== expected) {
		throw new Error(`${message}: expected ${expected}, got ${actual}`);
	}
}

Deno.test("copies the final top-frame document response without trusting its content type", async () => {
	const directory = await Deno.makeTempDir();
	const output = `${directory}/document.tmp`;
	let responseBodyCalls = 0;
	const Fetch = {
		async getResponseBody() {
			responseBodyCalls++;
			return { body: "JVBERi0xLjcK", base64Encoded: true };
		}
	};
	const context = {
		options: { browserDocumentFile: output },
		debugMessages: []
	};
	const captureState = { pdfCaptured: false };
	try {
		for (const [index, status] of [302, 303, 307, 308].entries()) {
			await captureMainDocument(
				{ Fetch },
				{
					frameId: "top-frame",
					requestId: `redirect-${index}`,
					resourceType: "Document",
					responseHeaders: [],
					responseStatusCode: status
				},
				"top-frame",
				context,
				captureState
			);
		}
		assertEquals(responseBodyCalls, 0, "redirect responses must not be captured");
		await captureMainDocument(
			{ Fetch },
			{
				frameId: "top-frame",
				requestId: "request-1",
				resourceType: "Document",
				responseHeaders: [{ name: "Content-Type", value: "application/octet-stream" }],
				responseStatusCode: 200
			},
			"top-frame",
			context,
			captureState
		);
		assertEquals(responseBodyCalls, 1, "the main response body must be requested once");
		assertEquals(
			new TextDecoder().decode(await Deno.readFile(output)),
			"%PDF-1.7\n",
			"base64 response bytes must be preserved"
		);
		assertEquals(captureState.pdfCaptured, true, "a captured PDF must be retained");
		assertEquals(
			JSON.parse(await Deno.readTextFile(output + ".json")).contentType,
			"application/octet-stream",
			"the response content type must be recorded without sensitive headers"
		);

		await captureMainDocument(
			{ Fetch },
			{
				frameId: "top-frame",
				requestId: "request-2",
				resourceType: "Document",
				responseHeaders: [{ name: "Content-Type", value: "text/html" }],
				responseStatusCode: 200
			},
			"top-frame",
			context,
			captureState
		);
		await captureMainDocument(
			{ Fetch },
			{
				frameId: "child-frame",
				requestId: "request-3",
				resourceType: "Document",
				responseHeaders: [],
				responseStatusCode: 200
			},
			"top-frame",
			context,
			captureState
		);
		await captureMainDocument(
			{ Fetch },
			{
				frameId: "top-frame",
				requestId: "request-4",
				resourceType: "Document",
				responseHeaders: [],
				responseStatusCode: 302
			},
			"top-frame",
			context,
			captureState
		);
		assertEquals(responseBodyCalls, 1, "the PDF must not be overwritten by viewer, redirect, or child responses");
	} finally {
		await Deno.remove(directory, { recursive: true });
	}
});

Deno.test("detects an already-open PDF tab for authenticated reload", async () => {
	let enableCalls = 0;
	let disableCalls = 0;
	const Runtime = {
		async enable() {
			enableCalls++;
		},
		async disable() {
			disableCalls++;
		},
		async evaluate() {
			return {
				result: { value: "https://example.test/protected/document" }
			};
		}
	};
	const url = await getCurrentPdfUrl(
		{ Runtime },
		{ options: {}, debugMessages: [] }
	);
	assertEquals(url, "https://example.test/protected/document");
	assertEquals(enableCalls, 1);
	assertEquals(disableCalls, 1);
});

Deno.test("encodes large fetched resources without overflowing the call stack", () => {
	const bytes = new Uint8Array(512 * 1024);
	for (let index = 0; index < bytes.length; index++) {
		bytes[index] = index % 251;
	}
	const encoded = arrayBufferToBase64(bytes.buffer);
	const decoded = Uint8Array.fromBase64(encoded);
	assertEquals(decoded.length, bytes.length, "the encoded resource length must be preserved");
	assertEquals(decoded[0], bytes[0], "the first byte must be preserved");
	assertEquals(decoded[123456], bytes[123456], "a middle byte must be preserved");
	assertEquals(decoded.at(-1), bytes.at(-1), "the last byte must be preserved");
});

Deno.test("retries HTTP error responses with the built-in out-of-browser fetch", async () => {
	const originalFetch = globalThis.fetch;
	const originalSingleFile = globalThis.singlefile;
	const originalFetchBinding = globalThis[FETCH_FUNCTION_NAME];
	const originalResolveBinding = globalThis[RESOLVE_FETCH_FUNCTION_NAME];
	const originalRejectBinding = globalThis[REJECT_FETCH_FUNCTION_NAME];
	let singleFileFetch;
	let fallbackRequest;
	try {
		globalThis.fetch = async () => ({ status: 403 });
		globalThis.singlefile = {
			init({ fetch }) {
				singleFileFetch = fetch;
			}
		};
		globalThis[FETCH_FUNCTION_NAME] = payload => {
			fallbackRequest = JSON.parse(payload);
			globalThis[RESOLVE_FETCH_FUNCTION_NAME](fallbackRequest.requestId, {
				status: 200,
				headers: { "content-type": "image/jpeg" },
				data: btoa("image-bytes")
			});
		};
		initSingleFile({
			FETCH_FUNCTION_NAME,
			RESOLVE_FETCH_FUNCTION_NAME,
			REJECT_FETCH_FUNCTION_NAME
		});

		const response = await singleFileFetch("https://images.example.test/photo.jpg", {
			referrer: "https://example.test/page/"
		});
		assertEquals(response.status, 200, "the fallback response must replace the HTTP error");
		assertEquals(
			new TextDecoder().decode(await response.arrayBuffer()),
			"image-bytes",
			"the fallback response body must be preserved"
		);
		assertEquals(
			fallbackRequest.url,
			"https://images.example.test/photo.jpg",
			"the failed URL must be retried"
		);
	} finally {
		globalThis.fetch = originalFetch;
		restoreGlobal("singlefile", originalSingleFile);
		restoreGlobal(FETCH_FUNCTION_NAME, originalFetchBinding);
		restoreGlobal(RESOLVE_FETCH_FUNCTION_NAME, originalResolveBinding);
		restoreGlobal(REJECT_FETCH_FUNCTION_NAME, originalRejectBinding);
	}
});

Deno.test("turns the SingleFile referrer option into an HTTP header for fallback fetches", () => {
	const headers = getFetchHeaders(
		{
			headers: { accept: "image/*" },
			referrer: "https://example.test/page/"
		},
		{ httpHeaders: { "x-reader-test": "enabled" } },
		{ userAgent: "Reader Browser" }
	);
	assertEquals(headers.accept, "image/*", "resource headers must be preserved");
	assertEquals(headers.referer, "https://example.test/page/", "the referrer header must be sent");
	assertEquals(headers["user-agent"], "Reader Browser", "the browser user agent must be sent");
	assertEquals(headers["x-reader-test"], "enabled", "configured headers must be preserved");
});

function restoreGlobal(name, value) {
	if (value === undefined) {
		delete globalThis[name];
	} else {
		globalThis[name] = value;
	}
}
