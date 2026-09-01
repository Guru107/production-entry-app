const { test, expect } = require("@playwright/test");

const { expectValidationError } = require("../fixtures/assertions");
const { callFrappeMethod, saveForm, setFieldValue } = require("../fixtures/frappe");
const { deleteUserIfExists, ensureUser } = require("../fixtures/users");
const { getRoute } = require("../utils/routing");

const ADMIN_USERNAME = process.env.PLAYWRIGHT_USERNAME || "Administrator";
const ADMIN_PASSWORD = process.env.PLAYWRIGHT_PASSWORD || "123";
const TEST_PASSWORD = process.env.PLAYWRIGHT_TEST_USER_PASSWORD || "E2eT3st!Pass#2026";
const UNAUTHORIZED_USER = "e2e_rework_type_no_access@example.com";

async function openDeskHome(page) {
	await page.goto(getRoute("/home"));
	await page.waitForFunction(() => Boolean(window.frappe?.csrf_token));
}

async function loginAs(page, username, password) {
	const response = await page.request.post("/api/method/login", {
		form: { usr: username, pwd: password },
	});
	expect(response.ok()).toBeTruthy();
	await openDeskHome(page);
}

async function openNewReworkType(page) {
	await page.goto(getRoute("/rework-type/new"));
	await page.waitForFunction(
		() => window.cur_frm?.doctype === "Rework Type" && window.cur_frm?.is_new?.()
	);
}

async function deleteReworkTypeIfExists(page, name) {
	try {
		await callFrappeMethod(page, "frappe.client.delete", {
			doctype: "Rework Type",
			name,
		});
	} catch (error) {
		if (!String(error?.message || "").match(/DoesNotExistError|not found/i)) {
			throw error;
		}
	}
}

test.describe("Rework Type master", () => {
	test("@regression creates, edits, and lists a Rework Type", async ({ page }) => {
		const name = `E2E Rework Type ${Date.now()}`;

		try {
			await openNewReworkType(page);
			await setFieldValue(page, "rework_type_name", name);
			await saveForm(page);

			expect(await page.evaluate(() => window.cur_frm?.doc?.name)).toBe(name);
			expect(await page.evaluate(() => window.cur_frm?.doc?.is_active)).toBe(1);

			await setFieldValue(page, "is_active", 0);
			await saveForm(page);
			expect(await page.evaluate(() => window.cur_frm?.doc?.is_active)).toBe(0);

			await page.goto(getRoute("/rework-type"));
			await expect(
				page.locator(".list-row-container").filter({ hasText: name })
			).toBeVisible();
		} finally {
			await deleteReworkTypeIfExists(page, name);
		}
	});

	test("@regression requires a Rework Type name", async ({ page }) => {
		await openNewReworkType(page);

		await saveForm(page).catch(() => {});

		await expectValidationError(page, /Rework Type Name.*mandatory|Mandatory/i);
	});

	test("@regression blocks users without Rework Type access", async ({ page }) => {
		await openDeskHome(page);
		await deleteUserIfExists(page, UNAUTHORIZED_USER);
		await ensureUser(page, {
			email: UNAUTHORIZED_USER,
			firstName: "Rework Type No Access",
			password: TEST_PASSWORD,
			roles: ["Manufacturing User"],
		});

		try {
			await loginAs(page, UNAUTHORIZED_USER, TEST_PASSWORD);

			await expect(
				callFrappeMethod(page, "frappe.client.insert", {
					doc: JSON.stringify({
						doctype: "Rework Type",
						rework_type_name: "Unauthorized Rework Type",
					}),
				})
			).rejects.toThrow(/PermissionError|Not permitted|No permission/i);
		} finally {
			await loginAs(page, ADMIN_USERNAME, ADMIN_PASSWORD);
			await deleteUserIfExists(page, UNAUTHORIZED_USER);
		}
	});
});
