const { test, expect } = require("@playwright/test");

const { expectValidationError } = require("../fixtures/assertions");
const { callFrappeMethod, saveForm, setFieldValue } = require("../fixtures/frappe");
const { deleteUserIfExists, ensureUser, loginAs } = require("../fixtures/users");
const { getRoute } = require("../utils/routing");

const ADMIN_USERNAME = process.env.PLAYWRIGHT_USERNAME || "Administrator";
const ADMIN_PASSWORD = process.env.PLAYWRIGHT_PASSWORD || "123";
const TEST_PASSWORD = process.env.PLAYWRIGHT_TEST_USER_PASSWORD || "E2eT3st!Pass#2026";
const UNAUTHORIZED_USER = "e2e_downtime_reason_no_access@example.com";

async function openDeskHome(page) {
	await page.goto(getRoute("/home"));
	await page.waitForFunction(() => Boolean(window.frappe?.csrf_token));
}

async function openNewDowntimeReason(page) {
	await page.goto(getRoute("/downtime-reason/new"));
	await page.waitForFunction(
		() => window.cur_frm?.doctype === "Downtime Reason" && window.cur_frm?.is_new?.()
	);
}

async function deleteDowntimeReasonIfExists(page, name) {
	try {
		await callFrappeMethod(page, "frappe.client.delete", {
			doctype: "Downtime Reason",
			name,
		});
	} catch (error) {
		if (!String(error?.message || "").match(/DoesNotExistError|not found/i)) {
			throw error;
		}
	}
}

test.describe("Downtime Reason master", () => {
	test("@regression creates, edits, and lists a Downtime Reason by code", async ({ page }) => {
		const code = `8${Math.floor(Math.random() * 9)}`;
		const description = `E2E Downtime Reason ${Date.now()}`;

		try {
			await openNewDowntimeReason(page);
			await setFieldValue(page, "code", code);
			await setFieldValue(page, "description", description);
			await saveForm(page);

			expect(await page.evaluate(() => window.cur_frm?.doc?.name)).toBe(code);
			expect(await page.evaluate(() => window.cur_frm?.doc?.is_active)).toBe(1);

			const editedDescription = `${description} edited`;
			await setFieldValue(page, "description", editedDescription);
			await saveForm(page);
			expect(await page.evaluate(() => window.cur_frm?.doc?.description)).toBe(
				editedDescription
			);
			expect(await page.evaluate(() => window.cur_frm?.doc?.name)).toBe(code);

			await page.evaluate(
				(filterCode) => frappe.set_route("List", "Downtime Reason", { code: filterCode }),
				code
			);
			await page.locator(".list-row-container").first().waitFor();
			await expect(
				page.locator(".list-row-container").filter({ hasText: editedDescription })
			).toBeVisible();
		} finally {
			await deleteDowntimeReasonIfExists(page, code);
		}
	});

	test("@regression requires a code and a description", async ({ page }) => {
		await openNewDowntimeReason(page);

		await saveForm(page).catch(() => {});

		await expectValidationError(page, /Code.*required|Code.*mandatory|Mandatory/i);
	});

	async function saveAndCaptureMessage(page) {
		return await page.evaluate(
			() =>
				new Promise((resolve) => {
					Promise.resolve(cur_frm.save("Save")).catch(() => {});
					const startedAt = Date.now();
					const timer = setInterval(() => {
						const message = (
							window.frappe?.msg_dialog?.msg_area?.text?.() || ""
						).trim();
						if (message || Date.now() - startedAt > 10000) {
							clearInterval(timer);
							resolve(message);
						}
					}, 100);
				})
		);
	}

	test("@regression rejects a code that is not a two-digit number", async ({ page }) => {
		await openNewDowntimeReason(page);

		await setFieldValue(page, "code", "1a");
		await setFieldValue(page, "description", "E2E Invalid Code Reason");
		expect(await saveAndCaptureMessage(page)).toMatch(/two-digit/i);

		await setFieldValue(page, "code", "123");
		expect(await saveAndCaptureMessage(page)).toMatch(/two-digit/i);
	});

	test("@regression blocks users without Downtime Reason access", async ({ page }) => {
		await openDeskHome(page);
		await deleteUserIfExists(page, UNAUTHORIZED_USER);
		await ensureUser(page, {
			email: UNAUTHORIZED_USER,
			firstName: "Downtime Reason No Access",
			password: TEST_PASSWORD,
			roles: ["PEA User"],
		});

		try {
			await loginAs(page, UNAUTHORIZED_USER, TEST_PASSWORD);

			await expect(
				callFrappeMethod(page, "frappe.client.insert", {
					doc: JSON.stringify({
						doctype: "Downtime Reason",
						code: "89",
						description: "Unauthorized Downtime Reason",
					}),
				})
			).rejects.toThrow(/PermissionError|Not permitted|No permission/i);
		} finally {
			await loginAs(page, ADMIN_USERNAME, ADMIN_PASSWORD);
			await deleteUserIfExists(page, UNAUTHORIZED_USER);
		}
	});
});
