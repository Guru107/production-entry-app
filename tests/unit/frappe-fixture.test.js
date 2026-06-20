const test = require("node:test");
const assert = require("node:assert/strict");

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
