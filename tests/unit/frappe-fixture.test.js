const test = require("node:test");
const assert = require("node:assert/strict");

const { retryTransientRequest } = require("../e2e/fixtures/test-data");
const { callFrappeMethod, retryOnContextDestroyed, saveForm } = require("../e2e/fixtures/frappe");

test("callFrappeMethod fails before POST when CSRF token is unavailable", async () => {
	let evaluateCalls = 0;
	const page = {
		async evaluate() {
			evaluateCalls += 1;
			return "";
		},
		async waitForLoadState() {},
		request: {
			async post() {
				throw new Error("POST should not run without a CSRF token.");
			},
		},
	};

	await assert.rejects(
		() => callFrappeMethod(page, "frappe.client.get"),
		/Unable to read CSRF token after retries/
	);
	assert.equal(evaluateCalls, 3);
});

test("retryOnContextDestroyed bounds the recovery wait before retrying", async () => {
	let attempts = 0;
	const waits = [];
	const page = {
		async waitForFunction(predicate, argument, options) {
			waits.push({ argument, options });
		},
	};

	const result = await retryOnContextDestroyed(page, async () => {
		attempts += 1;
		if (attempts === 1) {
			throw new Error("Execution context was destroyed");
		}
		return "ready";
	});

	assert.equal(result, "ready");
	assert.equal(attempts, 2);
	assert.deepEqual(waits, [{ argument: undefined, options: { timeout: 5000 } }]);
});

test("saveForm retries when Frappe assigns a name but leaves the form dirty", async () => {
	let saves = 0;
	let waitAttempts = 0;
	let timeoutWaits = 0;
	let stateReads = 0;
	const page = {
		async evaluate(fn, args) {
			if (args?.requestedAction) {
				saves += 1;
				return;
			}
			stateReads += 1;
			return {
				doctype: "Stock Entry",
				href: "http://localhost/app/stock-entry/MAT-STE-00001",
				isNew: false,
				message: "",
				name: "MAT-STE-00001",
				route: "Form/Stock Entry/MAT-STE-00001",
				unsaved: 1,
			};
		},
		async waitForFunction() {
			waitAttempts += 1;
			if (waitAttempts === 1) {
				throw new Error("Timeout 10000ms exceeded");
			}
		},
		async waitForLoadState() {},
		async waitForTimeout(timeout) {
			assert.equal(timeout, 500);
			timeoutWaits += 1;
		},
	};

	await saveForm(page, "Save");

	assert.equal(saves, 2);
	assert.equal(waitAttempts, 2);
	assert.equal(timeoutWaits, 1);
	assert.equal(stateReads, 1);
});

test("retryTransientRequest retries a socket reset for idempotent E2E setup calls", async () => {
	let attempts = 0;
	const result = await retryTransientRequest(async () => {
		attempts += 1;
		if (attempts === 1) {
			throw new Error("socket hang up");
		}
		return "ready";
	});

	assert.equal(result, "ready");
	assert.equal(attempts, 2);
});

test("retryTransientRequest does not retry application failures", async () => {
	let attempts = 0;
	await assert.rejects(
		() =>
			retryTransientRequest(async () => {
				attempts += 1;
				throw new Error("ValidationError");
			}),
		/ValidationError/
	);
	assert.equal(attempts, 1);
});

test("retryTransientRequest surfaces the last transient failure after retries are exhausted", async () => {
	let attempts = 0;
	await assert.rejects(
		() =>
			retryTransientRequest(async () => {
				attempts += 1;
				throw new Error(`socket hang up ${attempts}`);
			}),
		/socket hang up 3/
	);
	assert.equal(attempts, 3);
});
