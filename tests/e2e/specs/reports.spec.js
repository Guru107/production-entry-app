const { test, expect } = require("@playwright/test");
const { bootstrapE2E, cleanupE2E } = require("../fixtures/test-data");
const { ReportsPage } = require("../pages/reports-page");
const { StockEntryPage } = require("../pages/stock-entry-page");
const { getDoc, callFrappeMethod } = require("../fixtures/frappe");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");

async function setupFreshContext(page, prefix) {
	await cleanupE2E(page, prefix);
	return await bootstrapE2E(page, prefix);
}

async function createSubmittedStockEntryForReports(page, ctx, rejectionQty = 0) {
	const stockEntryPage = new StockEntryPage(page);
	await stockEntryPage.openNew();
	await stockEntryPage.setManufactureFields(ctx, {
		fgQty: 100,
		rejectionQty,
		actualStart: `${ctx.shift_date} 08:00:00`,
		actualEnd: `${ctx.shift_date} 09:00:00`,
	});
	await stockEntryPage.fetchItems();
	if (rejectionQty > 0) {
		await stockEntryPage.setRejectionBreakupRows([
			{ rejection_reason: "Burr", qty: rejectionQty },
		]);
	}
	await stockEntryPage.saveDraft();
	const name = await page.evaluate(() => window.cur_frm?.doc?.name);
	const doc = await getDoc(page, "Stock Entry", name);
	await callFrappeMethod(page, "frappe.client.submit", { doc: JSON.stringify(doc) });
	return { name, posting_date: doc.posting_date };
}

test.describe("Production reports", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@smoke OEE report shows seeded entry for date range", async ({ page }) => {
		await page.goto("/app/home");
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(page, ctx, 0);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Production OEE Report");
		await reportsPage.runWithDateRange(seeded.posting_date, seeded.posting_date);
		await reportsPage.waitForRows(1);

		const rows = await reportsPage.getRows();
		const seededRow = rows.find((row) => row.stock_entry === seeded.name);
		expect(Boolean(seededRow)).toBeTruthy();
		expect(String(seededRow.posting_date)).toContain(seeded.posting_date);
	});

	test("@regression OEE report honors fg_item filter", async ({ page }) => {
		await page.goto("/app/home");
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(page, ctx, 0);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Production OEE Report");
		await reportsPage.runWithDateRange(seeded.posting_date, seeded.posting_date);
		await reportsPage.setFilterByFieldname("fg_item", ctx.fg_item);
		await reportsPage.setFilterByFieldname("custom_shift", ctx.shift_name);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const filters = await reportsPage.getFilterValues();
		expect(filters.fg_item).toBe(ctx.fg_item);
		expect(filters.custom_shift).toBe(ctx.shift_name);

		const rows = await reportsPage.getRows();
		const seededRow = rows.find((row) => row.stock_entry === seeded.name);
		expect(Boolean(seededRow)).toBeTruthy();
		expect(seededRow.item_code).toBe(ctx.fg_item);
	});

	test("@regression Operator report honors operator and shift filters", async ({ page }) => {
		await page.goto("/app/home");
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(page, ctx, 0);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Operator Efficiency Report");
		await reportsPage.runWithDateRange(seeded.posting_date, seeded.posting_date);
		await reportsPage.setFilterByFieldname("custom_operator", ctx.operator);
		await reportsPage.setFilterByFieldname("custom_shift", ctx.shift_name);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const filters = await reportsPage.getFilterValues();
		expect(filters.custom_operator).toBe(ctx.operator);
		expect(filters.custom_shift).toBe(ctx.shift_name);

		const rows = await reportsPage.getRows();
		expect(rows.some((row) => row.operator === ctx.operator)).toBeTruthy();
	});

	test("@regression Workstation report honors workstation and shift filters", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(page, ctx, 0);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Workstation Efficiency Report");
		await reportsPage.runWithDateRange(seeded.posting_date, seeded.posting_date);
		await reportsPage.setFilterByFieldname("custom_workstation", ctx.workstation);
		await reportsPage.setFilterByFieldname("custom_shift", ctx.shift_name);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const filters = await reportsPage.getFilterValues();
		expect(filters.custom_workstation).toBe(ctx.workstation);
		expect(filters.custom_shift).toBe(ctx.shift_name);

		const rows = await reportsPage.getRows();
		expect(rows.some((row) => row.workstation === ctx.workstation)).toBeTruthy();
	});

	test("@regression Die Tool report honors item filter and shows maintenance columns", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		await createSubmittedStockEntryForReports(page, ctx, 0);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Die Tool Stroke and Maintenance Report");
		await reportsPage.setFilterByFieldname("item_code", ctx.fg_item);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const filters = await reportsPage.getFilterValues();
		expect(filters.item_code).toBe(ctx.fg_item);

		const rows = await reportsPage.getRows();
		const filteredRow = rows.find((row) => row.die_tool_item === ctx.fg_item);
		expect(Boolean(filteredRow)).toBeTruthy();
		expect(filteredRow.utilization_pct).toBeDefined();
		expect(filteredRow.maintenance_due).toBeDefined();
		expect(filteredRow.maintenance_count).toBeDefined();
	});
});
