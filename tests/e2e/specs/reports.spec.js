const { test, expect } = require("@playwright/test");
const { bootstrapE2E, cleanupE2E } = require("../fixtures/test-data");
const { ReportsPage } = require("../pages/reports-page");
const { ShiftPage } = require("../pages/shift-page");
const { StockEntryPage } = require("../pages/stock-entry-page");
const { getDoc, callFrappeMethod } = require("../fixtures/frappe");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");
const { deleteUserIfExists, ensureUser, loginAs } = require("../fixtures/users");
const { getRoute } = require("../utils/routing");

const ADMIN_USERNAME = process.env.PLAYWRIGHT_USERNAME || "Administrator";
const ADMIN_PASSWORD = process.env.PLAYWRIGHT_PASSWORD || "123";
const TEST_PASSWORD = process.env.PLAYWRIGHT_TEST_USER_PASSWORD || "E2eT3st!Pass#2026";

async function setupFreshContext(page, prefix) {
	await cleanupE2E(page, prefix);
	return await bootstrapE2E(page, prefix);
}

function addDays(dateString, days) {
	const date = new Date(`${dateString}T00:00:00Z`);
	date.setUTCDate(date.getUTCDate() + days);
	return date.toISOString().slice(0, 10);
}

async function createSubmittedStockEntryForReports(
	page,
	ctx,
	rejectionQty = 0,
	unplannedLossRows = [],
	breakupRows = null,
	timeWindow = {}
) {
	const stockEntryPage = new StockEntryPage(page);
	const actualStart = timeWindow.actualStart || `${ctx.shift_date} 08:00:00`;
	const actualEnd = timeWindow.actualEnd || `${ctx.shift_date} 09:00:00`;
	const plannedStart = timeWindow.plannedStart || actualStart;
	const plannedEnd = timeWindow.plannedEnd || actualEnd;
	const postingDate = timeWindow.postingDate || ctx.shift_date;
	await stockEntryPage.openNew();
	await stockEntryPage.setManufactureFields(ctx, {
		fgQty: 100,
		rejectionQty,
		actualStart,
		actualEnd,
		plannedStart,
		plannedEnd,
		postingDate,
	});
	await page.evaluate(async (targetPostingDate) => {
		await cur_frm.set_value("posting_date", targetPostingDate);
		await cur_frm.set_value("posting_time", "09:00:00");
	}, postingDate);
	await stockEntryPage.fetchItems();
	for (const row of unplannedLossRows) {
		await stockEntryPage.addUnplannedLossRow(row);
	}
	if (Array.isArray(breakupRows) && breakupRows.length) {
		await stockEntryPage.setRejectionBreakupRows(breakupRows);
	} else if (rejectionQty > 0) {
		await stockEntryPage.setRejectionBreakupRows([
			{ rejection_reason: "Burr", qty: rejectionQty },
		]);
	}
	await stockEntryPage.saveDraft();
	const name = await page.evaluate(() => window.cur_frm?.doc?.name);
	const doc = await getDoc(page, "Stock Entry", name);
	await callFrappeMethod(page, "frappe.client.submit", { doc: JSON.stringify(doc) });
	const shift = await getDoc(page, "Shift", ctx.shift_name);
	if (shift.status !== "Completed") {
		const shiftPage = new ShiftPage(page);
		await shiftPage.open(ctx.shift_name);
		await shiftPage.endShift();
	}
	return { name, posting_date: doc.posting_date, production_date: ctx.shift_date };
}

