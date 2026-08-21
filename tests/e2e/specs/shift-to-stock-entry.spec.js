const { test, expect } = require("@playwright/test");
const { bootstrapE2E, cleanupE2E } = require("../fixtures/test-data");
const { getDoc, callFrappeMethod, setFieldValue } = require("../fixtures/frappe");
const { expectValidationError } = require("../fixtures/assertions");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");
const { ShiftPage } = require("../pages/shift-page");
const { StockEntryPage } = require("../pages/stock-entry-page");
const { getRoute } = require("../utils/routing");

function plusOneDay(dateString) {
	const nextDate = new Date(dateString);
	nextDate.setDate(nextDate.getDate() + 1);
	return nextDate.toISOString().slice(0, 10);
}

function uniqueFutureDate() {
	const uniqueDay = String((Date.now() % 20) + 10).padStart(2, "0");
	return `2099-12-${uniqueDay}`;
}

async function setupFreshContext(page, prefix) {
	await cleanupE2E(page, prefix);
	return await bootstrapE2E(page, prefix);
}

async function ensureJointStockEntryType(page, prefix) {
	const existing = await callFrappeMethod(page, "frappe.client.get_list", {
		doctype: "Stock Entry Type",
		fields: JSON.stringify(["name"]),
		filters: JSON.stringify({
			purpose: "Repack",
			custom_pea_joint_lh_rh_production: 1,
		}),
		order_by: "modified desc, name asc",
		limit_page_length: 1,
	});
	if (existing?.length) return { name: existing[0].name, created: false };

	const name = `${prefix} Joint LH RH`;
	await callFrappeMethod(page, "frappe.client.insert", {
		doc: JSON.stringify({
			doctype: "Stock Entry Type",
			name,
			purpose: "Repack",
			custom_pea_joint_lh_rh_production: 1,
		}),
	});
	return { name, created: true };
}

async function deleteStockEntryTypeIfExists(page, name) {
	if (!name) return;
	const existing = await callFrappeMethod(page, "frappe.client.get_list", {
		doctype: "Stock Entry Type",
		fields: JSON.stringify(["name"]),
		filters: JSON.stringify({ name }),
		limit_page_length: 1,
	});
	if (existing?.length) {
		await callFrappeMethod(page, "frappe.client.delete", {
			doctype: "Stock Entry Type",
			name,
		});
	}
}

async function setSystemFloatPrecision(page, prefix, precision) {
	await callFrappeMethod(
		page,
		"production_entry_app.production_entry_app.e2e_api.set_e2e_system_float_precision",
		{ prefix, precision }
	);
}

async function openForm(page, doctypeRoute, name) {
	const doctypeByRoute = {
		shift: "Shift",
		workstation: "Workstation",
		operator: "Operator",
	};
	const encodedName = encodeURIComponent(name);
	await page.goto(getRoute(`/${doctypeRoute}/${encodedName}`));
	await page.waitForFunction(
		({ expectedName, expectedDoctype }) =>
			window.cur_frm?.doc?.name === expectedName &&
			window.cur_frm?.doctype === expectedDoctype,
		{ expectedName: name, expectedDoctype: doctypeByRoute[doctypeRoute] }
	);
}

