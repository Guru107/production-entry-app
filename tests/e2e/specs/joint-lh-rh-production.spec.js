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
	try {
		await callFrappeMethod(page, "frappe.client.delete", { doctype, name });
	} catch (error) {
		const message = String(error?.message || error);
		if (!/not found|DoesNotExistError|Resource is not available/i.test(message)) throw error;
	}
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
		expect(await form.isFieldVisible("custom_pea_shift")).toBe(true);
		expect(await form.isSectionVisible("bom_info_section")).toBe(false);
		expect(await form.isSectionVisible("custom_pea_operation_details_section")).toBe(true);
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

		await expect(
			callFrappeMethod(
				page,
				"production_entry_app.production_entry_app.api.get_joint_production_items",
				{ doc: JSON.stringify({ doctype: "Stock Entry", purpose: "Repack" }) }
			)
		).rejects.toThrow(/permission|not permitted|403/i);
	});
});
