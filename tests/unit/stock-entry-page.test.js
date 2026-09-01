const test = require("node:test");
const assert = require("node:assert/strict");

const { isStockEntryFormSettled } = require("../e2e/pages/stock-entry-page");

test("Stock Entry readiness waits for passive Rework discovery or a real dialog", () => {
	const originalWindow = global.window;
	const originalDocument = global.document;
	global.window = {
		cur_frm: { doctype: "Stock Entry", doc: {}, is_new: () => true },
	};
	global.document = { querySelector: () => null };

	try {
		assert.equal(isStockEntryFormSettled(), false);
		global.window.cur_frm.doc.__pea_rework_stock_entry_type = "";
		assert.equal(isStockEntryFormSettled(), true);
		delete global.window.cur_frm.doc.__pea_rework_stock_entry_type;
		global.window.cur_frm.doctype = "Shift";
		global.document.querySelector = () => ({ role: "dialog" });
		assert.equal(isStockEntryFormSettled(), true);
		global.document.querySelector = () => null;
		assert.equal(isStockEntryFormSettled(), false);
	} finally {
		global.window = originalWindow;
		global.document = originalDocument;
	}
});
