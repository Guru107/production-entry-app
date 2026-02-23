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

async function createSubmittedStockEntryForReports(
	page,
	ctx,
	rejectionQty = 0,
	unplannedLossRows = []
) {
	const stockEntryPage = new StockEntryPage(page);
	await stockEntryPage.openNew();
	await stockEntryPage.setManufactureFields(ctx, {
		fgQty: 100,
		rejectionQty,
		actualStart: `${ctx.shift_date} 08:00:00`,
		actualEnd: `${ctx.shift_date} 09:00:00`,
	});
	await page.evaluate(async (shiftDate) => {
		await cur_frm.set_value("posting_date", shiftDate);
		await cur_frm.set_value("posting_time", "09:00:00");
	}, ctx.shift_date);
	await stockEntryPage.fetchItems();
	for (const row of unplannedLossRows) {
		await stockEntryPage.addUnplannedLossRow(row);
	}
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

	test("@smoke OEE report shows day-workstation aggregate row", async ({ page }) => {
		await page.goto("/app/home");
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(page, ctx, 0, [
			{ downtime_reason: "Other", start_time: "11:00:00", end_time: "13:00:00" },
		]);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Production OEE Report");
		await reportsPage.runWithDateRange(seeded.posting_date, seeded.posting_date);
		await reportsPage.setFilterByFieldname("custom_workstation", ctx.workstation);
		await reportsPage.setFilterByFieldname("avl_hours_per_day", 24);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const rows = await reportsPage.getRows();
		const seededRow = rows.find(
			(row) =>
				String(row.day || "").includes(seeded.posting_date) &&
				row.workstation === ctx.workstation
		);
		expect(Boolean(seededRow)).toBeTruthy();
		expect(Number(seededRow.total_strokes || 0)).toBeGreaterThan(0);
		expect(Number(seededRow.other_1st || 0)).toBe(2);
	});

	test("@regression OEE report availability responds to avl_hours_per_day filter", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(page, ctx, 0);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Production OEE Report");
		await reportsPage.runWithDateRange(seeded.posting_date, seeded.posting_date);
		await reportsPage.setFilterByFieldname("custom_workstation", ctx.workstation);
		await reportsPage.setFilterByFieldname("avl_hours_per_day", 24);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);
		const rows24 = await reportsPage.getRows();
		const row24 = rows24.find((row) => row.workstation === ctx.workstation);
		expect(Boolean(row24)).toBeTruthy();

		await reportsPage.setFilterByFieldname("avl_hours_per_day", 8);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);
		const filters = await reportsPage.getFilterValues();
		expect(Number(filters.avl_hours_per_day)).toBe(8);

		const rows8 = await reportsPage.getRows();
		const row8 = rows8.find((row) => row.workstation === ctx.workstation);
		expect(Boolean(row8)).toBeTruthy();
		expect(Number(row8.total_strokes || 0)).toBeGreaterThan(0);
	});

	test("@regression OEE report ignores Downtime Entry rows for loss buckets", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(page, ctx, 0);
		await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.create_e2e_downtime_entry",
			{
				prefix,
				from_time: "11:00:00",
				to_time: "13:00:00",
				stop_reason: "Other",
			}
		);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Production OEE Report");
		await reportsPage.runWithDateRange(seeded.posting_date, seeded.posting_date);
		await reportsPage.setFilterByFieldname("custom_workstation", ctx.workstation);
		await reportsPage.setFilterByFieldname("avl_hours_per_day", 24);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);
		const rows = await reportsPage.getRows();
		const seededRow = rows.find((row) => row.workstation === ctx.workstation);
		expect(Boolean(seededRow)).toBeTruthy();
		expect(Number(seededRow.other_1st || 0)).toBe(0);
		expect(Number(seededRow.total_loss_time || 0)).toBe(0);
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

	test("@regression report date range prevents from_date > to_date", async ({ page }) => {
		await page.goto("/app/home");
		const reportsPage = new ReportsPage(page);
		for (const reportName of [
			"Production OEE Report",
			"Operator Efficiency Report",
			"Workstation Efficiency Report",
		]) {
			await reportsPage.open(reportName);
			await reportsPage.setFilterByFieldname("to_date", "2026-02-10");
			await reportsPage.setFilterByFieldname("from_date", "2026-02-11");
			const filters = await reportsPage.getFilterValues();
			expect(filters.from_date).toBe("2026-02-10");
			expect(filters.to_date).toBe("2026-02-10");
		}
	});
});
