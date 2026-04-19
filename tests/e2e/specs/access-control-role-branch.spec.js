const { test, expect } = require("@playwright/test");
const { bootstrapE2E } = require("../fixtures/test-data");
const { ensureRole, ensureUser, deleteUserIfExists } = require("../fixtures/users");
const { callFrappeMethod, setFieldValue } = require("../fixtures/frappe");
const { StockEntryPage } = require("../pages/stock-entry-page");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");
const { getRoute, getRouteRegex } = require("../utils/routing");

const ADMIN_USERNAME = process.env.PLAYWRIGHT_USERNAME || "Administrator";
const ADMIN_PASSWORD = process.env.PLAYWRIGHT_PASSWORD || "123";
const TEST_PASSWORD = process.env.PLAYWRIGHT_TEST_USER_PASSWORD || "E2eT3st!Pass#2026";
const STOCK_ENTRY_ROLE = "Manufacturing User";
const REQUIRED_ROLE = "PEA User";
const ACCESS_BLOCKED_TEXT_RE =
	/not permitted|permission denied|page not found|does not exist|access denied/i;

function uniqueSuffix() {
	return `${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

function userEmail(label, suffix) {
	return `e2e-user-${label}-${suffix}@example.com`;
}

async function loginAs(page, username, password) {
	const response = await page.request.post("/api/method/login", {
		form: {
			usr: username,
			pwd: password,
		},
	});
	expect(response.ok()).toBeTruthy();
	await page.goto(getRoute("/home"));
	await expect(page).toHaveURL(getRouteRegex("/home"));
}

async function loginAsAdmin(page) {
	await loginAs(page, ADMIN_USERNAME, ADMIN_PASSWORD);
}

async function ensureAccessRule(page, { enabled, requiredRole = REQUIRED_ROLE }) {
	await ensureRole(page, requiredRole);
	await callFrappeMethod(
		page,
		"production_entry_app.production_entry_app.api.set_e2e_access_control",
		{
			enabled: enabled ? 1 : 0,
			required_role: requiredRole,
		}
	);
}

async function getWorkspaceNameForModule(page, moduleName) {
	const rows = await callFrappeMethod(page, "frappe.client.get_list", {
		doctype: "Workspace",
		fields: JSON.stringify(["name"]),
		filters: JSON.stringify([["module", "=", moduleName]]),
		limit_page_length: 20,
	});
	return rows?.[0]?.name || null;
}

async function expectRouteBlocked(page, routePath) {
	const target = getRoute(routePath);
	await page.goto(target);
	await page.waitForLoadState("domcontentloaded");
	const bodyText = await page.locator("body").innerText();
	const blocked = ACCESS_BLOCKED_TEXT_RE.test(bodyText);
	expect(page.url() !== target || blocked).toBe(true);
}

test.describe("Access control role-only flow", () => {
	const lifecycle = registerE2ELifecycle(test);
	const createdUsers = new Set();

	test.afterEach(async ({ page }) => {
		await loginAsAdmin(page);
		for (const email of createdUsers) {
			await deleteUserIfExists(page, email);
		}
		createdUsers.clear();
		await ensureAccessRule(page, { enabled: false });
	});

	test("@smoke denied user gets native stock entry UI without app custom fields", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());

		const deniedEmail = userEmail("denied", uniqueSuffix());
		createdUsers.add(deniedEmail);
		await ensureUser(page, {
			email: deniedEmail,
			firstName: "Denied",
			password: TEST_PASSWORD,
			roles: [STOCK_ENTRY_ROLE],
		});

		await loginAsAdmin(page);
		await ensureAccessRule(page, { enabled: true });

		await loginAs(page, deniedEmail, TEST_PASSWORD);
		await expect
			.poll(async () => {
				return await callFrappeMethod(
					page,
					"production_entry_app.production_entry_app.api.get_access_control_state"
				);
			})
			.toEqual({ enabled: false });

		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.openNew();
		await setFieldValue(page, "stock_entry_type", "Manufacture");
		await setFieldValue(page, "company", ctx.company);
		await setFieldValue(page, "from_bom", 1);
		await setFieldValue(page, "bom_no", ctx.bom);
		await setFieldValue(page, "fg_completed_qty", 100);

		expect(await stockEntryPage.isFieldVisible("custom_pea_shift")).toBe(false);
		expect(await stockEntryPage.isFieldVisible("custom_pea_workstation")).toBe(false);
		expect(await stockEntryPage.isFieldVisible("custom_pea_operator")).toBe(false);
		expect(await stockEntryPage.isFieldVisible("custom_pea_fetch_items")).toBe(false);
		expect(await stockEntryPage.isFieldVisible("custom_pea_rejection_breakup")).toBe(false);

		await expect(
			stockEntryPage.page.getByRole("button", { name: "Get Items", exact: true })
		).toBeVisible();
	});

	test("@regression denied user cannot see app entry or open workspace routes", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		await bootstrapE2E(page, lifecycle.getPrefix());

		const deniedEmail = userEmail("module-blocked", uniqueSuffix());
		createdUsers.add(deniedEmail);
		await ensureUser(page, {
			email: deniedEmail,
			firstName: "DeniedModule",
			password: TEST_PASSWORD,
			roles: [STOCK_ENTRY_ROLE],
		});

		await loginAsAdmin(page);
		await ensureAccessRule(page, { enabled: true });

		await loginAs(page, deniedEmail, TEST_PASSWORD);
		await page.goto("/app");
		await expect(page.getByText("Production Entry App", { exact: true })).toHaveCount(0);

		await expectRouteBlocked(page, "/production-entry-app");

		const workspaceName = await getWorkspaceNameForModule(page, "Production Entry App");
		if (workspaceName) {
			await expectRouteBlocked(page, `/workspace/${encodeURIComponent(workspaceName)}`);
		}
	});

	test("@regression allowed user sees app custom stock entry UI", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());

		const allowedEmail = userEmail("allowed", uniqueSuffix());
		createdUsers.add(allowedEmail);
		await ensureUser(page, {
			email: allowedEmail,
			firstName: "Allowed",
			password: TEST_PASSWORD,
			roles: [STOCK_ENTRY_ROLE, REQUIRED_ROLE],
		});

		await loginAsAdmin(page);
		await ensureAccessRule(page, { enabled: true });

		await loginAs(page, allowedEmail, TEST_PASSWORD);
		await expect
			.poll(async () => {
				return await callFrappeMethod(
					page,
					"production_entry_app.production_entry_app.api.get_access_control_state"
				);
			})
			.toEqual({ enabled: true });

		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.openNew();
		await stockEntryPage.setManufactureFields(ctx, {
			fgQty: 100,
			rejectionQty: 0,
		});

		await expect
			.poll(async () => await stockEntryPage.isFieldVisible("custom_pea_shift"))
			.toBe(true);
		await expect
			.poll(async () => await stockEntryPage.isFieldVisible("custom_pea_workstation"))
			.toBe(true);
		await expect
			.poll(async () => await stockEntryPage.isFieldVisible("custom_pea_operator"))
			.toBe(true);
		await expect
			.poll(async () => await stockEntryPage.isFieldVisible("custom_pea_fetch_items"))
			.toBe(true);
		await expect(
			stockEntryPage.page.getByRole("button", { name: "Get Items", exact: true })
		).not.toBeVisible();
	});

	test("@regression system manager bypass sees app entry and can open workspace routes", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());

		await loginAsAdmin(page);
		await ensureAccessRule(page, { enabled: true });

		await page.goto("/app");
		await page.goto(getRoute("/production-entry-app"));
		await page.waitForLoadState("domcontentloaded");
		expect(ACCESS_BLOCKED_TEXT_RE.test(await page.locator("body").innerText())).toBe(false);

		const workspaceName = await getWorkspaceNameForModule(page, "Production Entry App");
		if (workspaceName) {
			await page.goto(getRoute(`/workspace/${encodeURIComponent(workspaceName)}`));
			await page.waitForLoadState("domcontentloaded");
			expect(ACCESS_BLOCKED_TEXT_RE.test(await page.locator("body").innerText())).toBe(
				false
			);
		}

		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.openNew();
		await stockEntryPage.setManufactureFields(ctx, {
			fgQty: 100,
			rejectionQty: 0,
		});
		await expect
			.poll(async () => await stockEntryPage.isFieldVisible("custom_pea_shift"))
			.toBe(true);
	});
});
