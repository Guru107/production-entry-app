const { test, expect } = require("@playwright/test");
const { bootstrapE2E } = require("../fixtures/test-data");
const { getDoc } = require("../fixtures/frappe");
const { ShiftPage } = require("../pages/shift-page");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");

test.describe("Shift lifecycle", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@smoke draft shift can be cancelled", async ({ page }) => {
		await page.goto("/app/home");
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());

		const nextDate = new Date(ctx.shift_date);
		nextDate.setDate(nextDate.getDate() + 1);
		const nextDateString = nextDate.toISOString().slice(0, 10);

		const shiftPage = new ShiftPage(page);
		const draft = await shiftPage.createDraftViaApi({
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
		await page.goto("/app/home");
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
			date: nextDateString,
			label: "1",
			startTime: "08:00:00",
		});
		await shiftPage.open(draft.name);
		await shiftPage.startShift();

		const runningShift = await getDoc(page, "Shift", draft.name);
		expect(runningShift.status).toBe("Running");
	});
});
