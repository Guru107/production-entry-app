const { test, expect } = require("@playwright/test");

const username = process.env.PLAYWRIGHT_USERNAME || "Administrator";
const password = process.env.PLAYWRIGHT_PASSWORD || "123";

test("authenticate admin for e2e", async ({ page }) => {
	await page.goto("/login");
	await page.getByRole("textbox", { name: "Email" }).fill(username);
	await page.getByRole("textbox", { name: "Password" }).fill(password);
	await page.getByRole("button", { name: "Login" }).click();

	await expect(page).toHaveURL(/\/app\//);
	await expect(page.getByRole("button", { name: "User Menu" })).toBeVisible();

	await page.context().storageState({ path: "tests/e2e/.auth/admin.json" });
});
