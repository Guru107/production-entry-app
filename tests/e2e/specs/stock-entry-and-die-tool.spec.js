const { test, expect } = require("@playwright/test");
const { bootstrapE2E } = require("../fixtures/test-data");
const { getDoc, callFrappeMethod } = require("../fixtures/frappe");
const { StockEntryPage } = require("../pages/stock-entry-page");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");

test.describe("Stock Entry integration", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@smoke manufacture stock entry computes metrics and updates die tool counter", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());

		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.openNew();
		await stockEntryPage.fillManufactureEntry(ctx);
		await stockEntryPage.fetchItems();
		await stockEntryPage.setRejectionBreakup();
		await stockEntryPage.saveAndSubmit();

		const stockEntryName = await page.evaluate(() => cur_frm.doc.name);
		const stockEntry = await getDoc(page, "Stock Entry", stockEntryName);

		expect(stockEntry.docstatus).toBe(1);
		expect(Number(stockEntry.custom_actual_duration_mins)).toBeGreaterThan(0);
		expect(Number(stockEntry.custom_actual_spm)).toBeGreaterThan(0);
		expect(Number(stockEntry.custom_operator_efficiency_pct)).toBeGreaterThan(0);

		const dieCounter = await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.get_die_tool_counter",
			{ die_tool_code: ctx.fg_item }
		);
		expect(Number(dieCounter.current_strokes)).toBeGreaterThan(0);
		expect(Number(dieCounter.utilization_pct)).toBeGreaterThan(0);
	});
});
