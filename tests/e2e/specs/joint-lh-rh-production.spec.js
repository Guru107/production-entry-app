const { test, expect } = require("@playwright/test");
const { expectValidationError } = require("../fixtures/assertions");
const { callFrappeMethod, setFieldValue } = require("../fixtures/frappe");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");
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

async function createJointStockEntryType(page, prefix) {
	const name = `${prefix} Joint LH RH`;
	await deleteDocIfExists(page, "Stock Entry Type", name);
	await callFrappeMethod(page, "frappe.client.insert", {
		doc: JSON.stringify({
			doctype: "Stock Entry Type",
			name,
			purpose: "Repack",
			custom_pea_joint_lh_rh_production: 1,
		}),
	});
	return name;
}

async function deleteDocIfExists(page, doctype, name) {
	if (!name) return;
	const rows = await callFrappeMethod(page, "frappe.client.get_list", {
		doctype,
		fields: JSON.stringify(["name"]),
		filters: JSON.stringify({ name }),
		limit_page_length: 1,
	});
	if (rows?.length) await callFrappeMethod(page, "frappe.client.delete", { doctype, name });
}

test.describe("Joint LH/RH production form", () => {
	const lifecycle = registerE2ELifecycle(test);
	const createdTypes = new Set();
	const createdUsers = new Set();

	test.afterEach(async ({ page }) => {
		await login(page, ADMIN_USERNAME, ADMIN_PASSWORD);
		for (const name of createdTypes) await deleteDocIfExists(page, "Stock Entry Type", name);
		for (const email of createdUsers) await deleteUserIfExists(page, email);
		createdTypes.clear();
		createdUsers.clear();
	});

	test("@regression Stock Entry Type quick entry exposes the joint-production flag", async ({
		page,
	}) => {
		const stockEntryType = `${lifecycle.getPrefix()} Quick Joint LH RH`;
		createdTypes.add(stockEntryType);
		const form = new StockEntryPage(page);
		await form.openNew();
		await page.evaluate(() => frappe.ui.form.make_quick_entry("Stock Entry Type"));

		const dialog = page.getByRole("dialog");
		const jointFlag = dialog.getByRole("checkbox", { name: "Joint LH/RH Production" });
		await expect(jointFlag).toBeVisible();
		await expect(jointFlag).toBeEnabled();
		await dialog.locator('[data-fieldname="__newname"] input').fill(stockEntryType);
		await dialog.locator('[data-fieldname="purpose"] select').selectOption("Repack");
		await jointFlag.check();
		await dialog.getByRole("button", { name: "Save", exact: true }).click();
		await expect(dialog).toBeHidden();

		const savedType = await callFrappeMethod(page, "frappe.client.get_value", {
			doctype: "Stock Entry Type",
			filters: stockEntryType,
			fieldname: JSON.stringify(["purpose", "custom_pea_joint_lh_rh_production"]),
		});
		expect(savedType).toMatchObject({
			purpose: "Repack",
			custom_pea_joint_lh_rh_production: 1,
		});
	});

	test("@smoke joint Repack uses the common production form", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const stockEntryType = await createJointStockEntryType(page, lifecycle.getPrefix());
		createdTypes.add(stockEntryType);
		const form = new StockEntryPage(page);

		await form.openNew();
		await setFieldValue(page, "stock_entry_type", stockEntryType);
		await form.waitForFieldValue("custom_pea_is_joint_lh_rh", 1);
		await setFieldValue(page, "company", ctx.company);

		expect(await form.isFieldVisible("custom_pea_lh_bom")).toBe(true);
		expect(await form.isFieldVisible("custom_pea_rh_bom")).toBe(true);
		expect(await form.isFieldVisible("custom_pea_total_strokes")).toBe(true);
		expect(await form.isFieldVisible("custom_pea_total_rm_consumption")).toBe(true);
		expect(await form.isFieldVisible("custom_pea_joint_fetch_items")).toBe(true);
		expect(await form.isFieldVisible("custom_pea_shift")).toBe(true);
		expect(await form.isSectionVisible("bom_info_section")).toBe(false);
		expect(await form.isSectionVisible("custom_pea_operation_details_section")).toBe(true);
		expect(await form.isSectionVisible("custom_pea_joint_production_section")).toBe(true);
		expect(await form.isSectionVisible("custom_pea_joint_resources_section")).toBe(true);
		const sectionTops = await page.evaluate(() => {
			const top = (fieldname) =>
				document.querySelector(`[data-fieldname="${fieldname}"]`)?.getBoundingClientRect()
					.top;
			return {
				dates: top("custom_pea_operation_details_section"),
				actualStartDate: top("custom_pea_actual_start_date_input"),
				actualStartTime: top("custom_pea_actual_start_time_input"),
				actualEndDate: top("custom_pea_actual_end_date_input"),
				actualEndTime: top("custom_pea_actual_end_time_input"),
				jointProduction: top("custom_pea_joint_production_section"),
				jointResources: top("custom_pea_joint_resources_section"),
				workstation: top("custom_pea_workstation_operator_section"),
			};
		});
		expect(sectionTops.dates).toBeLessThan(sectionTops.jointProduction);
		for (const fieldname of [
			"actualStartDate",
			"actualStartTime",
			"actualEndDate",
			"actualEndTime",
		]) {
			expect(sectionTops[fieldname]).toBeGreaterThan(sectionTops.dates);
			expect(sectionTops[fieldname]).toBeLessThan(sectionTops.jointProduction);
		}
		expect(sectionTops.jointProduction).toBeLessThan(sectionTops.jointResources);
		expect(sectionTops.jointResources).toBeLessThan(sectionTops.workstation);
	});

	test("@smoke joint Fetch Items populates rows from both BOMs", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const stockEntryType = await createJointStockEntryType(page, lifecycle.getPrefix());
		createdTypes.add(stockEntryType);
		const form = new StockEntryPage(page);

		await form.openNew();
		await setFieldValue(page, "stock_entry_type", stockEntryType);
		await form.waitForFieldValue("custom_pea_is_joint_lh_rh", 1);
		await setFieldValue(page, "company", ctx.company);
		await setFieldValue(page, "custom_pea_shift", ctx.shift_name);
		await setFieldValue(page, "from_warehouse", ctx.wip_warehouse);
		await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
		await setFieldValue(page, "custom_pea_lh_bom", ctx.joint_lh_bom);
		await setFieldValue(page, "custom_pea_lh_gross_qty", 40);
		await setFieldValue(page, "custom_pea_lh_rejection_qty", 0);
		await setFieldValue(page, "custom_pea_rh_bom", ctx.joint_rh_bom);
		await setFieldValue(page, "custom_pea_rh_gross_qty", 41);
		await setFieldValue(page, "custom_pea_rh_rejection_qty", 0);
		await setFieldValue(page, "custom_pea_total_strokes", 41);
		await setFieldValue(page, "custom_pea_die_tool_item", ctx.joint_lh_item);
		await form.waitForFieldValue("custom_pea_total_rm_consumption", 49.125);

		await page.locator('[data-fieldname="custom_pea_joint_fetch_items"] button').click();
		await page.waitForFunction(() => (window.cur_frm?.doc?.items || []).length === 4);

		const values = await form.getFieldValues(["items", "custom_pea_joint_scrap_qty"]);
		const outgoingRows = values.items.filter((row) => row.s_warehouse);
		const sideRows = values.items.filter((row) => row.custom_pea_joint_output_side);
		const scrapRow = values.items.find(
			(row) => row.is_scrap_item || row.is_legacy_scrap_item || row.type === "Scrap"
		);
		expect(outgoingRows).toHaveLength(1);
		expect(outgoingRows[0]).toMatchObject({ item_code: ctx.joint_rm_item, qty: 49.125 });
		expect(sideRows.map((row) => row.custom_pea_joint_output_side).sort()).toEqual([
			"LH",
			"RH",
		]);
		expect(scrapRow?.item_code).toBe(ctx.joint_scrap_item);
		expect(values.custom_pea_joint_scrap_qty).toBeGreaterThan(0);
	});

	test("@regression joint Fetch Items shows required-header validation", async ({ page }) => {
		await page.goto(getRoute("/home"));
		await bootstrapE2E(page, lifecycle.getPrefix());
		const stockEntryType = await createJointStockEntryType(page, lifecycle.getPrefix());
		createdTypes.add(stockEntryType);
		const form = new StockEntryPage(page);

		await form.openNew();
		await setFieldValue(page, "stock_entry_type", stockEntryType);
		await form.waitForFieldValue("custom_pea_is_joint_lh_rh", 1);
		await setFieldValue(page, "custom_pea_lh_gross_qty", 40);
		await setFieldValue(page, "custom_pea_rh_gross_qty", 41);
		await form.fetchItems();

		await expectValidationError(page, /LH BOM is required/i);
	});

	test("@regression users without Stock Entry access cannot call the joint-items API", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const email = `e2e-user-joint-${lifecycle.getPrefix()}@example.com`.toLowerCase();
		createdUsers.add(email);
		await ensureUser(page, {
			email,
			firstName: "JointProductionNoAccess",
			password: TEST_PASSWORD,
			roles: [],
		});
		await login(page, email, TEST_PASSWORD);

		const response = await page.request.post(
			"/api/method/production_entry_app.production_entry_app.api.get_joint_production_items",
			{
				form: {
					doc: JSON.stringify({ doctype: "Stock Entry", purpose: "Repack" }),
				},
			}
		);
		expect(response.status()).toBe(403);
	});
});
