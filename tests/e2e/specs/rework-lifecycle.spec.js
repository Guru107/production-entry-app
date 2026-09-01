const { test, expect } = require("@playwright/test");

const { expectValidationError } = require("../fixtures/assertions");
const { callFrappeMethod, getDoc, saveForm, setFieldValue } = require("../fixtures/frappe");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");
const { ensureUser, loginAs } = require("../fixtures/users");
const { ReportsPage } = require("../pages/reports-page");
const { StockEntryPage } = require("../pages/stock-entry-page");
const { getRoute } = require("../utils/routing");

const ADMIN_USERNAME =
	process.env.PLAYWRIGHT_ADMIN_USERNAME || process.env.PLAYWRIGHT_USERNAME || "Administrator";
const ADMIN_PASSWORD =
	process.env.PLAYWRIGHT_ADMIN_PASSWORD || process.env.PLAYWRIGHT_PASSWORD || "123";
const TEST_PASSWORD = process.env.PLAYWRIGHT_TEST_USER_PASSWORD || "E2eT3st!Pass#2026";

async function seedLifecycle(page, prefix) {
	await page.goto(getRoute("/home"));
	return await callFrappeMethod(
		page,
		"production_entry_app.production_entry_app.e2e_api.create_e2e_rework_lifecycle_source",
		{ prefix, qty: 5 }
	);
}

async function fillReworkEntry(page, context, options = {}) {
	const stockEntryPage = new StockEntryPage(page);
	await stockEntryPage.openNew();
	await setFieldValue(page, "stock_entry_type", context.rework_stock_entry_type);
	await page.waitForFunction((expectedType) => {
		const frm = window.cur_frm;
		return (
			frm?.doc?.__pea_rework_stock_entry_type === expectedType &&
			frm?.get_field?.("custom_pea_rework_type")?.$wrapper?.is(":visible")
		);
	}, context.rework_stock_entry_type);
	await setFieldValue(page, "company", context.company);
	await setFieldValue(page, "branch", context.branch);
	await stockEntryPage.waitForFieldValue("from_warehouse", context.rejection_warehouse);
	await stockEntryPage.setPostingDate(context.shift_date);
	await setFieldValue(page, "to_warehouse", context.fg_warehouse);
	await setFieldValue(page, "custom_pea_rework_type", context.rework_type);
	await stockEntryPage.waitForFieldValue(
		"custom_pea_rework_workstation",
		context.rework_workstation
	);
	await page.evaluate(
		async ({ itemCode, qty, targetWarehouse }) => {
			cur_frm.clear_table("items");
			const row = cur_frm.add_child("items");
			await frappe.model.set_value(row.doctype, row.name, "item_code", itemCode);
			await frappe.after_ajax();
			await frappe.model.set_value(row.doctype, row.name, "qty", qty);
			await frappe.model.set_value(row.doctype, row.name, "t_warehouse", targetWarehouse);
			if (row.s_warehouse !== cur_frm.doc.from_warehouse) {
				throw new Error(
					"Rework item source did not inherit the configured rejection warehouse"
				);
			}
			cur_frm.refresh_field("items");
		},
		{
			itemCode: context.fg_item,
			qty: options.qty ?? 5,
			targetWarehouse: context.fg_warehouse,
		}
	);
	if (options.includeTimes !== false) {
		await setFieldValue(
			page,
			"custom_pea_rework_actual_start",
			`${context.shift_date} 10:00:00`
		);
		await setFieldValue(
			page,
			"custom_pea_rework_actual_end",
			`${context.shift_date} 11:00:00`
		);
	}
	if (options.includeOperator !== false) {
		await page.evaluate((operator) => {
			cur_frm.add_child("custom_pea_rework_operators", { operator });
			cur_frm.refresh_field("custom_pea_rework_operators");
		}, context.operator);
	}
	return stockEntryPage;
}

async function getBinQty(page, itemCode, warehouse) {
	const result = await callFrappeMethod(page, "frappe.client.get_value", {
		doctype: "Bin",
		filters: JSON.stringify({ item_code: itemCode, warehouse }),
		fieldname: "actual_qty",
	});
	return Number(result?.actual_qty || 0);
}

async function getReportRows(page, reportName, context) {
	const reportsPage = new ReportsPage(page);
	await reportsPage.open(reportName);
	if (reportName === "Rework Register") {
		await reportsPage.runWithDateRange(context.shift_date, context.shift_date);
	}
	await reportsPage.setFilterByFieldname("item_code", context.fg_item);
	await reportsPage.clickRefresh();
	return await reportsPage.getRows();
}

async function expectSaveValidation(page, pattern) {
	const message = expectValidationError(page, pattern, 30_000);
	const save = page.evaluate(async () => {
		try {
			await cur_frm.save();
		} catch (error) {
			// The visible validation message is the public behavior asserted by the caller.
		}
	});
	await Promise.all([message, save]);
}

async function expectSubmitValidation(page, pattern) {
	const message = expectValidationError(page, pattern, 30_000);
	const submit = saveForm(page, "Submit").catch(() => {});
	await Promise.all([message, submit]);
}

