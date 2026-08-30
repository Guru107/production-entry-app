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
	const lifecycle = registerE2ELifecycle(test);
	let jointType;
	let user;
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
