const { test, expect } = require("@playwright/test");
const { bootstrapE2E, cleanupE2E, DOWNTIME_REASON } = require("../fixtures/test-data");
const { getDoc, callFrappeMethod } = require("../fixtures/frappe");
const { expectValidationError } = require("../fixtures/assertions");
const { ShiftPage } = require("../pages/shift-page");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");

const LOCKED_ONCE_STARTED_FIELDS = ["planned_losses", "shift_date", "shift_label"];

function plusDays(dateString, days) {
	const nextDate = new Date(dateString);
	nextDate.setDate(nextDate.getDate() + days);
	return nextDate.toISOString().slice(0, 10);
}

function plusOneDay(dateString) {
	return plusDays(dateString, 1);
}

async function setupFreshContext(page, prefix) {
	await cleanupE2E(page, prefix);
	return await bootstrapE2E(page, prefix);
}

async function deleteShiftIfExists(page, name) {
	try {
		await callFrappeMethod(page, "frappe.client.get", {
			doctype: "Shift",
			name,
		});
		await callFrappeMethod(page, "frappe.client.delete", {
			doctype: "Shift",
			name,
		});
	} catch (error) {
		const message = String(error?.message || "");
		if (
			!message.includes("DoesNotExistError") &&
			!message.includes("Resource is not available") &&
			!message.includes("not found")
		) {
			throw error;
		}
	}
}

async function deleteShiftsForDate(page, { shiftDate, company, department, branch }) {
	const rows = await callFrappeMethod(page, "frappe.client.get_list", {
		doctype: "Shift",
		filters: JSON.stringify({
			company,
			department,
			branch,
			shift_date: shiftDate,
		}),
		fields: JSON.stringify(["name"]),
		limit_page_length: 100,
	});
	for (const row of rows || []) {
		await deleteShiftIfExists(page, row.name);
	}
}

