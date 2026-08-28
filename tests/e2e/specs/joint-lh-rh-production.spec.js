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

async function enableJointProduction(page, form, stockEntryType) {
	const jointCheckbox = page.getByRole("checkbox", {
		name: "Joint LH/RH Production",
		exact: true,
	});
	await expect(jointCheckbox).toBeEnabled();
	await jointCheckbox.check();
	await form.waitForFieldValue("stock_entry_type", stockEntryType);
	await form.waitForFieldValue("custom_pea_stock_entry_purpose", "Repack");
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

async function getFieldTops(page, fieldnames) {
	return page.evaluate(
		(names) =>
			Object.fromEntries(
				names.map((fieldname) => [
					fieldname,
					document
						.querySelector(`[data-fieldname="${fieldname}"]`)
						?.getBoundingClientRect().top,
				])
			),
		fieldnames
	);
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
		await enableJointProduction(page, form, stockEntryType);
		await setFieldValue(page, "company", ctx.company);

		expect(await form.isFieldVisible("custom_pea_rejection_breakup")).toBe(false);
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
		await enableJointProduction(page, form, stockEntryType);
		await setFieldValue(page, "company", ctx.company);
		await setFieldValue(page, "custom_pea_shift", ctx.shift_name);
		await setFieldValue(page, "from_warehouse", ctx.wip_warehouse);
		await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
		await form.fillJointProductionFields(ctx);
		await form.waitForFieldValue("custom_pea_total_rm_consumption", 39.79125);

		await page.locator('[data-fieldname="custom_pea_joint_fetch_items"] button').click();
		await page.waitForFunction(() => (window.cur_frm?.doc?.items || []).length === 5);

		const values = await form.getFieldValues(["items"]);
		const outgoingRows = values.items.filter((row) => row.s_warehouse);
		const sideRows = values.items.filter((row) => row.custom_pea_joint_output_side);
		const scrapRows = values.items.filter(
			(row) => row.is_scrap_item || row.is_legacy_scrap_item || row.type === "Scrap"
		);
		expect(outgoingRows).toHaveLength(1);
		expect(outgoingRows[0].item_code).toBe(ctx.joint_rm_item);
		expect(outgoingRows[0].qty).toBeCloseTo(39.79125, 6);
		expect(sideRows.map((row) => row.custom_pea_joint_output_side).sort()).toEqual([
			"LH",
			"RH",
		]);
		expect(scrapRows).toHaveLength(2);
		expect(scrapRows).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					item_code: ctx.joint_scrap_item,
					qty: 1.32125,
					stock_uom: "Kg",
				}),
				expect.objectContaining({
					item_code: ctx.joint_scrap_nos_item,
					qty: 9,
					stock_uom: "Nos",
				}),
			])
		);
	});

	test("@regression joint rejection breakup stays editable and preserves rows", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const stockEntryType = await createJointStockEntryType(page, lifecycle.getPrefix());
		createdTypes.add(stockEntryType);
		const form = new StockEntryPage(page);

		await form.openNew();
		await enableJointProduction(page, form, stockEntryType);
		await setFieldValue(page, "company", ctx.company);
		await setFieldValue(page, "custom_pea_lh_bom", ctx.joint_lh_bom);
		await setFieldValue(page, "custom_pea_rh_bom", ctx.joint_rh_bom);
		await setFieldValue(page, "custom_pea_lh_rejection_qty", 2);
		await setFieldValue(page, "custom_pea_rh_rejection_qty", 3);
		await page.evaluate(() => cur_frm.scroll_to_field("custom_pea_rejection_breakup"));

		expect(await form.isFieldVisible("custom_pea_rejection_breakup")).toBe(true);
		const dataEntryFlowTops = await getFieldTops(page, [
			"custom_pea_joint_resources_section",
			"custom_pea_joint_fetch_items",
			"custom_pea_rejection_breakup",
			"custom_pea_workstation_operator_section",
		]);
		expect(dataEntryFlowTops.custom_pea_joint_resources_section).toBeLessThan(
			dataEntryFlowTops.custom_pea_joint_fetch_items
		);
		expect(dataEntryFlowTops.custom_pea_joint_fetch_items).toBeLessThan(
			dataEntryFlowTops.custom_pea_rejection_breakup
		);
		expect(dataEntryFlowTops.custom_pea_rejection_breakup).toBeLessThan(
			dataEntryFlowTops.custom_pea_workstation_operator_section
		);
		const jointColumnState = await page.evaluate(() => {
			const grid = cur_frm.fields_dict.custom_pea_rejection_breakup.grid;
			return Object.fromEntries(
				["output_side", "item_code"].map((fieldname) => {
					const df = grid.docfields.find((field) => field.fieldname === fieldname);
					return [fieldname, { hidden: Boolean(df.hidden), reqd: Boolean(df.reqd) }];
				})
			);
		});
		expect(jointColumnState).toEqual({
			output_side: { hidden: false, reqd: true },
			item_code: { hidden: false, reqd: false },
		});

		await form.setRejectionBreakupRows([
			{
				output_side: "LH",
				item_code: ctx.joint_lh_item,
				rejection_reason: "Burr",
				qty: 2,
				is_rework: 0,
			},
			{
				output_side: "RH",
				item_code: ctx.joint_rh_item,
				rejection_reason: "Crack",
				qty: 3,
				is_rework: 1,
			},
		]);
		await setFieldValue(page, "custom_pea_lh_bom", null);
		await page.waitForFunction(() => {
			const rows = window.cur_frm?.doc?.custom_pea_rejection_breakup || [];
			return rows.find((row) => row.output_side === "LH")?.item_code === "";
		});
		await setFieldValue(page, "custom_pea_lh_bom", ctx.joint_lh_bom);
		await page.waitForFunction((expectedItem) => {
			const rows = window.cur_frm?.doc?.custom_pea_rejection_breakup || [];
			return rows.find((row) => row.output_side === "LH")?.item_code === expectedItem;
		}, ctx.joint_lh_item);
		const refreshedBreakup = (await form.getFieldValues(["custom_pea_rejection_breakup"]))
			.custom_pea_rejection_breakup;
		expect(refreshedBreakup).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					output_side: "LH",
					item_code: ctx.joint_lh_item,
					rejection_reason: "Burr",
					qty: 2,
					is_rework: 0,
				}),
				expect.objectContaining({
					output_side: "RH",
					item_code: ctx.joint_rh_item,
					rejection_reason: "Crack",
					qty: 3,
					is_rework: 1,
				}),
			])
		);
		await setFieldValue(page, "custom_pea_shift", ctx.shift_name);
		await setFieldValue(page, "from_warehouse", ctx.wip_warehouse);
		await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
		await setFieldValue(page, "custom_pea_lh_gross_qty", 40);
		await setFieldValue(page, "custom_pea_rh_gross_qty", 41);
		await page.locator('[data-fieldname="custom_pea_joint_fetch_items"] button').click();
		await page.waitForFunction(() => (window.cur_frm?.doc?.items || []).length > 0);
		expect(
			(await form.getFieldValues(["custom_pea_rejection_breakup"]))
				.custom_pea_rejection_breakup
		).toHaveLength(2);
		await setFieldValue(page, "custom_pea_lh_rejection_qty", 0);
		await setFieldValue(page, "custom_pea_rh_rejection_qty", 0);

		expect(await form.isFieldVisible("custom_pea_rejection_breakup")).toBe(true);
		const values = await form.getFieldValues(["custom_pea_rejection_breakup"]);
		expect(values.custom_pea_rejection_breakup).toHaveLength(2);
	});

	test("@smoke joint rejection breakup saves and submits through the production form", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const stockEntryType = await createJointStockEntryType(page, lifecycle.getPrefix());
		createdTypes.add(stockEntryType);
		const form = new StockEntryPage(page);

		await form.openNew();
		await enableJointProduction(page, form, stockEntryType);
		await setFieldValue(page, "company", ctx.company);
		await form.setPostingDate(ctx.shift_date);
		await setFieldValue(page, "custom_pea_shift", ctx.shift_name);
		await setFieldValue(page, "from_warehouse", ctx.wip_warehouse);
		await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
		await form.fillJointProductionFields(ctx, { lhRejectionQty: 2, rhRejectionQty: 3 });
		await form.setRejectionBreakupRows([
			{
				output_side: "LH",
				rejection_reason: "Burr",
				qty: 2,
				is_rework: 0,
			},
			{
				output_side: "RH",
				rejection_reason: "Crack",
				qty: 3,
				is_rework: 1,
			},
		]);
		await form.fetchItems();
		await form.saveAndSubmit();

		const name = await page.evaluate(() => cur_frm.doc.name);
		const submitted = await callFrappeMethod(page, "frappe.client.get", {
			doctype: "Stock Entry",
			name,
		});
		expect(submitted.docstatus).toBe(1);
		expect(Number(submitted.custom_pea_rework_qty)).toBe(3);
		expect(
			submitted.custom_pea_rejection_breakup.map((row) => ({
				side: row.output_side,
				item: row.item_code,
				qty: Number(row.qty),
				rework: Number(row.is_rework),
			}))
		).toEqual([
			{ side: "LH", item: ctx.joint_lh_item, qty: 2, rework: 0 },
			{ side: "RH", item: ctx.joint_rh_item, qty: 3, rework: 1 },
		]);
	});

	test("@regression joint rejection quantity requires a breakup before save", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const stockEntryType = await createJointStockEntryType(page, lifecycle.getPrefix());
		createdTypes.add(stockEntryType);
		const form = new StockEntryPage(page);

		await form.openNew();
		await enableJointProduction(page, form, stockEntryType);
		await setFieldValue(page, "company", ctx.company);
		await form.setPostingDate(ctx.shift_date);
		await setFieldValue(page, "custom_pea_shift", ctx.shift_name);
		await setFieldValue(page, "from_warehouse", ctx.wip_warehouse);
		await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
		await form.fillJointProductionFields(ctx, { lhRejectionQty: 1 });
		await form.fetchItems();
		await form.attemptSaveDraft();

		await expectValidationError(page, /Rejection Breakup is required/i);
	});

	test("@regression normal Manufacture hides joint-only rejection columns", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const form = new StockEntryPage(page);

		await form.openNew();
		await form.setManufactureFields(ctx, { rejectionQty: 1 });
		await page.evaluate(() => cur_frm.scroll_to_field("custom_pea_rejection_breakup"));

		expect(await form.isFieldVisible("custom_pea_rejection_breakup")).toBe(true);
		const normalFlowTops = await getFieldTops(page, [
			"custom_pea_fetch_items",
			"custom_pea_rejection_breakup",
		]);
		expect(normalFlowTops.custom_pea_fetch_items).toBeLessThan(
			normalFlowTops.custom_pea_rejection_breakup
		);
		const columnState = await page.evaluate(() => {
			const grid = cur_frm.fields_dict.custom_pea_rejection_breakup.grid;
			return Object.fromEntries(
				["output_side", "item_code"].map((fieldname) => {
					const df = grid.docfields.find((field) => field.fieldname === fieldname);
					return [fieldname, { hidden: Boolean(df.hidden), reqd: Boolean(df.reqd) }];
				})
			);
		});
		expect(columnState).toEqual({
			output_side: { hidden: true, reqd: false },
			item_code: { hidden: true, reqd: false },
		});
	});

	test("@regression joint Fetch Items shows required-header validation", async ({ page }) => {
		await page.goto(getRoute("/home"));
		await bootstrapE2E(page, lifecycle.getPrefix());
		const stockEntryType = await createJointStockEntryType(page, lifecycle.getPrefix());
		createdTypes.add(stockEntryType);
		const form = new StockEntryPage(page);

		await form.openNew();
		await enableJointProduction(page, form, stockEntryType);
		await setFieldValue(page, "custom_pea_lh_gross_qty", 40);
		await setFieldValue(page, "custom_pea_rh_gross_qty", 41);
		await form.fetchItems();

		await expectValidationError(page, /LH BOM is required/i);
	});

	test("@regression stale joint rows require Fetch Items without clearing logistics", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const stockEntryType = await createJointStockEntryType(page, lifecycle.getPrefix());
		createdTypes.add(stockEntryType);
		const form = new StockEntryPage(page);

		await form.openNew();
		await enableJointProduction(page, form, stockEntryType);
		await setFieldValue(page, "company", ctx.company);
		await form.setPostingDate(ctx.shift_date);
		await setFieldValue(page, "custom_pea_shift", ctx.shift_name);
		await setFieldValue(page, "from_warehouse", ctx.wip_warehouse);
		await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
		await form.fillJointProductionFields(ctx);
		await form.fetchItems();
		await page.evaluate(async (warehouse) => {
			const row = cur_frm.doc.items.find((item) => item.s_warehouse);
			await frappe.model.set_value(row.doctype, row.name, "s_warehouse", warehouse);
		}, ctx.rm_warehouse);
		const before = await form.getFieldValues(["items"]);

		await setFieldValue(page, "custom_pea_lh_gross_qty", 39);
		await form.attemptSaveDraft();

		await expectValidationError(page, /Run Fetch Items again/i);
		const after = await form.getFieldValues(["items"]);
		expect(after.items).toHaveLength(before.items.length);
		expect(after.items.map((row) => row.name)).toEqual(before.items.map((row) => row.name));
		expect(after.items.find((row) => row.s_warehouse)?.s_warehouse).toBe(ctx.rm_warehouse);
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

	test("@regression users without Stock Entry access cannot change total press strokes", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const form = new StockEntryPage(page);
		await form.openNew();
		await form.setManufactureFields(ctx, { fgQty: 100, rejectionQty: 0 });
		await form.fetchItems();
		await form.saveDraft();
		const saved = await page.evaluate(() => ({
			...cur_frm.doc,
			custom_pea_total_strokes: 40,
		}));

		const email = `e2e-user-strokes-${lifecycle.getPrefix()}@example.com`.toLowerCase();
		createdUsers.add(email);
		await ensureUser(page, {
			email,
			firstName: "TotalStrokesNoAccess",
			password: TEST_PASSWORD,
			roles: [],
		});
		await login(page, email, TEST_PASSWORD);

		const response = await page.request.post("/api/method/frappe.client.save", {
			form: { doc: JSON.stringify(saved) },
		});
		expect(response.status()).toBe(403);
	});
});
