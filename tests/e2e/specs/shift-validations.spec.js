const { test, expect } = require("@playwright/test");
const { bootstrapE2E, cleanupE2E } = require("../fixtures/test-data");
const { getDoc, callFrappeMethod } = require("../fixtures/frappe");
const { expectValidationError } = require("../fixtures/assertions");
const { ShiftPage } = require("../pages/shift-page");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");

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

test.describe("Shift validations", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@regression starting second shift while one is running is blocked", async ({ page }) => {
		await page.goto("/app/home");
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);

		const draft = await shiftPage.createDraftViaApi({
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
		await page.goto("/app/home");
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);
		const shiftDate = plusOneDay(ctx.shift_date);

		await shiftPage.createDraftViaApi({
			date: shiftDate,
			label: "1",
			startTime: "08:00:00",
		});

		await shiftPage.openNew();
		await shiftPage.setDraftFields({
			date: shiftDate,
			label: "2",
			duration: "8",
			startTime: "10:00:00",
		});
		await shiftPage.attemptSaveDraft();
		await expectValidationError(page, /overlap/i);
	});

	test("@regression duplicate shift label/date is blocked", async ({ page }) => {
		await page.goto("/app/home");
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);
		const shiftDate = plusOneDay(ctx.shift_date);

		await shiftPage.createDraftViaApi({
			date: shiftDate,
			label: "2",
			startTime: "08:00:00",
		});

		await shiftPage.openNew();
		await shiftPage.setDraftFields({
			date: shiftDate,
			label: "2",
			duration: "8",
			startTime: "16:00:00",
		});
		await shiftPage.attemptSaveDraft();
		await expectValidationError(page, /already exists/i);
	});

	test("@regression planned losses auto-populate and repopulate on duration change", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);

		await shiftPage.openNew();
		await shiftPage.setDraftFields({
			date: plusOneDay(ctx.shift_date),
			label: "2",
			duration: "8",
			startTime: "08:00:00",
		});
		await shiftPage.waitForPlannedLossRows(3);
		const planned8h = await shiftPage.getPlannedLosses();
		expect(planned8h).toHaveLength(3);
		expect(planned8h[0].downtime_reason).toBe("Shift Start Up");
		expect(planned8h[0].start_time).toBe("08:00:00");
		expect(planned8h[1].downtime_reason).toBe("JH Activity");
		expect(planned8h[1].start_time).toBe("08:10:00");
		expect(planned8h[2].downtime_reason).toBe("Tea Break");
		expect(planned8h[2].start_time).toBe("09:00:00");

		await shiftPage.setDraftFields({ duration: "10" });
		await shiftPage.waitForPlannedLossRows(5);
		const planned10h = await shiftPage.getPlannedLosses();
		expect(planned10h).toHaveLength(5);
		expect(planned10h[4].downtime_reason).toBe("Tea Break");
		expect(planned10h[4].start_time).toBe("17:00:00");

		await shiftPage.setDraftFields({ duration: "12" });
		await shiftPage.waitForPlannedLossRows(5);
		const planned12h = await shiftPage.getPlannedLosses();
		expect(planned12h).toHaveLength(5);
		expect(planned12h[4].downtime_reason).toBe("Tea Break");
		expect(planned12h[4].start_time).toBe("17:00:00");
	});

	test("@regression planned start helper shorthand commits to canonical time and planned losses", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);

		await shiftPage.openNew();
		await shiftPage.setDraftFields({
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
		await page.goto("/app/home");
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);
		const targetDate = plusOneDay(ctx.shift_date);

		await shiftPage.openNew();
		await shiftPage.setDraftFields({
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
		await page.goto("/app/home");
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);

		await shiftPage.openNew();
		await page.evaluate(() => {
			if (window.cur_frm?.doc) {
				window.cur_frm.doc.status = "";
			}
		});
		await shiftPage.setDraftFields({
			date: plusOneDay(ctx.shift_date),
			label: "2",
			duration: "8",
			startTime: "08:00:00",
		});
		await shiftPage.waitForPlannedLossRows(3);
		const planned = await shiftPage.getPlannedLosses();
		expect(planned).toHaveLength(3);
	});

	test("@regression planned losses grid is non-editable once shift starts", async ({ page }) => {
		await page.goto("/app/home");
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);

		const draft = await shiftPage.createDraftViaApi({
			date: plusOneDay(ctx.shift_date),
			label: "2",
			startTime: "16:00:00",
		});
		await shiftPage.open(draft.name);
		expect(await shiftPage.isPlannedLossesReadOnly()).toBe(false);

		await shiftPage.open(ctx.shift_name);
		expect(await shiftPage.isPlannedLossesReadOnly()).toBe(true);
	});

	test("@regression planned losses helper fields drive inline row calculations", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);
		const editDate = uniqueFutureDate();
		const draftName = `SHIFT-${editDate}.Shift-2`;
		await deleteShiftIfExists(page, draftName);

		const draft = await shiftPage.createDraftViaApi({
			date: editDate,
			label: "2",
			startTime: "08:00:00",
		});
		await shiftPage.open(draft.name);
		await shiftPage.waitForPlannedLossRows(3);
		await shiftPage.setPlannedLossHelperRow(0, {
			start_time_input: "2350",
			duration_mins_input: 20,
		});
		await shiftPage.saveDraft();

		const savedShift = await getDoc(page, "Shift", draft.name);
		expect(savedShift.planned_losses[0].start_time).toBe("23:50:00");
		expect(String(savedShift.planned_losses[0].end_time)).toMatch(/^(00|0):10:00$/);
	});

	test("@regression linked downtime section renders overlapping downtime entries", async ({
		page,
	}) => {
		await page.goto("/app/home");
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
					stop_reason: "Other",
				}),
			});

			nonOverlapDowntime = await callFrappeMethod(page, "frappe.client.insert", {
				doc: JSON.stringify({
					doctype: "Downtime Entry",
					workstation: ctx.workstation,
					operator: employeeName,
					from_time: `${ctx.shift_date} 18:00:00`,
					to_time: `${ctx.shift_date} 19:00:00`,
					stop_reason: "Other",
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
});
