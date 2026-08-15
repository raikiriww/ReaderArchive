import {
	isLifecycleEventForCurrentTopFrame,
	captureMainDocument,
	getCurrentPdfUrl
} from "file:///src/lib/cdp-client.js";

function assertEquals(actual, expected, message) {
	if (actual !== expected) {
		throw new Error(`${message}: expected ${expected}, got ${actual}`);
	}
}

Deno.test("accepts lifecycle events only for the current top-frame navigation", () => {
	const pendingState = {
		topFrameId: undefined,
		topLoaderId: undefined
	};
	assertEquals(
		isLifecycleEventForCurrentTopFrame(
			{ frameId: "blank-frame", loaderId: "blank-loader" },
			pendingState
		),
		false,
		"an event received before the target navigation must be ignored"
	);

	const targetState = {
		topFrameId: "target-frame",
		topLoaderId: "target-loader"
	};
	assertEquals(
		isLifecycleEventForCurrentTopFrame(
			{ frameId: "target-frame", loaderId: "blank-loader" },
			targetState
		),
		false,
		"an event from an older navigation must be ignored"
	);
	assertEquals(
		isLifecycleEventForCurrentTopFrame(
			{ frameId: "iframe", loaderId: "target-loader" },
			targetState
		),
		false,
		"an event from a child frame must be ignored"
	);
	assertEquals(
		isLifecycleEventForCurrentTopFrame(
			{ frameId: "target-frame", loaderId: "target-loader" },
			targetState
		),
		true,
		"the current top-frame navigation must be accepted"
	);

	const redirectedState = {
		topFrameId: "target-frame",
		topLoaderId: "redirect-loader"
	};
	assertEquals(
		isLifecycleEventForCurrentTopFrame(
			{ frameId: "target-frame", loaderId: "target-loader" },
			redirectedState
		),
		false,
		"an event from before a redirect must be ignored"
	);
	assertEquals(
		isLifecycleEventForCurrentTopFrame(
			{ frameId: "target-frame", loaderId: "redirect-loader" },
			redirectedState
		),
		true,
		"the final redirected navigation must be accepted"
	);
});

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