test.describe("Rework full lifecycle", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@regression submits, values, reports, authorizes, and cancels rework", async ({
		page,
	}) => {
		const context = await seedLifecycle(page, lifecycle.getPrefix());
		const stockEntryPage = await fillReworkEntry(page, context);
		await setFieldValue(page, "custom_pea_shift", context.shift_name);
		await expect(page.locator('[data-fieldname="custom_pea_shift"]')).toBeVisible();
		expect(
			await page.evaluate(() => ({
				company: cur_frm.doc.company,
				branch: cur_frm.doc.branch,
				fromWarehouse: cur_frm.doc.from_warehouse,
				toWarehouse: cur_frm.doc.to_warehouse,
			}))
		).toEqual({
			company: context.company,
			branch: context.branch,
			fromWarehouse: context.rejection_warehouse,
			toWarehouse: context.fg_warehouse,
		});
		await stockEntryPage.saveAndSubmit();
		const reworkEntry = await page.evaluate(() => window.cur_frm?.doc?.name);
		const submitted = await getDoc(page, "Stock Entry", reworkEntry);

		expect(submitted.docstatus).toBe(1);
		expect(submitted.custom_pea_rework_workstation).toBe(context.workstation);
		expect(Number(submitted.custom_pea_rework_cost)).toBe(120);
		expect(Number(submitted.items[0].additional_cost)).toBe(120);
		expect(Number(submitted.items[0].valuation_rate)).toBeGreaterThan(
			Number(submitted.items[0].basic_rate)
		);
		expect(await getBinQty(page, context.fg_item, context.rejection_warehouse)).toBe(
			context.rejection_warehouse_qty - 5
		);
		expect(await getBinQty(page, context.fg_item, context.fg_warehouse)).toBe(
			context.good_warehouse_qty + 5
		);

		const pendingAfterSubmit = await getReportRows(page, "Pending Rework", context);
		const registerAfterSubmit = await getReportRows(page, "Rework Register", context);
		expect(pendingAfterSubmit).toEqual([]);
		expect(
			registerAfterSubmit.filter((row) => row.rework_entry).map((row) => row.rework_entry)
		).toEqual([reworkEntry]);

		const readOnlyUser = `e2e-user-rework-lifecycle-${Date.now()}@example.com`;
		await ensureUser(page, {
			email: readOnlyUser,
			firstName: "E2E Rework Lifecycle",
			password: TEST_PASSWORD,
			roles: ["PEA Read Only"],
		});
		try {
			await loginAs(page, readOnlyUser, TEST_PASSWORD);
			await expect(
				callFrappeMethod(page, "frappe.client.insert", {
					doc: JSON.stringify({
						doctype: "Stock Entry",
						stock_entry_type: context.rework_stock_entry_type,
						purpose: "Material Transfer",
					}),
				})
			).rejects.toThrow(/PermissionError|Not permitted|No permission/i);
			expect(await getReportRows(page, "Pending Rework", context)).toEqual([]);
			expect(
				(await getReportRows(page, "Rework Register", context)).some(
					(row) => row.rework_entry === reworkEntry
				)
			).toBe(true);
		} finally {
			await loginAs(page, ADMIN_USERNAME, ADMIN_PASSWORD);
		}

		await callFrappeMethod(page, "frappe.client.cancel", {
			doctype: "Stock Entry",
			name: reworkEntry,
		});
		expect(await getBinQty(page, context.fg_item, context.rejection_warehouse)).toBe(
			context.rejection_warehouse_qty
		);
		expect(await getBinQty(page, context.fg_item, context.fg_warehouse)).toBe(
			context.good_warehouse_qty
		);
		const pendingAfterCancel = await getReportRows(page, "Pending Rework", context);
		const registerAfterCancel = await getReportRows(page, "Rework Register", context);
		expect(Number(pendingAfterCancel[0].derived_pending_qty)).toBe(5);
		expect(Number(pendingAfterCancel[0].rejection_warehouse_balance)).toBe(5);
		expect(registerAfterCancel.filter((row) => row.rework_entry)).toEqual([]);
	});

	test("@regression shows missing time and operator validation", async ({ page }) => {
		const context = await seedLifecycle(page, lifecycle.getPrefix());
		await fillReworkEntry(page, context, {
			includeOperator: false,
			includeTimes: false,
		});

		await expectSaveValidation(page, /at least one active Operator/i);
		const validationDialog = page.locator(".modal.show").first();
		await validationDialog.locator(".btn-modal-close").click();
		await validationDialog.waitFor({ state: "hidden" });
		await fillReworkEntry(page, context, {
			includeOperator: true,
			includeTimes: false,
		});
		await expectSaveValidation(page, /Rework duration must be greater than zero/i);
	});

	test("@regression shows the available pool when rework overdraws it", async ({ page }) => {
		const context = await seedLifecycle(page, lifecycle.getPrefix());
		const stockEntryPage = await fillReworkEntry(page, context, { qty: 6 });
		await stockEntryPage.saveDraft();

		await saveForm(page, "Submit").catch(() => {});

		await expectValidationError(page, /requested 6.*Available quantity is 5/i);
	});

	test("@regression rejects wrong rework source and target routes", async ({ page }) => {
		const context = await seedLifecycle(page, lifecycle.getPrefix());
		const stockEntryPage = await fillReworkEntry(page, context);
		await page.evaluate(
			({ wrongSource, wrongTarget }) => {
				cur_frm.doc.items[0].s_warehouse = wrongSource;
				cur_frm.doc.items[0].t_warehouse = wrongTarget;
				cur_frm.refresh_field("items");
			},
			{ wrongSource: context.wip_warehouse, wrongTarget: context.scrap_warehouse }
		);
		await stockEntryPage.saveDraft();
		await expectSubmitValidation(page, /configured Rejection Warehouse/i);

		await page.evaluate(
			({ source, target }) => {
				cur_frm.doc.items[0].s_warehouse = source;
				cur_frm.doc.items[0].t_warehouse = target;
				cur_frm.refresh_field("items");
			},
			{ source: context.rejection_warehouse, target: context.scrap_warehouse }
		);
		await page.evaluate(() => cur_frm.save());
		await expectSubmitValidation(page, /good target warehouse/i);
	});
});