async function getFieldText(page, fieldname) {
	return await page.evaluate((name) => {
		const field = window.cur_frm?.fields_dict?.[name];
		return (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
	}, fieldname);
}

async function getTimelineCanvasDetails(page, fieldname) {
	return await page.evaluate((name) => {
		const field = window.cur_frm?.fields_dict?.[name];
		const wrapper = field?.$wrapper?.[0];
		const canvas = wrapper?.querySelector(".pea-shift-timeline-canvas");
		if (!canvas) {
			return null;
		}
		const first = (canvas.__peaHitBoxes || [])[0];
		return {
			hasCanvas: true,
			firstCenter: first
				? { x: Math.round(first.x + first.w / 2), y: Math.round(first.y + first.h / 2) }
				: null,
		};
	}, fieldname);
}

async function dispatchTimelineCanvasEvent(page, fieldname, eventType, position) {
	return await page.evaluate(
		({ name, type, pos }) => {
			const field = window.cur_frm?.fields_dict?.[name];
			const canvas = field?.$wrapper?.[0]?.querySelector(".pea-shift-timeline-canvas");
			if (!canvas) {
				return false;
			}
			const rect = canvas.getBoundingClientRect();
			const clientX = rect.left + (pos?.x || 0);
			const clientY = rect.top + (pos?.y || 0);
			canvas.dispatchEvent(
				new MouseEvent(type, {
					bubbles: true,
					cancelable: true,
					clientX,
					clientY,
				})
			);
			return true;
		},
		{ name: fieldname, type: eventType, pos: position }
	);
}

function formatFloatForUi(value, precision) {
	return Number(value || 0).toFixed(precision);
}

async function createSubmittedDecimalManufactureEntry(page, prefix, options = {}) {
	return await callFrappeMethod(
		page,
		"production_entry_app.production_entry_app.e2e_api.create_e2e_submitted_stock_entry",
		{
			prefix,
			rejection_qty: options.rejectionQty ?? 0,
		}
	);
}

async function deleteShiftIfExists(page, { department, date, label }) {
	const rows = await callFrappeMethod(page, "frappe.client.get_list", {
		doctype: "Shift",
		fields: JSON.stringify(["name"]),
		filters: JSON.stringify({
			department,
			shift_date: date,
			shift_label: label,
		}),
		limit_page_length: 20,
	});
	for (const row of rows || []) {
		await callFrappeMethod(page, "frappe.client.delete", {
			doctype: "Shift",
			name: row.name,
		});
	}
}

test.describe("Shift to Stock Entry integration", () => {
	const lifecycle = registerE2ELifecycle(test);
	const createdStockEntryTypes = new Set();

	test.afterEach(async ({ page }) => {
		for (const name of createdStockEntryTypes) {
			await deleteStockEntryTypeIfExists(page, name);
		}
		createdStockEntryTypes.clear();
	});

	test("@smoke running shift create action opens stock entry with shift prefilled", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());
		const jointType = await ensureJointStockEntryType(page, lifecycle.getPrefix());
		if (jointType.created) createdStockEntryTypes.add(jointType.name);
		const shift = await getDoc(page, "Shift", ctx.shift_name);
		const shiftPage = new ShiftPage(page);
		await shiftPage.open(ctx.shift_name);
		await shiftPage.createProductionEntryFromShift();

		const stockEntryPage = new StockEntryPage(page);
		const values = await stockEntryPage.getFieldValues([
			"stock_entry_type",
			"custom_pea_shift",
		]);
		expect(values.stock_entry_type).toBe("Manufacture");
		expect(values.custom_pea_shift).toBe(ctx.shift_name);
		expect(ctx.shift_name).toMatch(new RegExp(`^SHIFT-${ctx.shift_date}\\.1\\.\\d{4}$`));

		await stockEntryPage.waitForShiftAutoFill({
			branch: shift.branch || null,
			plannedStartIncludes: `${ctx.shift_date} 08:00:00`,
			plannedEndIncludes: "16:00:00",
			warehouse: ctx.wip_warehouse,
		});
		const beforeJoint = await stockEntryPage.getFieldValues([
			"company",
			"branch",
			"custom_pea_shift",
			"custom_pea_planned_start_date",
			"custom_pea_planned_end_date",
			"from_warehouse",
			"to_warehouse",
		]);
		const jointCheckbox = page.getByRole("checkbox", {
			name: "Joint LH/RH Production",
			exact: true,
		});
		await expect(jointCheckbox).toBeVisible();
		await expect(jointCheckbox).toBeEnabled();
		await jointCheckbox.check();
		await stockEntryPage.waitForFieldValue("stock_entry_type", jointType.name);
		await stockEntryPage.waitForFieldValue("custom_pea_stock_entry_purpose", "Repack");

		const afterJoint = await stockEntryPage.getFieldValues([
			"company",
			"branch",
			"custom_pea_shift",
			"custom_pea_planned_start_date",
			"custom_pea_planned_end_date",
			"from_warehouse",
			"to_warehouse",
		]);
		expect(afterJoint).toEqual(beforeJoint);

		await stockEntryPage.setPostingDate(ctx.shift_date);
		await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
		await stockEntryPage.fillJointProductionFields(ctx, { lhRejectionQty: 1 });
		await stockEntryPage.setRejectionBreakupRows([
			{
				rejection_reason: "Burr",
				qty: 1,
				output_side: "LH",
				item_code: ctx.joint_lh_item,
			},
		]);
		await stockEntryPage.addUnplannedLossRow({
			downtime_reason: "Tea Break",
			start_time: "08:30:00",
			end_time: "08:40:00",
		});
		await stockEntryPage.fetchItems();
		await stockEntryPage.saveAndSubmit();

		const stockEntryName = await page.evaluate(() => cur_frm.doc.name);
		const submitted = await getDoc(page, "Stock Entry", stockEntryName);
		expect(submitted.docstatus).toBe(1);
		expect(submitted.custom_pea_shift).toBe(ctx.shift_name);
		expect(submitted.custom_pea_is_joint_lh_rh).toBe(1);
		expect(submitted.custom_pea_lh_gross_qty).toBe(40);
		expect(submitted.custom_pea_lh_rejection_qty).toBe(1);
		expect(submitted.custom_pea_rh_gross_qty).toBe(41);
		expect(submitted.custom_pea_total_strokes).toBe(41);
		expect(submitted.custom_pea_ok_qty).toBe(80);
		expect(submitted.custom_pea_total_rm_consumption).toBe(49.125);
		expect(submitted.custom_pea_joint_scrap_qty).toBeGreaterThan(0);
		expect(submitted.custom_pea_actual_duration_mins).toBe(60);
		expect(submitted.custom_pea_production_time_mins).toBeLessThan(60);
		expect(submitted.custom_pea_actual_spm).toBeCloseTo(
			41 / submitted.custom_pea_production_time_mins,
			6
		);
		expect(submitted.custom_pea_unplanned_losses).toHaveLength(1);
		expect(submitted.items.filter((row) => row.s_warehouse)).toHaveLength(1);
		expect(submitted.items.filter((row) => row.custom_pea_is_rejection_item)).toHaveLength(1);
		expect(
			submitted.items
				.filter(
					(row) => row.custom_pea_joint_output_side && !row.custom_pea_is_rejection_item
				)
				.every((row) => row.basic_rate > 0 && row.valuation_rate > 0)
		).toBe(true);
		const submittedScrapRow = submitted.items.find(
			(row) => row.is_scrap_item || row.is_legacy_scrap_item || row.type === "Scrap"
		);
		expect(submittedScrapRow).toBeDefined();
		expect(submittedScrapRow).toHaveProperty("is_finished_item");
	});

	test("@regression selecting shift auto-fills branch and planned dates", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());
		const shift = await getDoc(page, "Shift", ctx.shift_name);

		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.openNew();
		await setFieldValue(page, "stock_entry_type", "Manufacture");
		await stockEntryPage.waitForFieldValue("custom_pea_stock_entry_purpose", "Manufacture");
		await stockEntryPage.setShift(ctx.shift_name);
		await stockEntryPage.waitForShiftAutoFill({
			branch: shift.branch || null,
			plannedStartIncludes: `${ctx.shift_date} 08:00:00`,
			plannedEndIncludes: "16:00:00",
		});

		const values = await stockEntryPage.getFieldValues([
			"branch",
			"custom_pea_planned_start_date",
			"custom_pea_planned_end_date",
		]);
		if (shift.branch && values.branch !== undefined) {
			expect(values.branch).toBe(shift.branch);
		}
		expect(String(values.custom_pea_planned_start_date || "")).toContain(
			`${ctx.shift_date} 08:00:00`
		);
		expect(String(values.custom_pea_planned_end_date || "")).toContain("16:00:00");
	});

	test("@regression clearing shift clears auto-filled planning and warehouse fields", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.openNew();
		await setFieldValue(page, "stock_entry_type", "Manufacture");
		await stockEntryPage.waitForFieldValue("custom_pea_stock_entry_purpose", "Manufacture");
		await stockEntryPage.setShift(ctx.shift_name);
		await stockEntryPage.waitForShiftAutoFill({
			plannedStartIncludes: `${ctx.shift_date} 08:00:00`,
			plannedEndIncludes: "16:00:00",
			warehouse: ctx.wip_warehouse,
		});

		await stockEntryPage.clearShift();
		await stockEntryPage.waitForShiftCleared();

		const values = await stockEntryPage.getFieldValues([
			"custom_pea_shift",
			"custom_pea_planned_start_date",
			"custom_pea_planned_end_date",
			"from_warehouse",
			"to_warehouse",
		]);
		expect(values.custom_pea_shift).toBeFalsy();
		expect(values.custom_pea_planned_start_date).toBeFalsy();
		expect(values.custom_pea_planned_end_date).toBeFalsy();
		expect(values.from_warehouse).toBeFalsy();
		expect(values.to_warehouse).toBeFalsy();
	});

	test("@regression custom_pea_shift query returns running and completed shifts with title labels", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());
		const seededShift = await getDoc(page, "Shift", ctx.shift_name);

		const shiftPage = new ShiftPage(page);
		const draft = await shiftPage.createDraftViaApi({
			department: seededShift.department,
			branch: seededShift.branch,
			date: plusOneDay(ctx.shift_date),
			label: "2",
			startTime: "16:00:00",
		});

		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.openNew();

		const expectedShiftTitle = `${ctx.shift_date} 08:00-16:00`;
		const runningResults = await stockEntryPage.searchShiftLinkResults(ctx.shift_name);
		const runningOption = runningResults.find(
			(row) => (row.value || row.name || "") === ctx.shift_name
		);
		expect(runningOption).toBeTruthy();
		expect(runningOption.label).toBe(expectedShiftTitle);

		await shiftPage.open(ctx.shift_name);
		await shiftPage.endShift();
		await stockEntryPage.openNew();

		const completedResults = await stockEntryPage.searchShiftLinkResults(ctx.shift_name);
		const completedOptionNames = completedResults.map((row) => row.value || row.name || "");
		const completedOption = completedResults.find(
			(row) => (row.value || row.name || "") === ctx.shift_name
		);
		expect(completedOption).toBeTruthy();
		expect(completedOption.label).toBe(expectedShiftTitle);

		const draftResults = await stockEntryPage.searchShiftLinkResults(draft.name);
		const draftOptionNames = draftResults.map((row) => row.value || row.name || "");
		expect(draftOptionNames).not.toContain(draft.name);

		const draftShift = await getDoc(page, "Shift", draft.name);
		expect(draftShift.status).toBe("Draft");

		const completedShift = await getDoc(page, "Shift", ctx.shift_name);
		expect(completedShift.status).toBe("Completed");

		const query = await callFrappeMethod(page, "frappe.client.get_list", {
			doctype: "Shift",
			filters: JSON.stringify([["name", "in", completedOptionNames]]),
			fields: JSON.stringify(["name", "status"]),
			limit_page_length: 50,
		});
		expect(query.length).toBeGreaterThan(0);
		for (const row of query) {
			expect(["Running", "Completed"]).toContain(row.status);
		}
	});

	test("@regression save is blocked when custom_pea_shift points to draft shift", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());
		const runningShift = await getDoc(page, "Shift", ctx.shift_name);

		const shiftPage = new ShiftPage(page);
		const draftDate = uniqueFutureDate();
		const draftLabel = "2";
		await deleteShiftIfExists(page, {
			department: runningShift.department,
			date: draftDate,
			label: draftLabel,
		});
		const draft = await shiftPage.createDraftViaApi({
			department: runningShift.department,
			branch: runningShift.branch,
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
		await expectValidationError(
			page,
			/Only Running or Completed shifts can be linked in Stock Entry/i
		);
		await setFieldValue(page, "from_warehouse", ctx.rm_warehouse);
		await setFieldValue(page, "to_warehouse", ctx.fg_warehouse);
		await stockEntryPage.fetchItems();
		await stockEntryPage.attemptSaveDraft();
		await expect(page.evaluate(() => Boolean(window.cur_frm?.is_new?.()))).resolves.toBe(true);
	});

	test("@regression shift aggregate production entries format numeric metrics with system precision", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const prefix = `${lifecycle.getPrefix()}-shift-aggregate-precision`;
		const ctx = await setupFreshContext(page, prefix);
		await setSystemFloatPrecision(page, prefix, 4);

		const shiftPage = new ShiftPage(page);
		await shiftPage.open(ctx.shift_name);
		await createSubmittedDecimalManufactureEntry(page, prefix, { rejectionQty: 1 });
		await page.evaluate(async () => {
			await cur_frm.reload_doc();
		});
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.aggregate_production_entries;
			const text = (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
			return (
				text.includes("BOM Used") &&
				text.includes("Total Qty") &&
				text.includes("Total OK Qty") &&
				text.includes("Total Reject Qty") &&
				text.includes("Avg SPM")
			);
		});

		const rows = await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.doctype.shift.shift.get_shift_aggregate_production_entries",
			{ shift_name: ctx.shift_name }
		);
		const firstRow = rows[0];
		expect(firstRow).toBeTruthy();
		const aggregateText = await getFieldText(page, "aggregate_production_entries");
		expect(aggregateText).toContain(formatFloatForUi(firstRow.total_qty, 4));
		expect(aggregateText).toContain(formatFloatForUi(firstRow.total_ok_qty, 4));
		expect(aggregateText).toContain(formatFloatForUi(firstRow.total_reject_qty, 4));
		expect(aggregateText).toContain(formatFloatForUi(firstRow.avg_spm, 4));
	});

	test("@regression workstation timeline tooltip formats quantity values with system precision", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const prefix = `${lifecycle.getPrefix()}-timeline-precision`;
		const ctx = await setupFreshContext(page, prefix);
		await setSystemFloatPrecision(page, prefix, 4);

		await createSubmittedDecimalManufactureEntry(page, prefix, { rejectionQty: 1 });

		await openForm(page, "workstation", ctx.workstation);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.custom_pea_shift_timeline_html;
			const canvas = field?.$wrapper?.[0]?.querySelector(".pea-shift-timeline-canvas");
			return Boolean(canvas && (canvas.__peaHitBoxes || []).length > 0);
		});

		const timelineData = await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api_timeline.get_shift_timeline_data",
			{ doctype: "Workstation", docname: ctx.workstation }
		);
		const productionEntry = (timelineData.entries || []).find(
			(row) => row.entry_type === "production"
		);
		expect(productionEntry).toBeTruthy();
		const canvasData = await getTimelineCanvasDetails(page, "custom_pea_shift_timeline_html");
		expect(canvasData?.firstCenter).toBeTruthy();
		const hovered = await dispatchTimelineCanvasEvent(
			page,
			"custom_pea_shift_timeline_html",
			"mousemove",
			canvasData.firstCenter
		);
		expect(hovered).toBe(true);

		await page.waitForFunction(() => {
			const tooltip = document.querySelector(".pea-shift-timeline-tooltip");
			return Boolean(tooltip && getComputedStyle(tooltip).display !== "none");
		});
		const tooltipText = await page.locator(".pea-shift-timeline-tooltip").textContent();
		expect(String(tooltipText || "")).toContain(
			formatFloatForUi(productionEntry.fg_qty, timelineData.float_precision)
		);
		expect(String(tooltipText || "")).toContain(
			formatFloatForUi(productionEntry.rejection_qty, timelineData.float_precision)
		);
		expect(String(tooltipText || "")).toContain(
			formatFloatForUi(productionEntry.ok_qty, timelineData.float_precision)
		);
	});

	test("@regression changing shift_duration while Running updates planned end time and refreshes summary", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);

		await shiftPage.open(ctx.shift_name);
		await page.waitForFunction(() => window.cur_frm?.doc?.status === "Running", {
			timeout: 10000,
		});

		const originalDuration = await shiftPage.getFieldValue("shift_duration");
		const originalPlannedEndTime = await shiftPage.getFieldValue("planned_end_time");

		const newDuration = String(parseInt(originalDuration, 10) + 2);
		await setFieldValue(page, "shift_duration", newDuration);
		await shiftPage.saveDraft();
		await page.waitForFunction(() => window.cur_frm?.doc, { timeout: 10000 });

		const updatedDuration = await shiftPage.getFieldValue("shift_duration");
		expect(updatedDuration).toBe(newDuration);

		const updatedPlannedEndTime = await shiftPage.getFieldValue("planned_end_time");
		expect(updatedPlannedEndTime).not.toBe(originalPlannedEndTime);

		// Issue 1: Verify summary sections are rendered after save
		await page.waitForFunction(() => {
			const summaryField = window.cur_frm?.fields_dict?.shift_metrics;
			const text = (summaryField?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
			return text.includes("Planned Shift Mins") || text.includes("No production entries");
		});
		await page.waitForFunction(() => {
			const aggregateField = window.cur_frm?.fields_dict?.aggregate_production_entries;
			const text = (aggregateField?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
			return text.includes("BOM Used") || text.includes("No production entries");
		});

		// Issue 2: Verify Stock Entry creation path sees the revised planned end
		await shiftPage.createProductionEntryFromShift();
		const stockEntryPage = new StockEntryPage(page);
		await stockEntryPage.waitForShiftAutoFill({
			plannedEndIncludes: updatedPlannedEndTime.slice(-8),
		});
		const stockEntryPlannedEnd = await stockEntryPage.getFieldValues([
			"custom_pea_planned_start_date",
			"custom_pea_planned_end_date",
		]);
		expect(String(stockEntryPlannedEnd.custom_pea_planned_end_date || "")).toContain(
			updatedPlannedEndTime.slice(-8)
		);
	});
});
