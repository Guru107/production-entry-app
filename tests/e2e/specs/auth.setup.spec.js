const { test, expect } = require("@playwright/test");

const username = process.env.PLAYWRIGHT_USERNAME || "Administrator";
const password = process.env.PLAYWRIGHT_PASSWORD || "123";

test("authenticate admin for e2e", async ({ page }) => {
	const loginResponse = await page.request.post("/api/method/login", {
		form: {
			usr: username,
			pwd: password,
		},
	});
	expect(loginResponse.ok()).toBeTruthy();

	const userResponse = await page.request.get("/api/method/frappe.auth.get_logged_user");
	expect(userResponse.ok()).toBeTruthy();
	const userPayload = await userResponse.json();
	expect(userPayload.message).toBe(username);

	await page.context().storageState({ path: "tests/e2e/.auth/admin.json" });
});
