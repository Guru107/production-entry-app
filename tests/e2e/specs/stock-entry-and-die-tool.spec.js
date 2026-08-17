const { test, expect } = require("@playwright/test");
const { bootstrapE2E } = require("../fixtures/test-data");
const { getDoc, callFrappeMethod } = require("../fixtures/frappe");
const { StockEntryPage } = require("../pages/stock-entry-page");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");
const { getRoute } = require("../utils/routing");

test.describe("Stock Entry integration", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@smoke manufacture stock entry computes metrics and updates die tool counter", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
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
		expect(Number(stockEntry.custom_pea_actual_duration_mins)).toBeGreaterThan(0);
		expect(Number(stockEntry.custom_pea_production_time_mins)).toBeGreaterThan(0);
		expect(Number(stockEntry.custom_pea_actual_spm)).toBeGreaterThan(0);
		expect(Number(stockEntry.custom_pea_operator_efficiency_pct)).toBeGreaterThan(0);

		const dieCounter = await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.get_die_tool_counter",
			{ die_tool_code: ctx.fg_item }
		);
		expect(Number(dieCounter.current_strokes)).toBeGreaterThan(0);
		expect(Number(dieCounter.utilization_pct)).toBeGreaterThan(0);
	});

	test("@regression manufacture stock entry keeps die tool metrics zero when item has no die tool", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		await callFrappeMethod(page, "frappe.client.set_value", {
			doctype: "Item",
			name: ctx.fg_item,
			fieldname: "custom_pea_has_die_tool",
			value: 0,
		});

		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.openNew();
		await stockEntryPage.fillManufactureEntry(ctx);
		await stockEntryPage.fetchItems();
		await stockEntryPage.setRejectionBreakup();
		await stockEntryPage.saveAndSubmit();

		const stockEntryName = await page.evaluate(() => cur_frm.doc.name);
		const stockEntry = await getDoc(page, "Stock Entry", stockEntryName);
		expect(Number(stockEntry.custom_pea_die_tool_utilization_pct || 0)).toBe(0);
		expect(Number(stockEntry.custom_pea_die_tool_maintenance_due || 0)).toBe(0);

		const dieCounter = await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.get_die_tool_counter",
			{ die_tool_code: ctx.fg_item }
		);
		expect(Number(dieCounter.has_die_tool || 0)).toBe(0);
		expect(Number(dieCounter.current_strokes || 0)).toBe(0);

		const warningMessage = await page.evaluate(() =>
			String(window.cur_frm?.__peaDieToolAlertMessage || "")
		);
		expect(warningMessage).toBe("");
	});

	test("@regression get_die_tool_counter stays side-effect-free during concurrent first reads", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());

		const existingCounter = await callFrappeMethod(page, "frappe.client.get_value", {
			doctype: "Die Tool Counter",
			filters: JSON.stringify({ die_tool_item: ctx.fg_item }),
			fieldname: "name",
		});
		const counterName = existingCounter?.name || existingCounter?.message?.name;
		if (counterName) {
			await callFrappeMethod(page, "frappe.client.delete", {
				doctype: "Die Tool Counter",
				name: counterName,
			});
		}

		await Promise.all(
			Array.from({ length: 8 }, () =>
				callFrappeMethod(
					page,
					"production_entry_app.production_entry_app.api.get_die_tool_counter",
					{
						die_tool_code: ctx.fg_item,
					}
				)
			)
		);
		const counterAfterReads = await callFrappeMethod(page, "frappe.client.get_value", {
			doctype: "Die Tool Counter",
			filters: JSON.stringify({ die_tool_item: ctx.fg_item }),
			fieldname: "name",
		});
		expect(counterAfterReads?.name || counterAfterReads?.message?.name).toBeFalsy();

		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.openNew();
		await stockEntryPage.fillManufactureEntry(ctx);
		await stockEntryPage.fetchItems();
	});
});