test.describe("Production reports", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@regression System Manager can open the native Stock Ledger report", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());
		const reportsPage = new ReportsPage(page);

		await reportsPage.open("Stock Ledger");
		await reportsPage.setFilterByFieldname("company", ctx.company);
		await reportsPage.runWithDateRange(ctx.shift_date, ctx.shift_date);

		await reportsPage.waitForRows(1);
		const rows = await reportsPage.getRows();
		expect(rows.length).toBeGreaterThan(0);
	});

	test("@smoke OEE report shows day-workstation aggregate row", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(
			page,
			ctx,
			0,
			[{ downtime_reason: "Other", start_time: "11:00:00", end_time: "13:00:00" }],
			null,
			{
				actualEnd: `${ctx.shift_date} 13:00:00`,
				plannedEnd: `${ctx.shift_date} 13:00:00`,
			}
		);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Production OEE Report");
		await reportsPage.runWithDateRange(seeded.production_date, seeded.production_date);
		await reportsPage.setFilterByFieldname("custom_pea_workstation", ctx.workstation);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const rows = await reportsPage.getRows();
		const seededRow = rows.find(
			(row) =>
				String(row.day || "").includes(seeded.production_date) &&
				row.workstation === ctx.workstation
		);
		expect(Boolean(seededRow)).toBeTruthy();
		expect(Number(seededRow.total_strokes || 0)).toBeGreaterThan(0);
		expect(Number(seededRow.other_1st || 0)).toBe(2);
		const labels = await reportsPage.getColumnLabels();
		expect(labels.filter((label) => label.startsWith("OEE"))).toEqual(["OEE %"]);
		expect(seededRow).toHaveProperty("oee_mult_pct");
		expect(seededRow).not.toHaveProperty("oee");
	});

	test("@regression OEE quality counts rework as rejected output", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());
		const seeded = await createSubmittedStockEntryForReports(
			page,
			ctx,
			5,
			[],
			[{ rejection_reason: "Burr", qty: 5, is_rework: 1 }]
		);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Production OEE Report");
		await reportsPage.runWithDateRange(seeded.production_date, seeded.production_date);
		await reportsPage.setFilterByFieldname("custom_pea_workstation", ctx.workstation);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const rows = await reportsPage.getRows();
		const seededRow = rows.find(
			(row) =>
				String(row.day || "").includes(seeded.production_date) &&
				row.workstation === ctx.workstation
		);
		expect(Boolean(seededRow)).toBeTruthy();
		expect(Number(seededRow.rejection)).toBe(5);
		expect(Number(seededRow.quality_pct)).toBe(95);
	});

	test("@regression date-driven reports use Completed Shift date instead of Posting Date", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		await createSubmittedStockEntryForReports(
			page,
			ctx,
			5,
			[],
			[
				{ rejection_reason: "Burr", qty: 2, is_rework: 0 },
				{ rejection_reason: "Crack", qty: 3, is_rework: 1 },
			],
			{ postingDate: addDays(ctx.shift_date, -1) }
		);

		const reportsPage = new ReportsPage(page);
		for (const reportName of [
			"Daily Strokes SPM Monitor",
			"Item BOM Rejection Hotspots",
			"Item BOM Rework Hotspots",
			"Operator Daily SPM Report",
			"Operator Efficiency Report",
			"Operator Rejection Performance",
			"Operator Rework Performance",
			"Production OEE Report",
			"Rejection Pareto Report",
			"Rejection PPM Report",
			"Rejection Trend Report",
			"Rework Pareto Report",
			"Rework PPM Report",
			"Rework Trend Report",
			"Workstation Efficiency Report",
			"Workstation Rejection Reason Matrix",
			"Workstation Rework Reason Matrix",
		]) {
			await test.step(reportName, async () => {
				await reportsPage.open(reportName);
				await reportsPage.runWithDateRange(ctx.shift_date, ctx.shift_date);
				await reportsPage.waitForRows(1);
			});
		}
	});

	test("@regression OEE report keeps source-controlled non-prepared mode", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		await setupFreshContext(page, prefix);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Production OEE Report", { ignorePreparedReport: false });
		await reportsPage.clickRefresh();
		const runtimeState = await reportsPage.getRuntimeState();
		expect(runtimeState.reportName).toBe("Production OEE Report");
		expect(runtimeState.preparedReport).toBe(0);
		expect(runtimeState.ignorePreparedReport).toBe(false);
		expect(new URL(runtimeState.href).searchParams.has("ignore_prepared_report")).toBe(false);
	});

	test("@regression OEE report derives availability from shift and removes avl-hours filter", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(page, ctx, 0);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Production OEE Report");
		await reportsPage.runWithDateRange(seeded.production_date, seeded.production_date);
		await reportsPage.setFilterByFieldname("custom_pea_workstation", ctx.workstation);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);
		const filters = await reportsPage.getFilterValues();
		expect(Object.prototype.hasOwnProperty.call(filters, "avl_hours_per_day")).toBeFalsy();

		const rows = await reportsPage.getRows();
		const row = rows.find((item) => item.workstation === ctx.workstation);
		expect(Boolean(row)).toBeTruthy();
		expect(Number(row.total_strokes || 0)).toBeGreaterThan(0);
		expect(row.avl_time_hrs).toBeDefined();
	});

	test("@regression OEE report ignores Downtime Entry rows for loss buckets", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.e2e_api.create_e2e_downtime_entry",
			{
				prefix,
				from_time: "11:00:00",
				to_time: "13:00:00",
				stop_reason: "Other",
			}
		);
		const seeded = await createSubmittedStockEntryForReports(page, ctx, 0);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Production OEE Report");
		await reportsPage.runWithDateRange(seeded.production_date, seeded.production_date);
		await reportsPage.setFilterByFieldname("custom_pea_workstation", ctx.workstation);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);
		const rows = await reportsPage.getRows();
		const seededRow = rows.find((row) => row.workstation === ctx.workstation);
		expect(Boolean(seededRow)).toBeTruthy();
		expect(Number(seededRow.other_1st || 0)).toBe(0);
		expect(Number(seededRow.total_loss_time || 0)).toBe(0);
	});

	test("@regression Operator report honors operator and shift filters", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(page, ctx, 0);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Operator Efficiency Report");
		await reportsPage.runWithDateRange(seeded.production_date, seeded.production_date);
		await reportsPage.setFilterByFieldname("custom_pea_operator", ctx.operator);
		await reportsPage.setFilterByFieldname("custom_pea_shift", ctx.shift_name);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const filters = await reportsPage.getFilterValues();
		expect(filters.custom_pea_operator).toBe(ctx.operator);
		expect(filters.custom_pea_shift).toBe(ctx.shift_name);

		const rows = await reportsPage.getRows();
		expect(rows.some((row) => row.operator === ctx.operator)).toBeTruthy();
	});

	test("@regression Operator Daily SPM report loads grouped operator-workstation rows", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		await createSubmittedStockEntryForReports(page, ctx, 0, [
			{ downtime_reason: "Setup Time", start_time: "08:00:00", end_time: "08:30:00" },
		]);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Operator Daily SPM Report");
		await reportsPage.runWithDateRange(ctx.shift_date, ctx.shift_date);
		await reportsPage.setFilterByFieldname("custom_pea_operator", ctx.operator);
		await reportsPage.setFilterByFieldname("custom_pea_workstation", ctx.workstation);
		await reportsPage.setFilterByFieldname("custom_pea_shift", ctx.shift_name);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const rows = await reportsPage.getRows();
		const row = rows.find(
			(item) => item.operator === ctx.operator && item.workstation === ctx.workstation
		);
		expect(Boolean(row)).toBeTruthy();
		expect(Number(row.total_strokes || 0)).toBeGreaterThan(0);
		expect(Number(row.working_hours || 0)).toBeGreaterThan(0);
		expect(Number(row.spm || 0)).toBeGreaterThan(0);
	});

	test("@regression Workstation report honors workstation and shift filters", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(page, ctx, 0);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Workstation Efficiency Report");
		await reportsPage.runWithDateRange(seeded.production_date, seeded.production_date);
		await reportsPage.setFilterByFieldname("custom_pea_workstation", ctx.workstation);
		await reportsPage.setFilterByFieldname("custom_pea_shift", ctx.shift_name);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const filters = await reportsPage.getFilterValues();
		expect(filters.custom_pea_workstation).toBe(ctx.workstation);
		expect(filters.custom_pea_shift).toBe(ctx.shift_name);

		const rows = await reportsPage.getRows();
		expect(rows.some((row) => row.workstation === ctx.workstation)).toBeTruthy();
	});

	test("@regression Die Tool report honors item filter and shows maintenance columns", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
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

	test("@regression Rejection Pareto report loads and renders chart with grouped reasons", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(
			page,
			ctx,
			8,
			[],
			[
				{ rejection_reason: "Crack", qty: 5 },
				{ rejection_reason: "Burr", qty: 3 },
			]
		);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Rejection Pareto Report");
		await reportsPage.runWithDateRange(seeded.production_date, seeded.production_date);
		await reportsPage.setFilterByFieldname("custom_pea_workstation", ctx.workstation);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const rows = await reportsPage.getRows();
		expect(rows.length).toBeGreaterThan(0);
		expect(rows.some((row) => row.rejection_reason === "Crack")).toBeTruthy();
		expect(await reportsPage.hasChart()).toBeTruthy();
	});

	test("@regression Rejection Trend report supports daily and monthly grain", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);

		await createSubmittedStockEntryForReports(page, ctx, 10, [], null, {
			actualStart: `${ctx.shift_date} 08:00:00`,
			actualEnd: `${ctx.shift_date} 09:00:00`,
		});
		await createSubmittedStockEntryForReports(page, ctx, 6, [], null, {
			actualStart: `${ctx.shift_date} 09:00:00`,
			actualEnd: `${ctx.shift_date} 10:00:00`,
		});

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Rejection Trend Report");
		await reportsPage.runWithDateRange(ctx.shift_date, ctx.shift_date);
		await reportsPage.setFilterByFieldname("time_grain", "Daily");
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);
		const dailyRows = await reportsPage.getRows();
		expect(dailyRows.length).toBeGreaterThan(0);
		expect(await reportsPage.hasChart()).toBeTruthy();

		await reportsPage.setFilterByFieldname("time_grain", "Monthly");
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);
		const monthlyFilters = await reportsPage.getFilterValues();
		expect(monthlyFilters.time_grain).toBe("Monthly");
		const monthlyRows = await reportsPage.getRows();
		expect(monthlyRows.length).toBeGreaterThan(0);
	});

	test("@regression Workstation rejection matrix renders dynamic reason columns", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(
			page,
			ctx,
			9,
			[],
			[
				{ rejection_reason: "Crack", qty: 6 },
				{ rejection_reason: "Burr", qty: 3 },
			]
		);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Workstation Rejection Reason Matrix");
		await reportsPage.runWithDateRange(seeded.production_date, seeded.production_date);
		await reportsPage.setFilterByFieldname("custom_pea_workstation", ctx.workstation);
		await reportsPage.setFilterByFieldname("top_n_reasons", 2);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const rows = await reportsPage.getRows();
		expect(rows.some((row) => row.workstation === ctx.workstation)).toBeTruthy();
		const labels = await reportsPage.getColumnLabels();
		expect(labels).toContain("Crack");
	});

	test("@regression Operator rejection report shows top reasons and rates", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(
			page,
			ctx,
			8,
			[],
			[
				{ rejection_reason: "Crack", qty: 6 },
				{ rejection_reason: "Burr", qty: 2 },
			]
		);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Operator Rejection Performance");
		await reportsPage.runWithDateRange(seeded.production_date, seeded.production_date);
		await reportsPage.setFilterByFieldname("custom_pea_operator", ctx.operator);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const rows = await reportsPage.getRows();
		const row = rows.find((item) => item.operator === ctx.operator);
		expect(Boolean(row)).toBeTruthy();
		expect(Number(row.rejection_rate_pct || 0)).toBeGreaterThan(0);
		expect(String(row.top_3_reasons || "")).toContain("Crack");
	});

	test("@regression Item BOM hotspots report shows dominant reason", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(
			page,
			ctx,
			7,
			[],
			[
				{ rejection_reason: "Blank Cut", qty: 4 },
				{ rejection_reason: "Burr", qty: 3 },
			]
		);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Item BOM Rejection Hotspots");
		await reportsPage.runWithDateRange(seeded.production_date, seeded.production_date);
		await reportsPage.setFilterByFieldname("fg_item", ctx.fg_item);
		await reportsPage.setFilterByFieldname("custom_pea_shift", ctx.shift_name);
		await reportsPage.setFilterByFieldname("custom_pea_workstation", ctx.workstation);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const rows = await reportsPage.getRows();
		expect(rows.length).toBeGreaterThan(0);
		expect(rows.some((row) => row.item_code === ctx.fg_item)).toBeTruthy();
		expect(
			rows.some((row) => String(row.dominant_reason || "").includes("Blank Cut"))
		).toBeTruthy();
	});

	test("@regression Rework Pareto report renders seeded rework data", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		const seeded = await createSubmittedStockEntryForReports(
			page,
			ctx,
			8,
			[],
			[
				{ rejection_reason: "Crack", qty: 5, is_rework: 1 },
				{ rejection_reason: "Burr", qty: 3, is_rework: 0 },
			]
		);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Rework Pareto Report");
		await reportsPage.runWithDateRange(seeded.production_date, seeded.production_date);
		await reportsPage.setFilterByFieldname("custom_pea_workstation", ctx.workstation);
		await reportsPage.setFilterByFieldname("custom_pea_shift", ctx.shift_name);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);
		const rows = await reportsPage.getRows();
		expect(rows.length).toBeGreaterThan(0);
		expect(rows.some((row) => row.rejection_reason === "Crack")).toBeTruthy();
		expect(await reportsPage.hasChart()).toBeTruthy();
	});

	test("@regression Pending Rework shows pool, warehouse balance, and source drill-down", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());
		const seeded = await createSubmittedStockEntryForReports(
			page,
			ctx,
			5,
			[],
			[{ rejection_reason: "Crack", qty: 5, is_rework: 1 }]
		);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Pending Rework");
		await reportsPage.setFilterByFieldname("item_code", ctx.fg_item);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(2);

		const rows = await reportsPage.getRows();
		const summary = rows.find(
			(row) => row.item_code === ctx.fg_item && Number(row.indent) === 0
		);
		const detail = rows.find(
			(row) => row.source_entry === seeded.name && row.rejection_reason === "Crack"
		);
		expect(summary).toBeTruthy();
		expect(Number(summary.derived_pending_qty)).toBe(5);
		expect(Number(summary.rejection_warehouse_balance)).toBe(5);
		expect(Number(summary.pool_balance_difference)).toBe(0);
		expect(detail).toBeTruthy();
		expect(Number(detail.flagged_rework_qty)).toBe(5);
	});

	test("@regression PEA Read Only can open Pending Rework without source access", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const email = `e2e.pending.rework.${Date.now()}@example.com`;
		await ensureUser(page, {
			email,
			firstName: "E2E Pending Rework",
			password: TEST_PASSWORD,
			roles: ["PEA Read Only"],
		});

		try {
			await loginAs(page, email, TEST_PASSWORD);
			const reportsPage = new ReportsPage(page);
			await reportsPage.open("Pending Rework");
			await reportsPage.clickRefresh();
			const labels = await reportsPage.getColumnLabels();
			expect(labels).toContain("Derived Pending Qty");
			expect(labels).toContain("Rejection Warehouse Balance");
		} finally {
			await loginAs(page, ADMIN_USERNAME, ADMIN_PASSWORD);
			await deleteUserIfExists(page, email);
		}
	});

	test("@regression Rework Trend and Rework PPM reports render rework aggregates", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		await createSubmittedStockEntryForReports(
			page,
			ctx,
			10,
			[],
			[
				{ rejection_reason: "Crack", qty: 6, is_rework: 1 },
				{ rejection_reason: "Burr", qty: 4, is_rework: 0 },
			]
		);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Rework Trend Report");
		await reportsPage.runWithDateRange(ctx.shift_date, ctx.shift_date);
		await reportsPage.setFilterByFieldname("custom_pea_workstation", ctx.workstation);
		await reportsPage.setFilterByFieldname("custom_pea_shift", ctx.shift_name);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);
		const trendRows = await reportsPage.getRows();
		expect(trendRows.length).toBeGreaterThan(0);
		const trendRow = trendRows.find((row) => Number(row.rework_qty || 0) > 0);
		expect(Boolean(trendRow)).toBeTruthy();
		expect(await reportsPage.hasChart()).toBeTruthy();

		await reportsPage.open("Rework PPM Report");
		await reportsPage.runWithDateRange(ctx.shift_date, ctx.shift_date);
		await reportsPage.setFilterByFieldname("custom_pea_workstation", ctx.workstation);
		await reportsPage.setFilterByFieldname("custom_pea_shift", ctx.shift_name);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);
		const ppmRows = await reportsPage.getRows();
		expect(ppmRows.length).toBeGreaterThan(0);
		const ppmRow = ppmRows.find((row) => Number(row.ppm || 0) > 0);
		expect(Boolean(ppmRow)).toBeTruthy();
	});

	test("@regression Operator/Item/Workstation rework reports load with rework data", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		await createSubmittedStockEntryForReports(
			page,
			ctx,
			9,
			[],
			[
				{ rejection_reason: "Crack", qty: 5, is_rework: 1 },
				{ rejection_reason: "Burr", qty: 4, is_rework: 0 },
			]
		);

		const reportsPage = new ReportsPage(page);
		await reportsPage.open("Operator Rework Performance");
		await reportsPage.runWithDateRange(ctx.shift_date, ctx.shift_date);
		await reportsPage.setFilterByFieldname("custom_pea_operator", ctx.operator);
		await reportsPage.setFilterByFieldname("custom_pea_shift", ctx.shift_name);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);
		const operatorRows = await reportsPage.getRows();
		const operatorRow = operatorRows.find((row) => row.operator === ctx.operator);
		expect(operatorRow).toBeTruthy();
		expect(Number(operatorRow?.rework_qty || 0)).toBeGreaterThan(0);

		await reportsPage.open("Item BOM Rework Hotspots");
		await reportsPage.runWithDateRange(ctx.shift_date, ctx.shift_date);
		await reportsPage.setFilterByFieldname("fg_item", ctx.fg_item);
		await reportsPage.setFilterByFieldname("custom_pea_shift", ctx.shift_name);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);
		const itemRows = await reportsPage.getRows();
		expect(itemRows.some((row) => row.item_code === ctx.fg_item)).toBeTruthy();

		await reportsPage.open("Workstation Rework Reason Matrix");
		await reportsPage.runWithDateRange(ctx.shift_date, ctx.shift_date);
		await reportsPage.setFilterByFieldname("custom_pea_workstation", ctx.workstation);
		await reportsPage.setFilterByFieldname("custom_pea_shift", ctx.shift_name);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);
		const workstationRows = await reportsPage.getRows();
		expect(workstationRows.some((row) => row.workstation === ctx.workstation)).toBeTruthy();
	});

	test("@regression report date range prevents from_date > to_date", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const reportsPage = new ReportsPage(page);
		for (const reportName of [
			"Daily Strokes SPM Monitor",
			"Production OEE Report",
			"Operator Efficiency Report",
			"Operator Daily SPM Report",
			"Workstation Efficiency Report",
			"Rejection Pareto Report",
			"Rejection PPM Report",
			"Rejection Trend Report",
			"Workstation Rejection Reason Matrix",
			"Operator Rejection Performance",
			"Item BOM Rejection Hotspots",
			"Rework Pareto Report",
			"Rework Trend Report",
			"Rework PPM Report",
			"Operator Rework Performance",
			"Item BOM Rework Hotspots",
			"Workstation Rework Reason Matrix",
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
