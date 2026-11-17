const { test, expect } = require("@playwright/test");

const { deleteUserIfExists, ensureUser, loginAs } = require("../fixtures/users");
const { getRoute } = require("../utils/routing");

const ADMIN_USERNAME = process.env.PLAYWRIGHT_USERNAME || "Administrator";
const ADMIN_PASSWORD = process.env.PLAYWRIGHT_PASSWORD || "123";
const TEST_PASSWORD = process.env.PLAYWRIGHT_TEST_USER_PASSWORD || "E2eT3st!Pass#2026";
const MANUFACTURING_USER = "e2e_new_doc_timeline@example.com";

test.describe("Timeline panel on unsaved documents", () => {
	for (const [doctype, route] of [
		["Workstation", "/workstation/new"],
		["Operator", "/operator/new"],
	]) {
		test(`@regression Administrator opens a new ${doctype} with no dialog and an empty timeline`, async ({
			page,
		}) => {
			await page.goto(getRoute(route), { waitUntil: "domcontentloaded" });
			await page.waitForFunction(
				(expected) => window.cur_frm?.doctype === expected && window.cur_frm?.is_new?.(),
				doctype
			);
			await page.waitForLoadState("networkidle");

			await expect(page.locator(".msgprint-dialog:visible")).toHaveCount(0);
			await expect(page.locator(".pea-shift-timeline-canvas")).toHaveCount(0);
		});
	}

	for (const [doctype, route] of [
		["Workstation", "/workstation/new"],
		["Operator", "/operator/new"],
	]) {
		test(`@regression a supervisor opening a new ${doctype} sees no Not Found dialog`, async ({
			page,
		}) => {
			await deleteUserIfExists(page, MANUFACTURING_USER);
			await ensureUser(page, {
				email: MANUFACTURING_USER,
				firstName: "New Doc Timeline",
				password: TEST_PASSWORD,
				roles: ["PEA User", "Manufacturing User"],
			});

			try {
				await loginAs(page, MANUFACTURING_USER, TEST_PASSWORD);
				await page.goto(getRoute(route), { waitUntil: "domcontentloaded" });
				await page.waitForFunction(
					(expected) =>
						window.cur_frm?.doctype === expected && window.cur_frm?.is_new?.(),
					doctype
				);
				await page.waitForLoadState("networkidle");

				await expect(page.locator(".msgprint-dialog:visible")).toHaveCount(0);
			} finally {
				await loginAs(page, ADMIN_USERNAME, ADMIN_PASSWORD);
				await deleteUserIfExists(page, MANUFACTURING_USER);
			}
		});
	}
});
