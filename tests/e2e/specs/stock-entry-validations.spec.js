const { test, expect } = require("@playwright/test");
const { bootstrapE2E, cleanupE2E } = require("../fixtures/test-data");
const { getDoc, callFrappeMethod } = require("../fixtures/frappe");
const { expectValidationError } = require("../fixtures/assertions");
const { StockEntryPage } = require("../pages/stock-entry-page");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");

async function setupFreshContext(page, prefix) {
	await cleanupE2E(page, prefix);
	return await bootstrapE2E(page, prefix);
}

async function openManufactureEntry(page, ctx, options = {}) {
	const stockEntryPage = new StockEntryPage(page);
	await stockEntryPage.openNew();
	await stockEntryPage.setManufactureFields(ctx, options);
	return stockEntryPage;
}

test.describe("Stock Entry validation matrix", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@smoke custom_fetch_items requires qty before fetching", async ({ page }) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 0,
			rejectionQty: 0,
		});
		await stockEntryPage.fetchItems();
		await expectValidationError(page, /Qty to Manufacture/i);
	});

	test("@regression rejection qty with empty breakup blocks save", async ({ page }) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 5,
		});
		await stockEntryPage.fetchItems();
		await stockEntryPage.attemptSaveDraft();
		await expectValidationError(page, /Rejection Breakup/i);
	});

	test("@regression rejection breakup total mismatch blocks save", async ({ page }) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 5,
		});
		await stockEntryPage.fetchItems();
		await stockEntryPage.setRejectionBreakupRows([
			{ rejection_reason: "Burr", qty: 3 },
			{ rejection_reason: "Crack", qty: 1 },
		]);

		await stockEntryPage.attemptSaveDraft();
		await expectValidationError(page, /must equal Rejection Quantity/i);
	});

	test("@regression rejection breakup row without reason blocks save", async ({ page }) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 5,
		});
		await stockEntryPage.fetchItems();
		await stockEntryPage.setRejectionBreakupRows([{ qty: 5 }]);

		await stockEntryPage.attemptSaveDraft();
		await expectValidationError(page, /rejection reason/i);
	});

	test("@regression rejection qty greater than finished good qty blocks save", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 150,
		});
		await stockEntryPage.fetchItems();
		await stockEntryPage.setRejectionBreakupRows([{ rejection_reason: "Burr", qty: 150 }]);

		await stockEntryPage.attemptSaveDraft();
		await expectValidationError(page, /cannot exceed Finished Good quantity/i);
	});

	test("@regression actual start outside configured buffer blocks save with range message", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 0,
			actualStart: `${ctx.shift_date} 06:59:00`,
			actualEnd: `${ctx.shift_date} 16:00:00`,
		});
		await stockEntryPage.fetchItems();

		await stockEntryPage.attemptSaveDraft();
		await expectValidationError(page, /Actual Start Date must be between/i);
	});

	test("@regression actual end before actual start blocks save", async ({ page }) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 0,
			actualStart: `${ctx.shift_date} 09:00:00`,
			actualEnd: `${ctx.shift_date} 08:59:00`,
		});
		await stockEntryPage.fetchItems();

		await stockEntryPage.attemptSaveDraft();
		await expectValidationError(page, /Actual End Date cannot be before Actual Start Date/i);
	});

	test("@regression unplanned loss row can be added and persists after save", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 0,
		});
		await stockEntryPage.fetchItems();
		await stockEntryPage.addUnplannedLossRow({
			downtime_reason: "Tea Break",
			start_time: "10:00:00",
			end_time: "10:15:00",
		});

		await stockEntryPage.saveDraft();
		const stockEntryName = await page.evaluate(() => window.cur_frm?.doc?.name);
		const savedStockEntry = await getDoc(page, "Stock Entry", stockEntryName);

		expect(savedStockEntry.custom_unplanned_losses || []).toHaveLength(1);
		expect(savedStockEntry.custom_unplanned_losses[0].downtime_reason).toBe("Tea Break");
	});

	test("@regression re-save remains idempotent for rejection row and finished good qty", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 10,
		});
		await stockEntryPage.fetchItems();
		await stockEntryPage.setRejectionBreakupRows([
			{ rejection_reason: "Burr", qty: 4 },
			{ rejection_reason: "Crack", qty: 6 },
		]);

		await stockEntryPage.saveDraft();
		const stockEntryName = await page.evaluate(() => window.cur_frm?.doc?.name);
		const stockEntryDoc = await callFrappeMethod(page, "frappe.client.get", {
			doctype: "Stock Entry",
			name: stockEntryName,
		});
		await callFrappeMethod(page, "frappe.client.save", {
			doc: JSON.stringify(stockEntryDoc),
		});

		const savedStockEntry = await getDoc(page, "Stock Entry", stockEntryName);
		const rejectionRows = (savedStockEntry.items || []).filter((row) =>
			Boolean(row.custom_is_rejection_item)
		);
		const fgRows = (savedStockEntry.items || []).filter((row) =>
			Boolean(row.is_finished_item)
		);

		expect(rejectionRows).toHaveLength(1);
		expect(Number(rejectionRows[0].qty)).toBe(10);
		expect(fgRows.length).toBeGreaterThan(0);
		expect(Number(fgRows[0].qty)).toBe(90);
	});
});
