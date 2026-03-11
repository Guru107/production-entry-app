const { test, expect } = require("@playwright/test");
const { bootstrapE2E, cleanupE2E } = require("../fixtures/test-data");
const { getDoc, callFrappeMethod, setFieldValue } = require("../fixtures/frappe");
const { expectValidationError } = require("../fixtures/assertions");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");
const { ShiftPage } = require("../pages/shift-page");
const { StockEntryPage } = require("../pages/stock-entry-page");

function plusOneDay(dateString) {
	const nextDate = new Date(dateString);
	nextDate.setDate(nextDate.getDate() + 1);
	return nextDate.toISOString().slice(0, 10);
}

function plusDays(dateString, days) {
	const nextDate = new Date(dateString);
	nextDate.setDate(nextDate.getDate() + days);
	return nextDate.toISOString().slice(0, 10);
}

async function setupFreshContext(page, prefix) {
	await cleanupE2E(page, prefix);
	return await bootstrapE2E(page, prefix);
}

async function deleteShiftIfExists(page, date, label) {
	const name = `SHIFT-${date}.Shift-${label}`;
	const exists = await callFrappeMethod(page, "frappe.client.get_value", {
		doctype: "Shift",
		filters: JSON.stringify({ name }),
		fieldname: "name",
	});
	if (exists?.name) {
		await callFrappeMethod(page, "frappe.client.delete", {
			doctype: "Shift",
			name,
		});
	}
}

test.describe("Shift to Stock Entry integration", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@smoke running shift create action opens stock entry with shift prefilled", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const shiftPage = new ShiftPage(page);
		await shiftPage.open(ctx.shift_name);
		await shiftPage.createProductionEntryFromShift();

		const stockEntryPage = new StockEntryPage(page);
		const values = await stockEntryPage.getFieldValues(["stock_entry_type", "custom_shift"]);
		expect(values.stock_entry_type).toBe("Manufacture");
		expect(values.custom_shift).toBe(ctx.shift_name);
	});

	test("@regression selecting shift auto-fills branch and planned dates", async ({ page }) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());
		const shift = await getDoc(page, "Shift", ctx.shift_name);

		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.openNew();
		await setFieldValue(page, "stock_entry_type", "Manufacture");
		await stockEntryPage.waitForFieldValue("custom_stock_entry_purpose", "Manufacture");
		await stockEntryPage.setShift(ctx.shift_name);
		await stockEntryPage.waitForShiftAutoFill({
			branch: shift.branch || null,
			plannedStartIncludes: `${ctx.shift_date} 08:00:00`,
			plannedEndIncludes: "16:00:00",
		});

		const values = await stockEntryPage.getFieldValues([
			"branch",
			"custom_planned_start_date",
			"custom_planned_end_date",
		]);
		if (shift.branch) {
			expect(values.branch).toBe(shift.branch);
		}
		expect(String(values.custom_planned_start_date || "")).toContain(
			`${ctx.shift_date} 08:00:00`
		);
		expect(String(values.custom_planned_end_date || "")).toContain("16:00:00");
	});

	test("@regression clearing shift clears auto-filled planning and warehouse fields", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.openNew();
		await setFieldValue(page, "stock_entry_type", "Manufacture");
		await stockEntryPage.waitForFieldValue("custom_stock_entry_purpose", "Manufacture");
		await stockEntryPage.setShift(ctx.shift_name);
		await stockEntryPage.waitForShiftAutoFill({
			plannedStartIncludes: `${ctx.shift_date} 08:00:00`,
			plannedEndIncludes: "16:00:00",
			warehouse: ctx.wip_warehouse,
		});

		await stockEntryPage.clearShift();
		await stockEntryPage.waitForShiftCleared();

		const values = await stockEntryPage.getFieldValues([
			"custom_shift",
			"custom_planned_start_date",
			"custom_planned_end_date",
			"from_warehouse",
			"to_warehouse",
		]);
		expect(values.custom_shift).toBeFalsy();
		expect(values.custom_planned_start_date).toBeFalsy();
		expect(values.custom_planned_end_date).toBeFalsy();
		expect(values.from_warehouse).toBeFalsy();
		expect(values.to_warehouse).toBeFalsy();
	});

	test("@regression custom_shift query returns only running shifts", async ({ page }) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const shiftPage = new ShiftPage(page);
		const draft = await shiftPage.createDraftViaApi({
			date: plusOneDay(ctx.shift_date),
			label: "2",
			startTime: "16:00:00",
		});

		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.openNew();

		const runningResults = await stockEntryPage.searchShiftLinkResults(ctx.shift_name);
		const runningOptionNames = runningResults.map((row) => row.value || row.name || "");
		expect(runningOptionNames).toContain(ctx.shift_name);

		const draftResults = await stockEntryPage.searchShiftLinkResults(draft.name);
		const draftOptionNames = draftResults.map((row) => row.value || row.name || "");
		expect(draftOptionNames).not.toContain(draft.name);

		const draftShift = await getDoc(page, "Shift", draft.name);
		expect(draftShift.status).toBe("Draft");

		const runningShift = await getDoc(page, "Shift", ctx.shift_name);
		expect(runningShift.status).toBe("Running");

		const query = await callFrappeMethod(page, "frappe.client.get_list", {
			doctype: "Shift",
			filters: JSON.stringify([["name", "in", runningOptionNames]]),
			fields: JSON.stringify(["name", "status"]),
			limit_page_length: 50,
		});
		expect(query.length).toBeGreaterThan(0);
		for (const row of query) {
			expect(row.status).toBe("Running");
		}
	});

	test("@regression save is blocked when custom_shift points to draft shift", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const shiftPage = new ShiftPage(page);
		const draftDate = plusDays(ctx.shift_date, 2);
		const draftLabel = "2";
		await deleteShiftIfExists(page, draftDate, draftLabel);
		const draft = await shiftPage.createDraftViaApi({
			date: draftDate,
			label: draftLabel,
			startTime: "18:00:00",
		});

		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.openNew();
		await stockEntryPage.setManufactureFields(ctx, {
			fgQty: 100,
			rejectionQty: 0,
			shiftName: draft.name,
		});
		await setFieldValue(page, "from_warehouse", ctx.rm_warehouse);
		await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
		await stockEntryPage.fetchItems();
		await stockEntryPage.attemptSaveDraft();
		await expectValidationError(page, /Only Running shifts can be linked in Stock Entry/i);
	});
});
