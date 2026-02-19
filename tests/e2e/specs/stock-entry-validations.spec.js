const { test, expect } = require("@playwright/test");
const { bootstrapE2E, cleanupE2E } = require("../fixtures/test-data");
const { getDoc, callFrappeMethod, setFieldValue } = require("../fixtures/frappe");
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

async function getOrCreateEmployee(page, ctx, employeeNumber) {
	const rows = await callFrappeMethod(page, "frappe.client.get_list", {
		doctype: "Employee",
		fields: JSON.stringify(["name"]),
		filters: JSON.stringify({ employee_number: employeeNumber }),
		limit_page_length: 1,
	});
	const employeeName = rows?.[0]?.name;
	if (employeeName) {
		return employeeName;
	}

	const created = await callFrappeMethod(page, "frappe.client.insert", {
		doc: JSON.stringify({
			doctype: "Employee",
			first_name: "E2E",
			last_name: "Stock Entry",
			gender: "Female",
			date_of_birth: "1990-01-01",
			date_of_joining: "2020-01-01",
			company: ctx.company,
			status: "Active",
			employee_number: employeeNumber,
		}),
	});
	return created.name;
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

	test("@regression custom stock entry purpose is fetched from stock entry type", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 0,
		});
		await stockEntryPage.waitForFieldValue("custom_stock_entry_purpose", "Manufacture");
		const values = await stockEntryPage.getFieldValues([
			"stock_entry_type",
			"custom_stock_entry_purpose",
		]);
		expect(values.stock_entry_type).toBe("Manufacture");
		expect(values.custom_stock_entry_purpose).toBe("Manufacture");
	});

	test("@regression manufacture sections are visible for manufacture stock entry type", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 0,
		});
		await stockEntryPage.waitForSectionVisible("bom_info_section");
		expect(await stockEntryPage.isSectionVisible("bom_info_section")).toBe(true);
		expect(await stockEntryPage.isSectionVisible("custom_operation_details_section")).toBe(
			true
		);
		expect(await stockEntryPage.isFieldVisible("custom_workstation")).toBe(true);
	});

	test("@regression manufacture sections hide for non-manufacture stock entry type", async ({
		page,
	}) => {
		await page.goto("/app/home");

		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.openNew();
		await setFieldValue(page, "stock_entry_type", "Material Transfer");
		await stockEntryPage.waitForFieldValue("custom_stock_entry_purpose", "Material Transfer");

		const values = await stockEntryPage.getFieldValues(["custom_stock_entry_purpose"]);
		expect(values.custom_stock_entry_purpose).toBe("Material Transfer");
		expect(await stockEntryPage.isSectionVisible("bom_info_section")).toBe(false);
		expect(await stockEntryPage.isSectionVisible("section_break_7qsm")).toBe(false);
		expect(await stockEntryPage.isSectionVisible("custom_operation_details_section")).toBe(
			false
		);
		expect(await stockEntryPage.isFieldVisible("custom_workstation")).toBe(false);
		expect(await stockEntryPage.isFieldVisible("custom_fetch_items")).toBe(false);
	});

	test("@regression manufacture sections remain visible after fetch items", async ({ page }) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 0,
		});
		await stockEntryPage.fetchItems();
		await stockEntryPage.waitForSectionVisible("bom_info_section");
		expect(await stockEntryPage.isSectionVisible("bom_info_section")).toBe(true);
		expect(await stockEntryPage.isFieldVisible("custom_workstation")).toBe(true);
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

	test("@regression blocks overlapping stock entry when workstation is already in use", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const firstStockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 0,
			actualStart: `${ctx.shift_date} 08:00:00`,
			actualEnd: `${ctx.shift_date} 09:00:00`,
		});
		await firstStockEntryPage.fetchItems();
		await setFieldValue(page, "custom_operator", null);
		await firstStockEntryPage.saveDraft();

		const stockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 0,
			actualStart: `${ctx.shift_date} 08:30:00`,
			actualEnd: `${ctx.shift_date} 09:30:00`,
		});
		await stockEntryPage.fetchItems();
		await setFieldValue(page, "custom_operator", null);
		await stockEntryPage.attemptSaveDraft();
		await expectValidationError(page, /Workstation .* already in use/i);
	});

	test("@regression blocks overlapping stock entry when operator is already assigned", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const firstStockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 0,
			actualStart: `${ctx.shift_date} 08:00:00`,
			actualEnd: `${ctx.shift_date} 09:00:00`,
		});
		await firstStockEntryPage.fetchItems();
		await setFieldValue(page, "custom_workstation", null);
		await firstStockEntryPage.saveDraft();

		const stockEntryPage = await openManufactureEntry(page, ctx, {
			fgQty: 100,
			rejectionQty: 0,
			actualStart: `${ctx.shift_date} 08:30:00`,
			actualEnd: `${ctx.shift_date} 09:30:00`,
		});
		await stockEntryPage.fetchItems();
		await setFieldValue(page, "custom_workstation", null);
		await stockEntryPage.attemptSaveDraft();
		await expectValidationError(page, /Operator .* already assigned/i);
	});

	test("@regression blocks stock entry when workstation has overlapping downtime", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const prefix = lifecycle.getPrefix();
		const ctx = await setupFreshContext(page, prefix);
		let downtimeEntryName;

		try {
			const employeeName = await getOrCreateEmployee(page, ctx, `${prefix}-DT-EMP`);
			const downtimeEntry = await callFrappeMethod(page, "frappe.client.insert", {
				doc: JSON.stringify({
					doctype: "Downtime Entry",
					workstation: ctx.workstation,
					operator: employeeName,
					from_time: `${ctx.shift_date} 08:15:00`,
					to_time: `${ctx.shift_date} 08:45:00`,
					stop_reason: "Other",
				}),
			});
			downtimeEntryName = downtimeEntry.name;

			const stockEntryPage = await openManufactureEntry(page, ctx, {
				fgQty: 100,
				rejectionQty: 0,
				actualStart: `${ctx.shift_date} 08:30:00`,
				actualEnd: `${ctx.shift_date} 09:30:00`,
			});
			await stockEntryPage.fetchItems();
			await setFieldValue(page, "custom_operator", null);
			await stockEntryPage.attemptSaveDraft();
			await expectValidationError(page, /downtime entry/i);
		} finally {
			if (downtimeEntryName) {
				await callFrappeMethod(page, "frappe.client.delete", {
					doctype: "Downtime Entry",
					name: downtimeEntryName,
				});
			}
		}
	});
});
