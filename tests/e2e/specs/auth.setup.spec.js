const { test, expect } = require("@playwright/test");

const username = process.env.PLAYWRIGHT_USERNAME || "Administrator";
const password = process.env.PLAYWRIGHT_PASSWORD || "123";

test("authenticate admin for e2e", async ({ page }) => {
	await page.goto("/login");
	await page.getByRole("textbox", { name: "Email" }).fill(username);
	await page.getByRole("textbox", { name: "Password" }).fill(password);
	await page.getByRole("button", { name: "Login" }).click();

	await expect(page).toHaveURL(/\/(app|desk)/);
	await page.waitForFunction(
		(expectedUser) => window.frappe?.session?.user === expectedUser,
		username
	);

	await page.context().storageState({ path: "tests/e2e/.auth/admin.json" });
});
