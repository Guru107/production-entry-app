const { test, expect } = require("@playwright/test");
const { bootstrapE2E, cleanupE2E } = require("../fixtures/test-data");
const { getDoc, callFrappeMethod, retryOnContextDestroyed } = require("../fixtures/frappe");
const { StockEntryPage } = require("../pages/stock-entry-page");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");
const { getRoute } = require("../utils/routing");

async function setupFreshContext(page, prefix) {
	await cleanupE2E(page, prefix);
	return await bootstrapE2E(page, prefix);
}

async function setSystemFloatPrecision(page, prefix, precision) {
	await callFrappeMethod(
		page,
		"production_entry_app.production_entry_app.e2e_api.set_e2e_system_float_precision",
		{ prefix, precision }
	);
}

async function createManufactureEntry(page, ctx, options = {}) {
	const stockEntryPage = new StockEntryPage(page);
	await stockEntryPage.openNew();
	await stockEntryPage.setManufactureFields(ctx, options);
	await stockEntryPage.fetchItems();
	return stockEntryPage;
}

test.describe("Die tool metrics and counter", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@smoke submitted manufacture entry populates duration SPM cycle and efficiency", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await createManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 5,
		});
		await stockEntryPage.setRejectionBreakupRows([{ rejection_reason: "Burr", qty: 5 }]);
		await stockEntryPage.saveAndSubmit();

		const stockEntryName = await page.evaluate(() => window.cur_frm?.doc?.name);
		const stockEntry = await getDoc(page, "Stock Entry", stockEntryName);

		expect(stockEntry.docstatus).toBe(1);
		expect(Number(stockEntry.custom_pea_actual_duration_mins || 0)).toBeGreaterThan(0);
		expect(Number(stockEntry.custom_pea_production_time_mins || 0)).toBeGreaterThan(0);
		expect(Number(stockEntry.custom_pea_actual_spm || 0)).toBeGreaterThan(0);
		expect(Number(stockEntry.custom_pea_cycle_time_sec || 0)).toBeGreaterThan(0);
		expect(Number(stockEntry.custom_pea_operator_efficiency_pct || 0)).toBeGreaterThan(0);
	});

	test("@regression planned break overlap reduces net production time", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await createManufactureEntry(page, ctx, {
			fgQty: 30,
			rejectionQty: 0,
			actualStart: `${ctx.shift_date} 08:50:00`,
			actualEnd: `${ctx.shift_date} 09:20:00`,
		});
		await stockEntryPage.saveDraft();
		await page.waitForFunction(() => {
			const name = window.cur_frm?.doc?.name || "";
			return Boolean(name) && !String(name).startsWith("new-stock-entry");
		});

		const stockEntryName = await page.evaluate(() => window.cur_frm?.doc?.name);
		const stockEntry = await getDoc(page, "Stock Entry", stockEntryName);
		expect(Number(stockEntry.custom_pea_actual_duration_mins || 0)).toBe(30);
		// Shift planned Tea Break is 09:00-09:10; overlap should be deducted.
		expect(Number(stockEntry.custom_pea_production_time_mins || 0)).toBe(20);
	});

	test("@regression missing actual end keeps metrics empty", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await createManufactureEntry(page, ctx, {
			fgQty: 80,
			rejectionQty: 0,
			actualStart: `${ctx.shift_date} 08:00:00`,
			actualEnd: null,
		});
		await stockEntryPage.saveDraft();

		const stockEntryName = await page.evaluate(() => window.cur_frm?.doc?.name);
		const stockEntry = await getDoc(page, "Stock Entry", stockEntryName);
		expect(stockEntry.custom_pea_actual_duration_mins).toBeFalsy();
		expect(stockEntry.custom_pea_production_time_mins).toBeFalsy();
		expect(stockEntry.custom_pea_actual_spm).toBeFalsy();
		expect(stockEntry.custom_pea_cycle_time_sec).toBeFalsy();
		expect(stockEntry.custom_pea_operator_efficiency_pct).toBeFalsy();
	});

	test("@regression zero-duration clears metrics", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await createManufactureEntry(page, ctx, {
			fgQty: 80,
			rejectionQty: 0,
			actualStart: `${ctx.shift_date} 08:00:00`,
			actualEnd: `${ctx.shift_date} 08:00:00`,
		});
		await stockEntryPage.saveDraft();

		const stockEntryName = await page.evaluate(() => window.cur_frm?.doc?.name);
		const stockEntry = await getDoc(page, "Stock Entry", stockEntryName);
		expect(stockEntry.custom_pea_actual_duration_mins).toBeFalsy();
		expect(stockEntry.custom_pea_production_time_mins).toBeFalsy();
		expect(stockEntry.custom_pea_actual_spm).toBeFalsy();
		expect(stockEntry.custom_pea_cycle_time_sec).toBeFalsy();
		expect(stockEntry.custom_pea_operator_efficiency_pct).toBeFalsy();
	});

	test("@regression full deducted-loss window shows metrics note on stock entry", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await createManufactureEntry(page, ctx, {
			fgQty: 80,
			rejectionQty: 0,
			actualStart: `${ctx.shift_date} 08:00:00`,
			actualEnd: `${ctx.shift_date} 08:20:00`,
		});
		await stockEntryPage.addUnplannedLossRow({
			downtime_reason: "Setup Time",
			start_time: "08:10:00",
			end_time: "08:20:00",
		});
		await stockEntryPage.saveDraft();

		const stockEntryName = await page.evaluate(() => window.cur_frm?.doc?.name);
		const stockEntry = await getDoc(page, "Stock Entry", stockEntryName);
		expect(Number(stockEntry.custom_pea_production_time_mins || 0)).toBe(0);
		expect(Number(stockEntry.custom_pea_actual_spm || 0)).toBe(0);
		expect(Number(stockEntry.custom_pea_operator_efficiency_pct || 0)).toBe(0);
		expect(String(stockEntry.custom_pea_metrics_note || "")).toContain("deducted loss time");

		const metricsNote = page.locator('[data-fieldname="custom_pea_metrics_note"]');
		await expect(metricsNote).toContainText("deducted loss time");
		await expect(metricsNote).toContainText("full actual window");
	});

	test("@regression high utilization sets maintenance due and shows warning headline", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.e2e_api.reset_e2e_die_tool_counter",
			{
				prefix: lifecycle.getPrefix(),
			}
		);
		await callFrappeMethod(page, "frappe.client.set_value", {
			doctype: "Die Tool Counter",
			name: ctx.fg_item,
			fieldname: "current_stroke_count",
			value: 900,
		});
		await callFrappeMethod(page, "frappe.client.set_value", {
			doctype: "Die Tool Counter",
			name: ctx.fg_item,
			fieldname: "stroke_capacity",
			value: 1000,
		});
		await callFrappeMethod(page, "frappe.client.set_value", {
			doctype: "Die Tool Counter",
			name: ctx.fg_item,
			fieldname: "warning_threshold_pct",
			value: 90,
		});

		const stockEntryPage = await createManufactureEntry(page, ctx, {
			fgQty: 10,
			rejectionQty: 0,
		});
		await stockEntryPage.saveDraft();

		const stockEntryName = await page.evaluate(() => window.cur_frm?.doc?.name);
		const stockEntry = await getDoc(page, "Stock Entry", stockEntryName);
		expect(Number(stockEntry.custom_pea_die_tool_utilization_pct || 0)).toBeGreaterThanOrEqual(
			90
		);
		expect(Number(stockEntry.custom_pea_die_tool_maintenance_due || 0)).toBe(1);
		await page.waitForFunction(
			() =>
				/needs maintenance/i.test(String(window.cur_frm?.__peaDieToolAlertMessage || "")),
			undefined,
			{ timeout: 10000 }
		);
	});

	test("@regression die-tool warning headline keeps API precision instead of local toFixed", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const prefix = `${lifecycle.getPrefix()}-die-tool-precision`;
		const ctx = await setupFreshContext(page, prefix);
		await setSystemFloatPrecision(page, prefix, 4);

		const stockEntryPage = await createManufactureEntry(page, ctx, {
			fgQty: 10,
			rejectionQty: 0,
		});
		await retryOnContextDestroyed(page, async () => {
			await page.waitForFunction(
				() =>
					window.cur_frm?.doctype === "Stock Entry" &&
					window.cur_frm?.doc?.docstatus === 0 &&
					typeof window.cur_frm?.script_manager?.trigger === "function" &&
					typeof window.frappe?.call === "function"
			);
			await page.evaluate(async () => {
				const originalCall = window.__peaOriginalFrappeCall || frappe.call.bind(frappe);
				window.__peaOriginalFrappeCall = originalCall;
				frappe.call = function (options) {
					if (
						options?.method ===
						"production_entry_app.production_entry_app.api.get_die_tool_counter"
					) {
						options.callback?.({
							message: {
								die_tool_code: window.cur_frm?.doc?.fg_item || "ITEM-001",
								has_die_tool: 1,
								current_strokes: 901.2345,
								stroke_capacity: 1000,
								warning_threshold_pct: 90,
								utilization_pct: 90.12345,
								is_maintenance_due: 1,
							},
						});
						return Promise.resolve();
					}
					return originalCall(options);
				};
				await window.cur_frm?.script_manager?.trigger("custom_pea_rejection_qty");
			});
		});

		await stockEntryPage.saveDraft();
		await page.waitForFunction(
			() => String(window.cur_frm?.__peaDieToolAlertMessage || "").includes("90.12345%"),
			undefined,
			{ timeout: 10000 }
		);
	});

	test("@regression die-tool counter increases on submit and decreases on cancel", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const before = await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.get_die_tool_counter",
			{ die_tool_code: ctx.fg_item }
		);

		const stockEntryPage = await createManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 10,
		});
		await stockEntryPage.setRejectionBreakupRows([
			{ rejection_reason: "Burr", qty: 4 },
			{ rejection_reason: "Crack", qty: 6 },
		]);
		await stockEntryPage.saveAndSubmit();

		const stockEntryName = await page.evaluate(() => window.cur_frm?.doc?.name);
		const afterSubmit = await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.get_die_tool_counter",
			{ die_tool_code: ctx.fg_item }
		);
		expect(Number(afterSubmit.current_strokes)).toBeGreaterThan(
			Number(before.current_strokes)
		);

		const submittedDoc = await getDoc(page, "Stock Entry", stockEntryName);
		await callFrappeMethod(page, "frappe.client.cancel", {
			doctype: "Stock Entry",
			name: stockEntryName,
			doc: JSON.stringify(submittedDoc),
		});

		const afterCancel = await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.get_die_tool_counter",
			{ die_tool_code: ctx.fg_item }
		);
		expect(Number(afterCancel.current_strokes)).toBe(Number(before.current_strokes));
	});
});
