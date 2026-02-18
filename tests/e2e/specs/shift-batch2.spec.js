const { test, expect } = require("@playwright/test");
const { bootstrapE2E, cleanupE2E } = require("../fixtures/test-data");
const { callFrappeMethod } = require("../fixtures/frappe");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");

async function setupFreshContext(page, prefix) {
	await cleanupE2E(page, prefix);
	return await bootstrapE2E(page, prefix);
}

async function openForm(page, doctypeRoute, name) {
	const doctypeByRoute = {
		shift: "Shift",
		workstation: "Workstation",
		operator: "Operator",
	};
	const encodedName = encodeURIComponent(name);
	await page.goto(`/app/${doctypeRoute}/${encodedName}`);
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

test.describe("Batch 2 shift UX", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@regression shift form has batch 2 tabs and metrics field", async ({ page }) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		await openForm(page, "shift", ctx.shift_name);

		const meta = await page.evaluate(() => {
			const m = frappe.get_meta("Shift");
			return {
				fieldNames: (m.fields || []).map((f) => f.fieldname),
				tabFields: (m.fields || [])
					.filter((f) => f.fieldtype === "Tab Break")
					.map((f) => f.fieldname),
			};
		});

		expect(meta.tabFields).toEqual(
			expect.arrayContaining([
				"tab_overview",
				"tab_warehouses",
				"tab_breaks",
				"tab_activity",
				"tab_metrics",
			])
		);
		expect(meta.fieldNames).toContain("shift_metrics");
	});

	test("@regression shift metrics renders empty state then table after production entry", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		await openForm(page, "shift", ctx.shift_name);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.shift_metrics;
			const text = (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
			return text.includes("No production entries linked to this shift yet.");
		});

		await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.create_e2e_submitted_stock_entry",
			{ prefix: lifecycle.getPrefix(), rejection_qty: 0 }
		);
		await page.reload();
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.shift_metrics;
			const text = (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
			return text.includes("Entries") && text.includes("1");
		});
	});

	test("@regression workstation and operator render timeline in dedicated html fields", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.create_e2e_submitted_stock_entry",
			{ prefix: lifecycle.getPrefix(), rejection_qty: 0 }
		);

		await openForm(page, "workstation", ctx.workstation);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.custom_shift_timeline_html;
			const text = (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
			return text.includes("Running Shift Timeline");
		});
		const workstationTimelineText = await page.evaluate(() => {
			const field = window.cur_frm?.fields_dict?.custom_shift_timeline_html;
			return (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
		});
		expect(workstationTimelineText).toContain(ctx.shift_name);

		await openForm(page, "operator", ctx.operator);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.shift_timeline_html;
			const text = (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
			return text.includes("Running Shift Timeline");
		});
		const operatorTimelineText = await page.evaluate(() => {
			const field = window.cur_frm?.fields_dict?.shift_timeline_html;
			return (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
		});
		expect(operatorTimelineText).toContain(ctx.shift_name);
	});

	test("@regression timeline shows empty-state when shift is running but no entries exist", async ({
		page,
	}) => {
		await page.goto("/app/home");
		const ctx = await setupFreshContext(page, lifecycle.getPrefix());

		await openForm(page, "workstation", ctx.workstation);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.custom_shift_timeline_html;
			const text = (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
			return text.includes("No production entries for current running shift.");
		});
		const workstationText = await getFieldText(page, "custom_shift_timeline_html");
		expect(workstationText).toContain("Running Shift Timeline");
		expect(workstationText).toContain("No production entries for current running shift.");

		await openForm(page, "operator", ctx.operator);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.shift_timeline_html;
			const text = (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
			return text.includes("No production entries for current running shift.");
		});
		const operatorText = await getFieldText(page, "shift_timeline_html");
		expect(operatorText).toContain("Running Shift Timeline");
		expect(operatorText).toContain("No production entries for current running shift.");
	});
});
