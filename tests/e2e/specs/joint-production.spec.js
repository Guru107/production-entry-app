const { test, expect } = require("@playwright/test");
const { expectValidationError } = require("../fixtures/assertions");
const { callFrappeMethod, setFieldValue } = require("../fixtures/frappe");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");
const { getJointProductionStockEntryType } = require("../fixtures/joint-production");
const { bootstrapE2E } = require("../fixtures/test-data");
const { deleteUserIfExists, ensureUser } = require("../fixtures/users");
const { StockEntryPage } = require("../pages/stock-entry-page");
const { getRoute, getRouteRegex } = require("../utils/routing");

const ADMIN_USERNAME = process.env.PLAYWRIGHT_USERNAME || "Administrator";
const ADMIN_PASSWORD = process.env.PLAYWRIGHT_PASSWORD || "123";
const TEST_PASSWORD = process.env.PLAYWRIGHT_TEST_USER_PASSWORD || "E2eT3st!Pass#2026";

async function login(page, username, password) {
	const response = await page.request.post("/api/method/login", {
		form: { usr: username, pwd: password },
	});
	expect(response.ok()).toBeTruthy();
	await page.goto(getRoute("/home"));
	await expect(page).toHaveURL(getRouteRegex("/home"));
}

test.describe("Joint Production line table", () => {
	const lifecycle = registerE2ELifecycle(test);
	const createdUsers = new Set();

	test.afterEach(async ({ page }) => {
		await login(page, ADMIN_USERNAME, ADMIN_PASSWORD);
		for (const email of createdUsers) await deleteUserIfExists(page, email);
		createdUsers.clear();
	});

	test("@smoke shows Joint Production Lines instead of LH/RH header slots", async ({ page }) => {
		const ctx = await bootstrapE2E(page, lifecycle);
		const stockEntryType = await getJointProductionStockEntryType(page);
		const form = new StockEntryPage(page);
		await form.openNew();
		await setFieldValue(page, "stock_entry_type", stockEntryType);
		await form.waitForJointMode(stockEntryType);
		expect(await form.isFieldVisible("custom_pea_joint_production_lines")).toBe(true);
		expect(await form.isFieldVisible("custom_pea_lh_bom")).toBe(false);
		expect(await form.isFieldVisible("custom_pea_rh_bom")).toBe(false);
	});

	test("fetch items blocks a single Joint Production Line", async ({ page }) => {
		const ctx = await bootstrapE2E(page, lifecycle);
		const stockEntryType = await getJointProductionStockEntryType(page);
		const form = new StockEntryPage(page);
		await form.openNew();
		await setFieldValue(page, "stock_entry_type", stockEntryType);
		await form.waitForJointMode(stockEntryType);
		await setFieldValue(page, "company", ctx.company);
		await setFieldValue(page, "custom_pea_operation", ctx.joint_operation);
		await page.evaluate(
			(row) => {
				const frm = window.cur_frm;
				frm.clear_table("custom_pea_joint_production_lines");
				frm.add_child("custom_pea_joint_production_lines", row);
				frm.refresh_field("custom_pea_joint_production_lines");
			},
			{
				bom_no: ctx.joint_lh_bom,
				gross_qty: 10,
				rejection_qty: 0,
			}
		);
		await page.locator('[data-fieldname="custom_pea_joint_fetch_items"] button').click();
		await expectValidationError(page, /Manufacture Production Entry/);
	});

	test("@smoke three-line multipart die fetch and submit", async ({ page }) => {
		const ctx = await bootstrapE2E(page, lifecycle);
		const stockEntryType = await getJointProductionStockEntryType(page);
		const form = new StockEntryPage(page);
		await form.openNew();
		await setFieldValue(page, "stock_entry_type", stockEntryType);
		await form.waitForJointMode(stockEntryType);
		await setFieldValue(page, "company", ctx.company);
		await setFieldValue(page, "custom_pea_shift", ctx.shift_name);
		await setFieldValue(page, "from_warehouse", ctx.wip_warehouse);
		await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
		await form.fillJointProductionLineFields(ctx, {
			lines: [
				{ bom_no: ctx.joint_lh_bom, gross_qty: 30, rejection_qty: 1 },
				{ bom_no: ctx.joint_rh_bom, gross_qty: 40, rejection_qty: 0 },
				{ bom_no: ctx.joint_multipart_bom, gross_qty: 25, rejection_qty: 2 },
			],
			totalStrokes: 51,
		});
		const fetchResult = await form.fetchItems();
		expect(fetchResult.rowCount).toBeGreaterThan(0);
		const outputSides = await page.evaluate(() => {
			const sides = new Set();
			for (const row of cur_frm.doc.items || []) {
				if (row.custom_pea_joint_output_side) {
					sides.add(row.custom_pea_joint_output_side);
				}
			}
			return [...sides].sort();
		});
		expect(outputSides).toEqual(["BOM 1", "BOM 2", "BOM 3"]);
		await form.saveAndSubmit();
		const name = await page.evaluate(() => cur_frm.doc.name);
		lifecycle.track("Stock Entry", name);
	});

	test("three-line Joint Production rejects stale rows after a line edit", async ({ page }) => {
		const ctx = await bootstrapE2E(page, lifecycle);
		const stockEntryType = await getJointProductionStockEntryType(page);
		const form = new StockEntryPage(page);
		await form.openNew();
		await setFieldValue(page, "stock_entry_type", stockEntryType);
		await form.waitForJointMode(stockEntryType);
		await setFieldValue(page, "company", ctx.company);
		await setFieldValue(page, "custom_pea_shift", ctx.shift_name);
		await setFieldValue(page, "from_warehouse", ctx.wip_warehouse);
		await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
		await form.fillJointProductionLineFields(ctx, {
			lines: [
				{ bom_no: ctx.joint_lh_bom, gross_qty: 30, rejection_qty: 0 },
				{ bom_no: ctx.joint_rh_bom, gross_qty: 40, rejection_qty: 0 },
				{ bom_no: ctx.joint_multipart_bom, gross_qty: 25, rejection_qty: 0 },
			],
		});
		await form.fetchItems();
		await page.evaluate(() => {
			cur_frm.doc.custom_pea_joint_production_lines[2].gross_qty = 99;
		});
		await page.locator(".primary-action").click();
		await expectValidationError(page, /Run Fetch Items again/);
	});

	test("@smoke two-line Joint Production fetch and submit", async ({ page }) => {
		const ctx = await bootstrapE2E(page, lifecycle);
		const stockEntryType = await getJointProductionStockEntryType(page);
		const form = new StockEntryPage(page);
		await form.openNew();
		await setFieldValue(page, "stock_entry_type", stockEntryType);
		await form.waitForJointMode(stockEntryType);
		await setFieldValue(page, "company", ctx.company);
		await setFieldValue(page, "custom_pea_shift", ctx.shift_name);
		await setFieldValue(page, "from_warehouse", ctx.wip_warehouse);
		await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
		await form.fillJointProductionLineFields(ctx, { lhRejectionQty: 1 });
		const fetchResult = await form.fetchItems();
		expect(fetchResult.rowCount).toBeGreaterThan(0);
		await form.saveAndSubmit();
		const name = await page.evaluate(() => cur_frm.doc.name);
		lifecycle.track("Stock Entry", name);
	});

	test("@regression users without Stock Entry access cannot call the joint-items API", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const email = `e2e-user-joint-lines-${lifecycle.getPrefix()}@example.com`.toLowerCase();
		createdUsers.add(email);
		await ensureUser(page, {
			email,
			firstName: "JointLinesNoAccess",
			password: TEST_PASSWORD,
			roles: [],
		});
		await login(page, email, TEST_PASSWORD);

		await expect(
			callFrappeMethod(
				page,
				"production_entry_app.production_entry_app.api.get_joint_production_items",
				{
					doc: JSON.stringify({
						doctype: "Stock Entry",
						purpose: "Repack",
						custom_pea_joint_production_lines: [
							{ bom_no: "BOM-1", gross_qty: 1, rejection_qty: 0 },
							{ bom_no: "BOM-2", gross_qty: 1, rejection_qty: 0 },
						],
					}),
				}
			)
		).rejects.toThrow(
			/403|PermissionError|Not permitted|Insufficient Permission|do not have permission/i
		);
	});
});