test.describe("Shift validations", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@regression starting second shift while one is running is blocked", async ({ page }) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const seededShift = await getDoc(page, "Shift", ctx.shift_name);
		const shiftPage = new ShiftPage(page);

		const draft = await shiftPage.createDraftViaApi({
			department: seededShift.department,
			branch: seededShift.branch,
			date: plusOneDay(ctx.shift_date),
			label: "2",
			startTime: "16:00:00",
		});

		await shiftPage.open(draft.name);
		try {
			await shiftPage.startShift();
		} catch (error) {
			// Validation toast/msgprint asserted below.
		}
		await expectValidationError(page, /Cannot start shift/i);

		const shiftAfterAttempt = await getDoc(page, "Shift", draft.name);
		expect(shiftAfterAttempt.status).toBe("Draft");
	});

	test("@regression overlap validation prevents save of overlapping shift", async ({ page }) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const seededShift = await getDoc(page, "Shift", ctx.shift_name);
		const shiftPage = new ShiftPage(page);
		const shiftDate = plusOneDay(ctx.shift_date);

		await shiftPage.createDraftViaApi({
			company: seededShift.company,
			department: seededShift.department,
			branch: seededShift.branch,
			date: shiftDate,
			label: "1",
			startTime: "08:00:00",
		});

		await shiftPage.openNew();
		await shiftPage.setDraftFields({
			company: seededShift.company,
			department: seededShift.department,
			branch: seededShift.branch,
			date: shiftDate,
			label: "2",
			duration: "8",
			startTime: "10:00:00",
		});
		await shiftPage.attemptSaveDraft();
		await expectValidationError(page, /overlap/i);
	});

	test("@regression duplicate shift label/date is blocked", async ({ page }) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const seededShift = await getDoc(page, "Shift", ctx.shift_name);
		const shiftPage = new ShiftPage(page);
		const shiftDate = plusOneDay(ctx.shift_date);

		await shiftPage.createDraftViaApi({
			department: seededShift.department,
			branch: seededShift.branch,
			date: shiftDate,
			label: "2",
			startTime: "08:00:00",
		});

		await shiftPage.openNew();
		await shiftPage.setDraftFields({
			department: seededShift.department,
			branch: seededShift.branch,
			date: shiftDate,
			label: "2",
			duration: "8",
			startTime: "16:00:00",
		});
		await shiftPage.attemptSaveDraft();
		await expectValidationError(page, /already exists/i);
	});

	test("@regression completed shift duration can extend but not overlap", async ({ page }) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const seededShift = await getDoc(page, "Shift", ctx.shift_name);
		const shiftPage = new ShiftPage(page);

		await shiftPage.open(ctx.shift_name);
		if (seededShift.status === "Draft") {
			await shiftPage.startShift();
		}
		if (seededShift.status !== "Completed") {
			await shiftPage.endShift();
		}
		const shiftScope = {
			company: seededShift.company,
			department: seededShift.department,
			branch: seededShift.branch,
		};

		const isolatedDate = plusDays(ctx.shift_date, 2);
		await deleteShiftsForDate(page, { ...shiftScope, shiftDate: isolatedDate });
		const isolatedShift = await shiftPage.createDraftViaApi({
			...shiftScope,
			date: isolatedDate,
			label: "2",
			startTime: "08:00:00",
		});
		await shiftPage.open(isolatedShift.name);
		await shiftPage.startShift();
		await shiftPage.endShift();
		await shiftPage.setDraftFields({ duration: "10" });
		await shiftPage.saveDraft();

		const extendedShift = await getDoc(page, "Shift", isolatedShift.name);
		expect(extendedShift.status).toBe("Completed");
		expect(extendedShift.shift_duration).toBe("10");
		expect(extendedShift.planned_end_time).toBe("18:00:00");

		const overlapDate = plusDays(ctx.shift_date, 3);
		await deleteShiftsForDate(page, { ...shiftScope, shiftDate: overlapDate });
		const firstShift = await shiftPage.createDraftViaApi({
			...shiftScope,
			date: overlapDate,
			label: "1",
			startTime: "08:00:00",
		});
		await shiftPage.open(firstShift.name);
		await shiftPage.startShift();
		await shiftPage.endShift();
		await shiftPage.createDraftViaApi({
			...shiftScope,
			date: overlapDate,
			label: "2",
			startTime: "16:00:00",
		});

		await shiftPage.open(firstShift.name);
		await shiftPage.setDraftFields({ duration: "10" });
		await shiftPage.attemptSaveDraft();
		await expectValidationError(page, /overlap/i);

		const unchangedShift = await getDoc(page, "Shift", firstShift.name);
		expect(unchangedShift.shift_duration).toBe("8");
	});

	test("@regression planned losses auto-populate and repopulate on duration change", async ({
		page,
	}) => {
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);

		await shiftPage.openNew();
		await shiftPage.setDraftFields({
			branch: ctx.branch,
			date: plusOneDay(ctx.shift_date),
			label: "2",
			duration: "8",
			startTime: "08:00:00",
		});
		await shiftPage.waitForPlannedLossRows(3);
		const planned8h = await shiftPage.getPlannedLosses();
		expect(planned8h).toHaveLength(3);
		expect(planned8h[0].downtime_reason).toBe(DOWNTIME_REASON.SHIFT_START_UP);
		expect(planned8h[0].start_time).toBe("08:00:00");
		expect(planned8h[1].downtime_reason).toBe(DOWNTIME_REASON.TEA_BREAK);
		expect(planned8h[1].start_time).toBe("09:00:00");
		expect(planned8h[2].downtime_reason).toBe(DOWNTIME_REASON.JH_ACTIVITY);
		expect(planned8h[2].start_time).toBe("10:00:00");

		await shiftPage.setDraftFields({ duration: "10" });
		await shiftPage.waitForPlannedLossRows(5);
		const planned10h = await shiftPage.getPlannedLosses();
		expect(planned10h).toHaveLength(5);
		expect(planned10h[4].downtime_reason).toBe(DOWNTIME_REASON.TEA_BREAK);
		expect(planned10h[4].start_time).toBe("17:00:00");

		await shiftPage.setDraftFields({ duration: "12" });
		await shiftPage.waitForPlannedLossRows(5);
		const planned12h = await shiftPage.getPlannedLosses();
		expect(planned12h).toHaveLength(5);
		expect(planned12h[4].downtime_reason).toBe(DOWNTIME_REASON.TEA_BREAK);
		expect(planned12h[4].start_time).toBe("17:00:00");
	});

	test("@regression planned start helper shorthand commits to canonical time and planned losses", async ({
		page,
	}) => {
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);

		await shiftPage.openNew();
		await shiftPage.setDraftFields({
			branch: ctx.branch,
			date: plusOneDay(ctx.shift_date),
			label: "2",
			duration: "8",
		});
		await shiftPage.fillHelperField("planned_start_time_input", "630");
		await shiftPage.waitForPlannedLossRows(3);

		expect(await shiftPage.getHelperFieldValue("planned_start_time_input")).toBe("06:30");
		expect(await shiftPage.getFieldValue("planned_start_time")).toBe("06:30:00");

		const planned = await shiftPage.getPlannedLosses();
		expect(planned[0].start_time).toBe("06:30:00");
	});

	test("@regression planned start chips and today button update helper-backed fields", async ({
		page,
	}) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);
		const targetDate = plusOneDay(ctx.shift_date);

		await shiftPage.openNew();
		await shiftPage.setDraftFields({
			branch: ctx.branch,
			date: targetDate,
			label: "2",
			duration: "8",
		});
		await shiftPage.clickFieldChip("planned_start_time_input", "14:00");
		await page.waitForFunction(() => window.cur_frm?.doc?.planned_start_time === "14:00:00");
		expect(await shiftPage.getFieldValue("planned_start_time")).toBe("14:00:00");

		await shiftPage.clickFieldChip("shift_date", "Today");
		const today = await page.evaluate(() => frappe.datetime.get_today());
		expect(await shiftPage.getFieldValue("shift_date")).toBe(today);
	});

	test("@regression planned losses auto-populate on new doc even when status is temporarily blank", async ({
		page,
	}) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);

		await shiftPage.openNew();
		await page.evaluate(() => {
			if (window.cur_frm?.doc) {
				window.cur_frm.doc.status = "";
			}
		});
		await shiftPage.setDraftFields({
			branch: ctx.branch,
			date: plusOneDay(ctx.shift_date),
			label: "2",
			duration: "8",
			startTime: "08:00:00",
		});
		await shiftPage.waitForPlannedLossRows(3);
		const planned = await shiftPage.getPlannedLosses();
		expect(planned).toHaveLength(3);
	});

	test("@regression End Shift rejects an unsaved date edit on a running shift", async ({
		page,
	}) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);
		await shiftPage.open(ctx.shift_name);
		if ((await getDoc(page, "Shift", ctx.shift_name)).status === "Draft") {
			await shiftPage.startShift();
		}

		// shift_date is read-only here; set_value stands in for an API client or a stale form.
		await shiftPage.setDraftFields({ date: plusOneDay(ctx.shift_date) });
		await shiftPage.clickActionAndConfirm("End Shift");

		await expectValidationError(
			page,
			"Only shift duration and warehouse fields can be edited"
		);
		const shift = await getDoc(page, "Shift", ctx.shift_name);
		expect(shift.status).toBe("Running");
		expect(shift.shift_date).toBe(ctx.shift_date);
	});

	test("@regression shift date picker stops at tomorrow and a shift for tomorrow asks to confirm", async ({
		page,
	}) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const seededShift = await getDoc(page, "Shift", ctx.shift_name);
		const shiftPage = new ShiftPage(page);
		await shiftPage.openNew();
		const tomorrow = await page.evaluate(() =>
			frappe.datetime.add_days(frappe.datetime.get_today(), 1)
		);
		const scope = {
			shiftDate: tomorrow,
			company: seededShift.company,
			department: seededShift.department,
			branch: seededShift.branch,
		};
		await deleteShiftsForDate(page, scope);

		try {
			const maxDate = await page.evaluate(() =>
				frappe.datetime.obj_to_str(cur_frm.fields_dict.shift_date.datepicker.opts.maxDate)
			);
			expect(maxDate).toBe(tomorrow);

			await shiftPage.setDraftFields({
				department: seededShift.department,
				branch: seededShift.branch,
				date: tomorrow,
				label: "1",
				startTime: "10:00:00",
			});
			const confirmDialog = page.locator(".modal:visible").filter({
				has: page.locator(".frappe-confirm-message"),
			});

			await shiftPage.attemptSaveDraft();
			await expect(confirmDialog).toContainText(
				"Are you sure you want to create a shift for"
			);
			await confirmDialog.getByRole("button", { name: "No" }).click();
			await expect(confirmDialog).toBeHidden();
			expect(await page.evaluate(() => cur_frm.is_new())).toBeTruthy();

			await shiftPage.attemptSaveDraft();
			await confirmDialog.getByRole("button", { name: "Yes" }).click();
			await page.waitForFunction(() => window.cur_frm && !window.cur_frm.is_new());
			const savedName = await page.evaluate(() => cur_frm.doc.name);
			expect(savedName.startsWith(`SHIFT-${tomorrow}.1.`)).toBeTruthy();

			// A later save of the same date does not ask again.
			await shiftPage.setDraftFields({ startTime: "11:00:00" });
			await shiftPage.saveDraft();
			await expect(confirmDialog).toHaveCount(0);
		} finally {
			await deleteShiftsForDate(page, scope);
		}
	});

	test("@regression shift date confirmation follows the opened shift, not the last one opened", async ({
		page,
	}) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const seededShift = await getDoc(page, "Shift", ctx.shift_name);
		const shiftPage = new ShiftPage(page);
		await shiftPage.openNew();
		const { today, tomorrow } = await page.evaluate(() => {
			const tomorrow = frappe.datetime.add_days(
				frappe.datetime.system_datetime().slice(0, 10),
				1
			);
			return { today: frappe.datetime.system_datetime().slice(0, 10), tomorrow };
		});
		const scope = {
			company: seededShift.company,
			department: seededShift.department,
			branch: seededShift.branch,
		};
		const dates = [today, tomorrow];
		for (const shiftDate of dates) {
			await deleteShiftsForDate(page, { ...scope, shiftDate });
		}
		const openInSession = async (name) => {
			await page.evaluate((docname) => frappe.set_route("Form", "Shift", docname), name);
			await page.waitForFunction(
				(docname) => window.cur_frm?.doc?.name === docname && !window.cur_frm.is_dirty(),
				name
			);
		};
		const confirmDialog = page.locator(".modal:visible").filter({
			has: page.locator(".frappe-confirm-message"),
		});

		try {
			const todayShift = await shiftPage.createDraftViaApi({
				...scope,
				date: today,
				label: "1",
				startTime: "06:00:00",
			});
			const tomorrowShift = await shiftPage.createDraftViaApi({
				...scope,
				date: tomorrow,
				label: "2",
				startTime: "14:00:00",
			});

			await openInSession(todayShift.name);
			await openInSession(tomorrowShift.name);
			await openInSession(todayShift.name);
			await shiftPage.setDraftFields({ date: tomorrow });
			await shiftPage.attemptSaveDraft();
			await expect(confirmDialog).toContainText(
				"Are you sure you want to create a shift for"
			);
			await confirmDialog.getByRole("button", { name: "No" }).click();
			await expect(confirmDialog).toBeHidden();
			await page.evaluate(() => cur_frm.reload_doc());
			await page.waitForFunction(() => !window.cur_frm.is_dirty());

			await openInSession(tomorrowShift.name);
			await openInSession(todayShift.name);
			await openInSession(tomorrowShift.name);
			await shiftPage.setDraftFields({ startTime: "15:00:00" });
			await shiftPage.saveDraft();
			await expect(confirmDialog).toHaveCount(0);

			// Leave the tomorrow shift dirty, open another shift, then come back and save.
			await shiftPage.setDraftFields({ startTime: "16:00:00" });
			await page.evaluate(
				(docname) => frappe.set_route("Form", "Shift", docname),
				todayShift.name
			);
			await page.waitForFunction(
				(docname) => window.cur_frm?.doc?.name === docname && !window.cur_frm.is_dirty(),
				todayShift.name
			);
			await page.evaluate(
				(docname) => frappe.set_route("Form", "Shift", docname),
				tomorrowShift.name
			);
			await page.waitForFunction(
				(docname) => window.cur_frm?.doc?.name === docname && window.cur_frm.is_dirty(),
				tomorrowShift.name
			);
			await shiftPage.saveDraft();
			await expect(confirmDialog).toHaveCount(0);
		} finally {
			for (const shiftDate of dates) {
				await deleteShiftsForDate(page, { ...scope, shiftDate });
			}
		}
	});

	test("@regression completed shift can be cancelled from the form", async ({ page }) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);
		await shiftPage.open(ctx.shift_name);
		const seededShift = await getDoc(page, "Shift", ctx.shift_name);
		if (seededShift.status === "Draft") {
			await shiftPage.startShift();
		}
		if (seededShift.status !== "Completed") {
			await shiftPage.endShift();
		}
		await shiftPage.open(ctx.shift_name);

		await shiftPage.clickActionAndConfirm("Cancel");

		await page.waitForFunction(() => window.cur_frm?.doc?.status === "Cancelled");
		expect((await getDoc(page, "Shift", ctx.shift_name)).status).toBe("Cancelled");
	});

	test("@regression planned losses, date and label are locked once shift starts", async ({
		page,
	}) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const seededShift = await getDoc(page, "Shift", ctx.shift_name);
		const shiftPage = new ShiftPage(page);

		const draft = await shiftPage.createDraftViaApi({
			department: seededShift.department,
			branch: seededShift.branch,
			date: plusOneDay(ctx.shift_date),
			label: "2",
			startTime: "16:00:00",
		});
		await shiftPage.open(draft.name);
		for (const fieldname of LOCKED_ONCE_STARTED_FIELDS) {
			expect(await shiftPage.isFieldReadOnly(fieldname)).toBe(false);
		}
		expect(await shiftPage.hasTodayButton()).toBe(true);

		await shiftPage.open(ctx.shift_name);
		for (const fieldname of LOCKED_ONCE_STARTED_FIELDS) {
			expect(await shiftPage.isFieldReadOnly(fieldname)).toBe(true);
		}
		expect(await shiftPage.hasTodayButton()).toBe(false);
	});

	test("@regression planned losses helper fields drive inline row calculations", async ({
		page,
	}) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const seededShift = await getDoc(page, "Shift", ctx.shift_name);
		const shiftPage = new ShiftPage(page);
		const editDate = plusOneDay(ctx.shift_date);
		const draft = await shiftPage.createDraftViaApi({
			department: seededShift.department,
			branch: seededShift.branch,
			date: editDate,
			label: "2",
			startTime: "08:00:00",
		});
		await shiftPage.open(draft.name);
		await shiftPage.waitForPlannedLossRows(3);
		await shiftPage.setPlannedLossHelperRow(0, {
			start_time_input: "1530",
			duration_mins_input: 20,
		});
		await shiftPage.saveDraft();

		// Rows must lie inside the 08:00-16:00 window since #257, so no midnight-wrapping row here.
		const savedShift = await getDoc(page, "Shift", draft.name);
		expect(savedShift.planned_losses[0].start_time).toBe("15:30:00");
		expect(savedShift.planned_losses[0].end_time).toBe("15:50:00");
	});

	test("@regression linked downtime section renders overlapping downtime entries", async ({
		page,
	}) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);
		const employeeRows = await callFrappeMethod(page, "frappe.client.get_list", {
			doctype: "Employee",
			fields: JSON.stringify(["name"]),
			limit_page_length: 1,
		});
		let employeeName = employeeRows?.[0]?.name;
		if (!employeeName) {
			const createdEmployee = await callFrappeMethod(page, "frappe.client.insert", {
				doc: JSON.stringify({
					doctype: "Employee",
					first_name: "E2E",
					last_name: "Shift",
					gender: "Female",
					date_of_birth: "1990-01-01",
					date_of_joining: "2020-01-01",
					company: ctx.company,
					status: "Active",
					employee_number: `${lifecycle.getPrefix()}-EMP`,
				}),
			});
			employeeName = createdEmployee.name;
		}

		let overlapDowntime;
		let nonOverlapDowntime;

		try {
			overlapDowntime = await callFrappeMethod(page, "frappe.client.insert", {
				doc: JSON.stringify({
					doctype: "Downtime Entry",
					workstation: ctx.workstation,
					operator: employeeName,
					from_time: `${ctx.shift_date} 10:00:00`,
					to_time: `${ctx.shift_date} 11:00:00`,
					custom_pea_downtime_reason: "00",
				}),
			});

			nonOverlapDowntime = await callFrappeMethod(page, "frappe.client.insert", {
				doc: JSON.stringify({
					doctype: "Downtime Entry",
					workstation: ctx.workstation,
					operator: employeeName,
					from_time: `${ctx.shift_date} 18:00:00`,
					to_time: `${ctx.shift_date} 19:00:00`,
					custom_pea_downtime_reason: "00",
				}),
			});

			await shiftPage.open(ctx.shift_name);
			const linkedSection = page
				.locator('[data-fieldname="linked_downtime_entries"]')
				.first();
			await expect(linkedSection).toContainText(overlapDowntime.name);
			await expect(linkedSection).not.toContainText(nonOverlapDowntime.name);
		} finally {
			if (overlapDowntime?.name) {
				await callFrappeMethod(page, "frappe.client.delete", {
					doctype: "Downtime Entry",
					name: overlapDowntime.name,
				});
			}
			if (nonOverlapDowntime?.name) {
				await callFrappeMethod(page, "frappe.client.delete", {
					doctype: "Downtime Entry",
					name: nonOverlapDowntime.name,
				});
			}
		}
	});

	test("@regression completed shift with a submitted entry cannot be cancelled", async ({
		page,
	}) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.e2e_api.create_e2e_submitted_stock_entry",
			{
				prefix: lifecycle.getPrefix(),
				shift_name: ctx.shift_name,
				complete_shift_before_submit: 1,
			}
		);

		const shiftPage = new ShiftPage(page);
		await shiftPage.open(ctx.shift_name);
		await shiftPage.clickActionAndConfirm("Cancel");
		await expectValidationError(
			page,
			/Cannot cancel Shift .*: it has 1 submitted Stock Entry\(s\) linked/i
		);

		const shiftAfterAttempt = await getDoc(page, "Shift", ctx.shift_name);
		expect(shiftAfterAttempt.status).toBe("Completed");
	});
});
