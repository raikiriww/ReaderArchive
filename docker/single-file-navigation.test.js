import {
	isLifecycleEventForCurrentTopFrame
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
