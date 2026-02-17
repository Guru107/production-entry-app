const { test, expect } = require("@playwright/test");
const { bootstrapE2E } = require("../fixtures/test-data");
const { getDoc, callFrappeMethod } = require("../fixtures/frappe");
const { expectValidationError } = require("../fixtures/assertions");
const { ShiftPage } = require("../pages/shift-page");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");

function plusOneDay(dateString) {
	const nextDate = new Date(dateString);
	nextDate.setDate(nextDate.getDate() + 1);
	return nextDate.toISOString().slice(0, 10);
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
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const shiftPage = new ShiftPage(page);

		await shiftPage.openNew();
		await shiftPage.setDraftFields({
			date: plusOneDay(ctx.shift_date),
			label: "2",
			duration: "8",
			startTime: "08:00:00",
		});
		await shiftPage.waitForPlannedLossRows(2);
		const planned8h = await shiftPage.getPlannedLosses();
		expect(planned8h).toHaveLength(2);
		expect(planned8h[0].downtime_reason).toBe("Tea Break");
		expect(planned8h[0].start_time).toBe("10:00:00");
		expect(planned8h[1].downtime_reason).toBe("Lunch Break");
		expect(planned8h[1].start_time).toBe("12:00:00");

		await shiftPage.setDraftFields({ duration: "10" });
		await shiftPage.waitForPlannedLossRows(3);
		const planned10h = await shiftPage.getPlannedLosses();
		expect(planned10h).toHaveLength(3);
		expect(planned10h[2].downtime_reason).toBe("Tea Break");
		expect(planned10h[2].start_time).toBe("14:00:00");

		await shiftPage.setDraftFields({ duration: "12" });
		await shiftPage.waitForPlannedLossRows(3);
		const planned12h = await shiftPage.getPlannedLosses();
		expect(planned12h).toHaveLength(3);
		expect(planned12h[2].downtime_reason).toBe("Tea Break");
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
