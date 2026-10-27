const { test, expect } = require("@playwright/test");

const { callFrappeMethod } = require("../fixtures/frappe");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");
const { deleteUserIfExists, ensureUser, loginAs } = require("../fixtures/users");
const { ReportsPage } = require("../pages/reports-page");

const ADMIN_USERNAME =
	process.env.PLAYWRIGHT_ADMIN_USERNAME || process.env.PLAYWRIGHT_USERNAME || "Administrator";
const ADMIN_PASSWORD =
	process.env.PLAYWRIGHT_ADMIN_PASSWORD || process.env.PLAYWRIGHT_PASSWORD || "123";
const TEST_PASSWORD = process.env.PLAYWRIGHT_TEST_USER_PASSWORD || "E2eT3st!Pass#2026";

async function seedRegisterRow(page, prefix) {
	return await callFrappeMethod(
		page,
		"production_entry_app.production_entry_app.e2e_api.create_e2e_rework_register_row",
		{ prefix, qty: 4, cost: 240 }
	);
}

test.describe("Daily Rework Report", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@regression groups entries by date with day header, subtotal, and PPM chart", async ({
		page,
	}) => {
		const seeded = await seedRegisterRow(page, lifecycle.getPrefix());
		const reportsPage = new ReportsPage(page);

		await reportsPage.open("Daily Rework Report");
		await reportsPage.runWithDateRange(seeded.posting_date, seeded.posting_date);
		await reportsPage.setFilterByFieldname("operator", seeded.operator);
		await reportsPage.clickRefresh();
		await reportsPage.waitForRows(3);

		const rows = await reportsPage.getRows();
		const header = rows.find((row) => String(row.date || "") === seeded.posting_date);
		expect(header).toBeTruthy();
		expect(Number(header.operator_count)).toBe(1);
		expect(Number(header.duration_hours)).toBe(2);

		const entryRow = rows.find((row) => row.rework_entry === seeded.name);
		expect(entryRow).toBeTruthy();
		expect(Number(entryRow.total_qty)).toBe(4);
		expect(Number(entryRow.duration_hours)).toBe(2);
		expect(entryRow.operator_names).toBe(seeded.operator);

		const subtotal = rows.find(
			(row) => row.daily_rew_ppm !== undefined && row.daily_rew_ppm !== ""
		);
		expect(subtotal).toBeTruthy();
		expect(Number(subtotal.total_qty)).toBe(4);
		expect(Number(subtotal.operator_count)).toBe(1);
		expect(Number(subtotal.duration_hours)).toBe(2);

		expect(await reportsPage.hasChart()).toBeTruthy();
	});

	test("@regression PEA Read Only can run the report without Stock Entry access", async ({
		page,
	}) => {
		const seeded = await seedRegisterRow(page, lifecycle.getPrefix());
		const email = `e2e-user-daily-rework-${Date.now()}@example.com`;
		await ensureUser(page, {
			email,
			firstName: "E2E Daily Rework",
			password: TEST_PASSWORD,
			roles: ["PEA Read Only"],
		});

		try {
			await loginAs(page, email, TEST_PASSWORD);
			const reportsPage = new ReportsPage(page);
			await reportsPage.open("Daily Rework Report");
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
