const { test, expect } = require("@playwright/test");
const { StockEntryPage } = require("../pages/stock-entry-page");

test("@smoke @regression Branch appears once on Stock Entry Details, not Connections", async ({
	page,
}) => {
	await new StockEntryPage(page).openNew();
	const details = page.locator("#stock-entry-stock_entry_details_tab");
	const connections = page.locator("#stock-entry-tab_connections");
	await expect(details.locator('[data-fieldname="branch"].frappe-control')).toHaveCount(1);
	await expect(details.locator('[data-fieldname="branch"].frappe-control')).toBeVisible();
	await expect(connections.locator('[data-fieldname="branch"].frappe-control')).toHaveCount(0);
});
