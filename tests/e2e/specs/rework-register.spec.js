const { test, expect } = require("@playwright/test");

const { callFrappeMethod } = require("../fixtures/frappe");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");
const { deleteUserIfExists, ensureUser } = require("../fixtures/users");
const { ReportsPage } = require("../pages/reports-page");
const { getRoute } = require("../utils/routing");

const ADMIN_USERNAME =
	process.env.PLAYWRIGHT_ADMIN_USERNAME || process.env.PLAYWRIGHT_USERNAME || "Administrator";
const ADMIN_PASSWORD =
	process.env.PLAYWRIGHT_ADMIN_PASSWORD || process.env.PLAYWRIGHT_PASSWORD || "123";
const TEST_PASSWORD = process.env.PLAYWRIGHT_TEST_USER_PASSWORD || "E2eT3st!Pass#2026";

async function loginAs(page, username, password) {
	const response = await page.request.post("/api/method/login", {
		form: { usr: username, pwd: password },
	});
	expect(response.ok()).toBeTruthy();
	await page.goto(getRoute("/home"));
}

async function seedRegisterRow(page, prefix) {
	return await callFrappeMethod(
		page,
		"production_entry_app.production_entry_app.e2e_api.create_e2e_rework_register_row",
		{ prefix, qty: 4, cost: 240 }
	);
}

test.describe("Rework Register report", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@regression shows stored rework facts and honors all filters", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const seeded = await seedRegisterRow(page, lifecycle.getPrefix());
		const reportsPage = new ReportsPage(page);

		await reportsPage.open("Rework Register");
		await reportsPage.runWithDateRange(seeded.posting_date, seeded.posting_date);
		await reportsPage.setFilterByFieldname("rework_type", seeded.rework_type);
		await reportsPage.setFilterByFieldname("item_code", seeded.item_code);
		await reportsPage.setFilterByFieldname("workstation", seeded.workstation);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(1);

		const rows = await reportsPage.getRows();
		const row = rows.find((candidate) => candidate.rework_entry === seeded.name);
		expect(row).toBeTruthy();
		expect(row.rework_type).toBe(seeded.rework_type);
		expect(row.workstation).toBe(seeded.workstation);
		expect(String(row.items)).toContain(`${seeded.item_code} (4)`);
		expect(Number(row.total_qty)).toBe(4);
		expect(Number(row.duration_hours)).toBe(2);
		expect(row.operator_names).toBe(seeded.operator);
		expect(Number(row.operator_count)).toBe(1);
		expect(Number(row.computed_cost)).toBe(240);
	});

	test("@regression PEA Read Only can read the register without Stock Entry access", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const seeded = await seedRegisterRow(page, lifecycle.getPrefix());
		const email = `e2e-user-rework-register-${Date.now()}@example.com`;
		await ensureUser(page, {
			email,
			firstName: "E2E Rework Register",
			password: TEST_PASSWORD,
			roles: ["PEA Read Only"],
		});

		try {
			await loginAs(page, email, TEST_PASSWORD);
			const reportsPage = new ReportsPage(page);
			await reportsPage.open("Rework Register");
			await reportsPage.runWithDateRange(seeded.posting_date, seeded.posting_date);
			await reportsPage.clickRefresh();
			await reportsPage.waitForRows(1);

			const rows = await reportsPage.getRows();
			expect(rows.some((row) => row.rework_entry === seeded.name)).toBeTruthy();
		} finally {
			await loginAs(page, ADMIN_USERNAME, ADMIN_PASSWORD);
			await deleteUserIfExists(page, email);
		}
	});
});
