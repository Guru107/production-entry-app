const { test, expect } = require("@playwright/test");
const { callFrappeMethod, getDoc, saveForm, setFieldValue } = require("../fixtures/frappe");
const { expectValidationError } = require("../fixtures/assertions");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");
const { bootstrapE2E } = require("../fixtures/test-data");
const {
	ensureJointStockEntryType,
	deleteJointStockEntryTypeIfExists,
} = require("../fixtures/joint-production");
const { ensureUser, deleteUserIfExists } = require("../fixtures/users");
const { StockEntryPage } = require("../pages/stock-entry-page");
const { getRoute } = require("../utils/routing");

async function openSettings(page) {
	await page.goto(getRoute("/production-entry-settings"));
	await page.waitForFunction(() => window.cur_frm?.doctype === "Production Entry Settings");
}

test.describe("Branch warehouse defaults", () => {
	let jointType;
	let user;
	let workOrder;
	test.afterEach(async ({ page }) => {
		if (workOrder) {
			await callFrappeMethod(page, "frappe.client.cancel", {
				doctype: "Work Order",
				name: workOrder,
			});
			await callFrappeMethod(page, "frappe.client.delete", {
				doctype: "Work Order",
				name: workOrder,
			});
		}
		workOrder = null;
	});
	const lifecycle = registerE2ELifecycle(test);
	test.afterEach(async ({ page }) => {
		if (jointType) await deleteJointStockEntryTypeIfExists(page, jointType);
		if (user) await deleteUserIfExists(page, user);
		jointType = null;
		user = null;
	});

	test("@regression branch settings supply WIP, rejection and scrap for both Fetch Items flows", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		jointType = await ensureJointStockEntryType(page, lifecycle.getPrefix());
		await openSettings(page);
		await expect(page.locator('[data-fieldname="branch_warehouse_defaults"]')).toBeVisible();
		await page.evaluate(async (context) => {
			const row = cur_frm.doc.branch_warehouse_defaults.find(
				(row) => row.company === context.company && row.branch === context.branch
			);
			await frappe.model.set_value(
				row.doctype,
				row.name,
				"work_in_progress_warehouse",
				context.rm_warehouse
			);
			cur_frm.refresh_field("branch_warehouse_defaults");
		}, ctx);
		await saveForm(page);
		const shift = await getDoc(page, "Shift", ctx.shift_name);
		for (const field of [
			"raw_material_warehouse",
			"work_in_progress_warehouse",
			"rejection_warehouse",
			"scrap_warehouse",
		])
			shift[field] = null;
		await callFrappeMethod(page, "frappe.client.save", { doc: JSON.stringify(shift) });

		for (const joint of [false, true]) {
			const form = new StockEntryPage(page);
			await form.openNew();
			await setFieldValue(page, "stock_entry_type", joint ? jointType : "Manufacture");
			await setFieldValue(page, "company", ctx.company);
			await setFieldValue(page, "custom_pea_shift", ctx.shift_name);
			await form.waitForFieldValue("from_warehouse", ctx.rm_warehouse);
			await form.waitForFieldValue("to_warehouse", ctx.rm_warehouse);
			await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
			if (joint) {
				await form.fillJointProductionFields(ctx, { lhRejectionQty: 1 });
			} else {
				await setFieldValue(page, "from_bom", 1);
				await setFieldValue(page, "bom_no", ctx.joint_lh_bom);
				await setFieldValue(page, "fg_completed_qty", 40);
				await setFieldValue(page, "custom_pea_rejection_qty", 1);
			}
			await form.fetchItems();
			const rows = await page.evaluate(() => cur_frm.doc.items);
			const isScrap = (row) =>
				row.is_scrap_item ||
				row.is_legacy_scrap_item ||
				row.secondary_item_type === "Scrap" ||
				row.type === "Scrap";
			expect(rows.filter((row) => row.s_warehouse).map((row) => row.s_warehouse)).toEqual([
				ctx.rm_warehouse,
			]);
			expect(rows.filter(isScrap).length).toBeGreaterThan(0);
			for (const row of rows.filter((row) => row.t_warehouse)) {
				expect(row.t_warehouse).toBe(
					isScrap(row)
						? ctx.scrap_warehouse
						: row.custom_pea_is_rejection_item
						? ctx.rejection_warehouse
						: ctx.fg_warehouse
				);
			}
		}
	});

	test("@regression duplicate Company and Branch is rejected visibly", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		await openSettings(page);
		await page.evaluate((context) => {
			cur_frm.add_child("branch_warehouse_defaults", {
				company: context.company,
				branch: context.branch,
			});
			cur_frm.refresh_field("branch_warehouse_defaults");
			cur_frm.dirty();
			cur_frm.save().catch(() => {});
		}, ctx);
		await expectValidationError(page, /Duplicate warehouse defaults/);
	});

	test("@regression Work Order Fetch Items retains native scrap warehouse with a Shift", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const draft = await callFrappeMethod(page, "frappe.client.insert", {
			doc: JSON.stringify({
				doctype: "Work Order",
				company: ctx.company,
				production_item: ctx.joint_lh_item,
				bom_no: ctx.joint_lh_bom,
				qty: 40,
				skip_transfer: 1,
				source_warehouse: ctx.wip_warehouse,
				wip_warehouse: ctx.wip_warehouse,
				fg_warehouse: ctx.fg_warehouse,
				scrap_warehouse: ctx.fg_warehouse,
			}),
		});
		workOrder = draft.name;
		await callFrappeMethod(page, "frappe.client.submit", { doc: JSON.stringify(draft) });
		const form = new StockEntryPage(page);
		await form.openNew();
		await setFieldValue(page, "stock_entry_type", "Manufacture");
		await setFieldValue(page, "company", ctx.company);
		await setFieldValue(page, "work_order", workOrder);
		await page.evaluate(() => frappe.after_ajax());
		await setFieldValue(page, "from_warehouse", ctx.wip_warehouse);
		await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
		await setFieldValue(page, "custom_pea_shift", ctx.shift_name);
		await page.evaluate(() => frappe.after_ajax());
		expect(
			await form.getFieldValues(["custom_pea_shift", "custom_pea_planned_end_date"])
		).toMatchObject({
			custom_pea_shift: ctx.shift_name,
			custom_pea_planned_end_date: expect.stringContaining(ctx.shift_date),
		});
		await form.waitForFieldValue("to_warehouse", ctx.fg_warehouse);
		await setFieldValue(page, "fg_completed_qty", 40);
		expect((await form.getFieldValues(["work_order"])).work_order).toBe(workOrder);
		await form.fetchItems();
		const rows = await page.evaluate(() => cur_frm.doc.items);
		const scrap = rows.filter(
			(row) =>
				row.is_scrap_item ||
				row.is_legacy_scrap_item ||
				row.secondary_item_type === "Scrap" ||
				row.type === "Scrap"
		);
		expect(scrap.length).toBeGreaterThan(0);
		expect(scrap.map((row) => row.t_warehouse)).toEqual(scrap.map(() => ctx.fg_warehouse));
		await setFieldValue(page, "custom_pea_shift", "");
		await page.waitForFunction(() => !cur_frm.doc.custom_pea_planned_end_date);
		await page.evaluate(() => frappe.after_ajax());
		expect(await form.getFieldValues(["from_warehouse", "to_warehouse"])).toEqual({
			from_warehouse: ctx.wip_warehouse,
			to_warehouse: ctx.fg_warehouse,
		});
	});

	test("@regression Shift selection without WIP keeps context and allows manual warehouses", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		jointType = await ensureJointStockEntryType(page, lifecycle.getPrefix());
		const settings = await getDoc(
			page,
			"Production Entry Settings",
			"Production Entry Settings"
		);
		settings.branch_warehouse_defaults.find(
			(row) => row.company === ctx.company && row.branch === ctx.branch
		).work_in_progress_warehouse = null;
		await callFrappeMethod(page, "frappe.client.save", { doc: JSON.stringify(settings) });
		const shift = await getDoc(page, "Shift", ctx.shift_name);
		shift.work_in_progress_warehouse = null;
		await callFrappeMethod(page, "frappe.client.save", { doc: JSON.stringify(shift) });
		for (const joint of [false, true]) {
			const form = new StockEntryPage(page);
			await form.openNew();
			await setFieldValue(page, "stock_entry_type", joint ? jointType : "Manufacture");
			await setFieldValue(page, "company", ctx.company);
			await setFieldValue(page, "custom_pea_shift", ctx.shift_name);
			await form.waitForFieldValue("branch", ctx.branch);
			const values = await form.getFieldValues([
				"custom_pea_shift",
				"company",
				"custom_pea_planned_start_date",
			]);
			expect(values.custom_pea_shift).toBe(ctx.shift_name);
			expect(values.company).toBe(ctx.company);
			expect(values.custom_pea_planned_start_date).toContain(ctx.shift_date);
			await expect(page.locator(".modal:visible")).toHaveCount(0);
			await setFieldValue(page, "from_warehouse", ctx.wip_warehouse);
			await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
			if (joint) {
				await form.fillJointProductionFields(ctx);
			} else {
				await setFieldValue(page, "from_bom", 1);
				await setFieldValue(page, "bom_no", ctx.bom);
				await setFieldValue(page, "fg_completed_qty", 40);
			}
			await form.fetchItems();
			const rows = await page.evaluate(() => cur_frm.doc.items);
			expect(rows.length).toBeGreaterThan(1);
			expect(
				rows
					.filter((row) => row.s_warehouse)
					.every((row) => row.s_warehouse === ctx.wip_warehouse)
			).toBeTruthy();
		}
	});

	test("@regression PEA User can read but cannot edit branch settings", async ({ page }) => {
		await page.goto(getRoute("/home"));
		await bootstrapE2E(page, lifecycle.getPrefix());
		user = `e2e-user-${lifecycle.getPrefix().toLowerCase()}@example.com`;
		const password = "E2eT3st!Pass#2026";
		await ensureUser(page, { email: user, password, roles: ["PEA User"] });
		const login = await page.request.post("/api/method/login", {
			form: { usr: user, pwd: password },
		});
		expect(login.ok()).toBeTruthy();
		await openSettings(page);
		const settings = await getDoc(
			page,
			"Production Entry Settings",
			"Production Entry Settings"
		);
		await expect(
			callFrappeMethod(page, "frappe.client.save", { doc: JSON.stringify(settings) })
		).rejects.toThrow(/PermissionError|Not permitted|No permission/);
	});
});
