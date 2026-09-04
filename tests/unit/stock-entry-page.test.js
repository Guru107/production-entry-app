const test = require("node:test");
const assert = require("node:assert/strict");

const {
	getVisibleFetchItemsState,
	hasVisibleFetchItemsErrorDialog,
	isStockEntryReady,
	triggerFetchItems,
	waitForFetchItemsCall,
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

test("fetch item trigger preserves Frappe's async form trigger return value", () => {
	withBrowserState(() => {
		let triggered = false;
		const pending = new Promise(() => {});
		global.window = {
			cur_frm: {
				script_manager: {
					trigger(fieldname) {
						triggered = fieldname;
						return pending;
					},
				},
			},
		};

		assert.equal(triggerFetchItems(), pending);
		assert.equal(triggered, "custom_pea_fetch_items");
	});
});

test("fetch item visible state reports rows and error dialogs", () => {
	withBrowserState(() => {
		global.document = { querySelector: () => null };
		global.window = { cur_frm: { doc: { items: [] } } };
		assert.deepEqual(getVisibleFetchItemsState(), {
			hasErrorDialog: false,
			itemCount: 0,
			modalText: "",
		});

		global.window.cur_frm.doc.items = [{}];
		assert.deepEqual(getVisibleFetchItemsState(), {
			hasErrorDialog: false,
			itemCount: 1,
			modalText: "",
		});

		global.window.cur_frm.doc.items = [];
		global.document.querySelector = () => ({
			innerText: "Qty to Manufacture is required",
			querySelector: () => null,
		});
		assert.deepEqual(getVisibleFetchItemsState(), {
			hasErrorDialog: true,
			itemCount: 0,
			modalText: "Qty to Manufacture is required",
		});
	});
});

test("fetch item validation dialog predicate detects Frappe error modals", () => {
	withBrowserState(() => {
		global.window = { cur_frm: { doc: { items: [] } } };
		global.document = { querySelector: () => null };
		assert.equal(hasVisibleFetchItemsErrorDialog(), false);

		global.document.querySelector = () => ({
			innerText: "Qty to Manufacture is required",
			querySelector: () => null,
		});
		assert.equal(hasVisibleFetchItemsErrorDialog(), true);

		global.document.querySelector = () => ({
			innerText: "Items fetched successfully",
			querySelector: () => null,
		});
		assert.equal(hasVisibleFetchItemsErrorDialog(), false);

		global.document.querySelector = () => ({
			innerText: "",
			querySelector: (selector) => (selector.includes(".indicator.red") ? {} : null),
		});
		assert.equal(hasVisibleFetchItemsErrorDialog(), true);
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
		global.document.querySelector = () => ({
			innerText: "Qty to Manufacture is required",
			querySelector: () => null,
		});
		assert.equal(serializeForBrowser(hasVisibleFetchItemsErrorDialog)(), true);
	});
});

test("Fetch Items wait resolves after the client RPC callback applies rows", async () => {
	const originalWindow = global.window;
	const originalDocument = global.document;
	try {
		global.document = { querySelector: () => null };
		global.window = {
			cur_frm: {
				doc: { items: [] },
				script_manager: {
					trigger(fieldname) {
						assert.equal(fieldname, "custom_pea_fetch_items");
						global.window.frappe.call({
							method: "production_entry_app.production_entry_app.api.get_items_with_rejection",
							callback(response) {
								global.window.cur_frm.doc.items = response.message;
							},
						});
					},
				},
			},
			frappe: {
				after_ajax: async () => {},
				call(options) {
					options.callback({ message: [{ item_code: "FG" }] });
				},
			},
		};

		assert.deepEqual(await waitForFetchItemsCall(), {
			hasErrorDialog: false,
			itemCount: 1,
			modalText: "",
			rowCount: 1,
		});
	} finally {
		global.window = originalWindow;
		global.document = originalDocument;
	}
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
