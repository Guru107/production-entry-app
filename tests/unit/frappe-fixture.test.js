const test = require("node:test");
const assert = require("node:assert/strict");

const { retryTransientRequest } = require("../e2e/fixtures/test-data");
const { callFrappeMethod } = require("../e2e/fixtures/frappe");

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
