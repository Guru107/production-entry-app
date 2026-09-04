const test = require("node:test");
const assert = require("node:assert/strict");

const {
	hasFetchedItemsOrVisibleMessage,
	isStockEntryReady,
	triggerFetchItems,
	waitForStockEntryReady,
} = require("../e2e/pages/stock-entry-page");

function withBrowserState(callback) {
	const originalWindow = global.window;
	const originalDocument = global.document;
	try {
		callback();
	} finally {
		global.window = originalWindow;
		global.document = originalDocument;
	}
}

function serializeForBrowser(predicate) {
	return Function(`return (${predicate.toString()})`)();
}

test("Stock Entry route readiness fast-fails a shown modal", () => {
	withBrowserState(() => {
		global.window = {
			cur_frm: { doctype: "Shift", doc: {}, is_new: () => true },
		};
		global.document = { querySelector: () => ({ role: "dialog" }) };

		assert.equal(isStockEntryReady(false), true);
		assert.equal(isStockEntryReady(true), true);
	});
});

test("Stock Entry route readiness requires a new Stock Entry form", () => {
	withBrowserState(() => {
		global.document = { querySelector: () => null };
		global.window = { cur_frm: null };
		assert.equal(isStockEntryReady(false), false);

		global.window.cur_frm = { doctype: "Shift", doc: {}, is_new: () => true };
		assert.equal(isStockEntryReady(false), false);

		global.window.cur_frm = { doctype: "Stock Entry", doc: {}, is_new: () => false };
		assert.equal(isStockEntryReady(false), false);

		global.window.cur_frm.is_new = () => true;
		assert.equal(isStockEntryReady(false), true);
	});
});

test("Stock Entry AJAX readiness requires its new form and an idle Frappe request queue", () => {
	withBrowserState(() => {
		global.document = { querySelector: () => null };
		global.window = {
			cur_frm: { doctype: "Stock Entry", doc: {}, is_new: () => true },
			frappe: { request: { ajax_count: 1 } },
		};

		assert.equal(isStockEntryReady(true), false);
		global.window.frappe.request.ajax_count = 0;
		assert.equal(isStockEntryReady(true), true);
		global.window.cur_frm.doctype = "Shift";
		assert.equal(isStockEntryReady(true), false);
		delete global.window.frappe.request;
		assert.equal(isStockEntryReady(true), false);
	});
});

test("fetch item trigger does not await Frappe's async form trigger", () => {
	withBrowserState(() => {
		let triggered = false;
		global.window = {
			cur_frm: {
				script_manager: {
					trigger(fieldname) {
						triggered = fieldname;
						return new Promise(() => {});
					},
				},
			},
		};

		assert.equal(triggerFetchItems(), undefined);
		assert.equal(triggered, "custom_pea_fetch_items");
	});
});

test("fetch item completion accepts either rows or a visible validation message", () => {
	withBrowserState(() => {
		global.document = { querySelector: () => null };
		global.window = { cur_frm: { doc: { items: [] } } };
		assert.equal(hasFetchedItemsOrVisibleMessage(), false);

		global.window.cur_frm.doc.items = [{}];
		assert.equal(hasFetchedItemsOrVisibleMessage(), true);

		global.window.cur_frm.doc.items = [];
		global.document.querySelector = () => ({ role: "dialog" });
		assert.equal(hasFetchedItemsOrVisibleMessage(), true);
	});
});

test("Stock Entry readiness predicates remain self-contained after Playwright serialization", () => {
	withBrowserState(() => {
		global.document = { querySelector: () => null };
		global.window = {
			cur_frm: { doctype: "Stock Entry", doc: {}, is_new: () => true },
			frappe: { request: { ajax_count: 0 } },
		};

		assert.equal(serializeForBrowser(isStockEntryReady)(false), true);
		assert.equal(serializeForBrowser(isStockEntryReady)(true), true);
	});
});

test("Stock Entry readiness retries both bounded phases after context destruction", async () => {
	let routeAttempts = 0;
	let ajaxAttempts = 0;
	const waits = [];
	const page = {
		async waitForFunction(predicate, argument, options) {
			if (predicate !== isStockEntryReady) {
				return;
			}
			waits.push({ argument, options });
			if (argument === false) {
				routeAttempts += 1;
				return;
			}
			if (argument === true) {
				ajaxAttempts += 1;
				if (ajaxAttempts === 1) {
					throw new Error("Execution context was destroyed");
				}
			}
		},
	};

	await waitForStockEntryReady(page);

	assert.equal(routeAttempts, 2);
	assert.equal(ajaxAttempts, 2);
	assert.deepEqual(
		waits,
		[false, true, false, true].map((argument) => ({
			argument,
			options: { timeout: 10000 },
		}))
	);
});

test("Stock Entry readiness surfaces a bounded phase timeout without retrying", async () => {
	let attempts = 0;
	const page = {
		async waitForFunction(predicate, argument, options) {
			attempts += 1;
			assert.equal(predicate, isStockEntryReady);
			assert.equal(argument, false);
			assert.deepEqual(options, { timeout: 10000 });
			throw new Error("Timeout 10000ms exceeded");
		},
	};

	await assert.rejects(() => waitForStockEntryReady(page), /Timeout 10000ms exceeded/);
	assert.equal(attempts, 1);
});
