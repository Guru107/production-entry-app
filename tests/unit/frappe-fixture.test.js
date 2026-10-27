const test = require("node:test");
const assert = require("node:assert/strict");

const { retryTransientRequest } = require("../e2e/fixtures/test-data");
const {
	callFrappeMethod,
	retryOnContextDestroyed,
	saveForm,
	triggerSaveForm,
} = require("../e2e/fixtures/frappe");
const { hasStockEntryBranchField } = require("../e2e/fixtures/stock-entry-meta");

test("callFrappeMethod posts without a CSRF token or page state", async () => {
	let posted;
	const page = {
		async evaluate() {
			throw new Error("page.evaluate must not run: no token is read from Desk pages.");
		},
		request: {
			async post(url, options) {
				posted = { url, options };
				return {
					ok: () => true,
					status: 200,
					async text() {
						return JSON.stringify({ message: { name: "SHIFT-1" } });
					},
				};
			},
		},
	};

	const result = await callFrappeMethod(page, "frappe.client.get", { doctype: "Shift" });

	assert.deepEqual(result, { name: "SHIFT-1" });
	assert.equal(posted.url, "/api/method/frappe.client.get");
	assert.deepEqual(posted.options.form, { doctype: "Shift" });
	assert.equal(posted.options.headers, undefined);
});

test("hasStockEntryBranchField checks DocField then Custom Field via API", async () => {
	const calls = [];
	const pageFor = (rowsByDoctype) => ({
		request: {
			async post(url, options) {
				const doctype = options.form.doctype;
				calls.push(doctype);
				return {
					ok: () => true,
					status: 200,
					async text() {
						return JSON.stringify({ message: rowsByDoctype[doctype] || [] });
					},
				};
			},
		},
	});

	assert.equal(await hasStockEntryBranchField(pageFor({ DocField: [{ name: "x" }] })), true);
	assert.deepEqual(calls, ["DocField"]); // short-circuits before Custom Field

	calls.length = 0;
	assert.equal(
		await hasStockEntryBranchField(pageFor({ "Custom Field": [{ name: "y" }] })),
		true
	);
	assert.equal(await hasStockEntryBranchField(pageFor({})), false);
	assert.deepEqual(calls, ["DocField", "Custom Field", "DocField", "Custom Field"]);
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

test("saveForm surfaces visible Desk validation messages from the save path", async () => {
	let saves = 0;
	const page = {
		async evaluate(fn, args) {
			if (args?.requestedAction) {
				saves += 1;
				return { validationMessage: "Workstation is already in use." };
			}
			throw new Error("State read should not run after a validation message.");
		},
		async waitForFunction() {
			throw new Error("Saved-state wait should not run after a validation message.");
		},
		async waitForLoadState() {},
	};

	await assert.rejects(() => saveForm(page, "Save"), /Workstation is already in use/);
	assert.equal(saves, 1);
});

test("triggerSaveForm starts a Desk save without waiting for validation rejection", async () => {
	let action;
	const page = {
		async evaluate(fn, args) {
			const originalCurFrm = global.cur_frm;
			global.cur_frm = {
				save(requestedAction) {
					action = requestedAction;
					return Promise.reject(new Error("ValidationError"));
				},
			};
			try {
				return fn(args);
			} finally {
				global.cur_frm = originalCurFrm;
			}
		},
	};

	await triggerSaveForm(page, "Save");

	assert.equal(action, "Save");
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
