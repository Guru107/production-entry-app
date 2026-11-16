const { test, expect } = require("@playwright/test");
const { addDays, bootstrapE2E, cleanupE2E } = require("../fixtures/test-data");
const { getDoc } = require("../fixtures/frappe");
const { ShiftPage } = require("../pages/shift-page");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");

test.describe("Shift lifecycle", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@smoke draft shift can be cancelled", async ({ page }) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const seededShift = await getDoc(page, "Shift", ctx.shift_name);

		const nextDate = new Date(ctx.shift_date);
		nextDate.setDate(nextDate.getDate() + 1);
		const nextDateString = nextDate.toISOString().slice(0, 10);

		const shiftPage = new ShiftPage(page);
		const draft = await shiftPage.createDraftViaApi({
			department: seededShift.department,
			branch: seededShift.branch,
			date: nextDateString,
			label: "2",
			startTime: "16:00:00",
		});

		await shiftPage.open(draft.name);
		await shiftPage.cancelShift();

		const cancelledShift = await getDoc(page, "Shift", draft.name);
		expect(cancelledShift.status).toBe("Cancelled");
	});

	test("@smoke shift can start and end from UI actions", async ({ page }) => {
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

		const endedShift = await getDoc(page, "Shift", ctx.shift_name);
		expect(endedShift.status).toBe("Completed");

		const nextDate = new Date(ctx.shift_date);
		nextDate.setDate(nextDate.getDate() + 1);
		const nextDateString = nextDate.toISOString().slice(0, 10);

		const draft = await shiftPage.createDraftViaApi({
			department: seededShift.department,
			branch: seededShift.branch,
			date: nextDateString,
			label: "1",
			startTime: "08:00:00",
		});
		await shiftPage.open(draft.name);
		await shiftPage.startShift();

		const runningShift = await getDoc(page, "Shift", draft.name);
		expect(runningShift.status).toBe("Running");
	});

	test("editing a draft shift's date renames it on save", async ({ page }) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const seededShift = await getDoc(page, "Shift", ctx.shift_name);
		const shiftPage = new ShiftPage(page);
		const draft = await shiftPage.createDraftViaApi({
			department: seededShift.department,
			branch: seededShift.branch,
			date: addDays(ctx.shift_date, 1),
			label: "2",
			startTime: "16:00:00",
		});
		const movedDate = addDays(ctx.shift_date, 2);

		await shiftPage.open(draft.name);
		await shiftPage.setDraftFields({ date: movedDate });
		await shiftPage.saveDraft();

		await shiftPage.waitForRename(`SHIFT-${movedDate}.2.`);
		const renamed = await getDoc(page, "Shift", await shiftPage.getFieldValue("name"));
		expect(renamed.shift_date).toBe(movedDate);
	});

	test("starting a draft with an unsaved date edit follows the rename", async ({ page }) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const seededShift = await getDoc(page, "Shift", ctx.shift_name);
		const shiftPage = new ShiftPage(page);
		if (seededShift.status === "Running") {
			await shiftPage.open(ctx.shift_name);
			await shiftPage.endShift();
		}
		const draft = await shiftPage.createDraftViaApi({
			department: seededShift.department,
			branch: seededShift.branch,
			date: addDays(ctx.shift_date, 3),
			label: "2",
			startTime: "16:00:00",
		});
		const movedDate = addDays(ctx.shift_date, 4);

		await shiftPage.open(draft.name);
		await shiftPage.setDraftFields({ date: movedDate });
		await shiftPage.clickStartShiftButton();

		await shiftPage.waitForRename(`SHIFT-${movedDate}.2.`);
		await page.waitForFunction(() => window.cur_frm?.doc?.status === "Running");
	});

	test("cleanup is idempotent for repeated calls", async ({ page }) => {
		const prefix = lifecycle.getPrefix();
		await bootstrapE2E(page, prefix);

		const firstCleanup = await cleanupE2E(page, prefix);
		expect(firstCleanup.ok).toBe(true);

		const secondCleanup = await cleanupE2E(page, prefix);
		expect(secondCleanup.ok).toBe(true);
	});

	test("planned break population is debounced to a single API call", async ({ page }) => {
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const nextDate = new Date(ctx.shift_date);
		nextDate.setDate(nextDate.getDate() + 2);
		const shiftDate = nextDate.toISOString().slice(0, 10);

		let breakApiCalls = 0;
		page.on("request", (request) => {
			if (
				request
					.url()
					.includes(
						"production_entry_app.production_entry_app.doctype.shift.shift.get_planned_losses_for_duration"
					)
			) {
				breakApiCalls += 1;
			}
		});

		const shiftPage = new ShiftPage(page);
		await shiftPage.openNew();
		await page.evaluate(
			async ({ dateValue }) => {
				const frm = window.cur_frm;
				await frm.set_value("shift_date", dateValue);
				await frm.set_value("planned_start_time", "08:00:00");
				await frm.set_value("shift_duration", "8");
			},
			{ dateValue: shiftDate }
		);

		await shiftPage.waitForPlannedLossRows(2);
		await page.waitForTimeout(600);
		expect(breakApiCalls).toBe(1);
	});
});
