const { test, expect } = require("@playwright/test");
const { bootstrapE2E, cleanupE2E } = require("../fixtures/test-data");
const { callFrappeMethod } = require("../fixtures/frappe");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");
const { getRoute } = require("../utils/routing");

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

async function getTimelineCanvasDetails(page, fieldname) {
	return await page.evaluate((name) => {
		const field = window.cur_frm?.fields_dict?.[name];
		const wrapper = field?.$wrapper?.[0];
		const canvas = wrapper?.querySelector(".pea-shift-timeline-canvas");
		if (!canvas) {
			return null;
		}
		const first = (canvas.__peaHitBoxes || [])[0];
		const downtime = (canvas.__peaHitBoxes || []).find(
			(box) => box?.entry?.entry_type === "downtime"
		);
		return {
			hasCanvas: true,
			blockCount: (canvas.__peaHitBoxes || []).length,
			firstCenter: first
				? { x: Math.round(first.x + first.w / 2), y: Math.round(first.y + first.h / 2) }
				: null,
			downtimeCenter: downtime
				? {
						x: Math.round(downtime.x + downtime.w / 2),
						y: Math.round(downtime.y + downtime.h / 2),
				  }
				: null,
		};
	}, fieldname);
}

async function getTimelineCoverageDetails(page, fieldname) {
	return await page.evaluate((name) => {
		const field = window.cur_frm?.fields_dict?.[name];
		const wrapper = field?.$wrapper?.[0];
		const canvas = wrapper?.querySelector(".pea-shift-timeline-canvas");
		if (!canvas) {
			return null;
		}
		const hitBoxes = canvas.__peaHitBoxes || [];
		const bar = canvas.__peaBarFrame || null;
		if (!bar || !hitBoxes.length) {
			return {
				blockCount: hitBoxes.length,
				bar: bar || null,
				coveragePct: 0,
			};
		}
		const firstX = Math.min(...hitBoxes.map((b) => b.x));
		const maxRight = Math.max(...hitBoxes.map((b) => b.x + b.w));
		const used = Math.max(0, maxRight - firstX);
		return {
			blockCount: hitBoxes.length,
			bar,
			firstX,
			maxRight,
			coveragePct: (used / bar.w) * 100,
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

test.describe("Batch 2 shift UX", () => {
	const lifecycle = registerE2ELifecycle(test);

	test("@regression shift form has batch 2 tabs and metrics field", async ({ page }) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, `${lifecycle.getPrefix()}-tabs`);

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
				"tab_aggregate_entries",
			])
		);
		expect(meta.fieldNames).toContain("shift_metrics");
		expect(meta.fieldNames).toContain("aggregate_production_entries");
	});

	test("@regression shift metrics renders empty state then table after production entry", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const testPrefix = `${lifecycle.getPrefix()}-metrics`;
		const ctx = await setupFreshContext(page, testPrefix);

		await openForm(page, "shift", ctx.shift_name);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.shift_metrics;
			const text = (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
			return (
				text.includes("No production entries linked to this shift yet.") ||
				(text.includes("Entries") && text.includes("Total Qty"))
			);
		});

		await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.create_e2e_submitted_stock_entry",
			{ prefix: testPrefix, rejection_qty: 0 }
		);
		await page.evaluate(async () => {
			await cur_frm.reload_doc();
		});
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.shift_metrics;
			const text = (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
			return text.includes("Entries") && text.includes("Total Qty");
		});
	});

	test("@regression shift aggregate entries renders empty state then table after production entry", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const testPrefix = `${lifecycle.getPrefix()}-aggregate`;
		const ctx = await setupFreshContext(page, testPrefix);

		await openForm(page, "shift", ctx.shift_name);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.aggregate_production_entries;
			const text = (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
			return (
				text.includes("No production entries linked to this shift yet.") ||
				(text.includes("BOM Used") && text.includes("Item Code"))
			);
		});

		await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.create_e2e_submitted_stock_entry",
			{ prefix: testPrefix, rejection_qty: 5 }
		);
		await page.evaluate(async () => {
			await cur_frm.reload_doc();
		});
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.aggregate_production_entries;
			const text = (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
			return (
				text.includes("BOM Used") &&
				text.includes("Item Code") &&
				text.includes("Total Qty") &&
				text.includes("Total OK Qty") &&
				text.includes("Total Reject Qty") &&
				text.includes("Avg SPM")
			);
		});
		const aggregateText = await getFieldText(page, "aggregate_production_entries");
		expect(aggregateText).toContain(ctx.bom);
		expect(aggregateText).toContain(ctx.fg_item);
	});

	test("@regression workstation and operator render timeline in dedicated html fields", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const testPrefix = `${lifecycle.getPrefix()}-timeline`;
		const ctx = await setupFreshContext(page, testPrefix);

		await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.create_e2e_submitted_stock_entry",
			{ prefix: testPrefix, rejection_qty: 0 }
		);

		await openForm(page, "workstation", ctx.workstation);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.custom_shift_timeline_html;
			return Boolean(field?.$wrapper?.[0]?.querySelector(".pea-shift-timeline-canvas"));
		});
		const workstationCanvas = await getTimelineCanvasDetails(
			page,
			"custom_shift_timeline_html"
		);
		expect(workstationCanvas?.hasCanvas).toBe(true);
		expect(workstationCanvas?.blockCount).toBeGreaterThan(0);
		const workstationTimelineText = await page.evaluate(() => {
			const field = window.cur_frm?.fields_dict?.custom_shift_timeline_html;
			return (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
		});
		expect(workstationTimelineText).toContain(ctx.shift_name);

		await openForm(page, "operator", ctx.operator);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.shift_timeline_html;
			return Boolean(field?.$wrapper?.[0]?.querySelector(".pea-shift-timeline-canvas"));
		});
		const operatorCanvas = await getTimelineCanvasDetails(page, "shift_timeline_html");
		expect(operatorCanvas?.hasCanvas).toBe(true);
		expect(operatorCanvas?.blockCount).toBeGreaterThan(0);
		const operatorTimelineText = await page.evaluate(() => {
			const field = window.cur_frm?.fields_dict?.shift_timeline_html;
			return (field?.$wrapper?.text?.() || "").replace(/\s+/g, " ").trim();
		});
		expect(operatorTimelineText).toContain(ctx.shift_name);
	});

	test("@regression timeline shows empty-state when shift is running but no entries exist", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const ctx = await setupFreshContext(page, `${lifecycle.getPrefix()}-empty`);

		await openForm(page, "workstation", ctx.workstation);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.custom_shift_timeline_html;
			const canvas = field?.$wrapper?.[0]?.querySelector(".pea-shift-timeline-canvas");
			return Boolean(canvas && (canvas.__peaHitBoxes || []).length === 0);
		});
		const workstationText = await getFieldText(page, "custom_shift_timeline_html");
		expect(workstationText).toContain("Running Shift Timeline");

		await openForm(page, "operator", ctx.operator);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.shift_timeline_html;
			const canvas = field?.$wrapper?.[0]?.querySelector(".pea-shift-timeline-canvas");
			return Boolean(canvas && (canvas.__peaHitBoxes || []).length === 0);
		});
		const operatorText = await getFieldText(page, "shift_timeline_html");
		expect(operatorText).toContain("Running Shift Timeline");
	});

	test("@regression timeline hover shows tooltip and click opens stock entry", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const testPrefix = `${lifecycle.getPrefix()}-hover`;
		const ctx = await setupFreshContext(page, testPrefix);

		const stockEntry = await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.create_e2e_submitted_stock_entry",
			{ prefix: testPrefix, rejection_qty: 0 }
		);

		await openForm(page, "workstation", ctx.workstation);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.custom_shift_timeline_html;
			const canvas = field?.$wrapper?.[0]?.querySelector(".pea-shift-timeline-canvas");
			return Boolean(canvas && (canvas.__peaHitBoxes || []).length > 0);
		});

		const canvasData = await getTimelineCanvasDetails(page, "custom_shift_timeline_html");
		expect(canvasData?.firstCenter).toBeTruthy();
		const hovered = await dispatchTimelineCanvasEvent(
			page,
			"custom_shift_timeline_html",
			"mousemove",
			canvasData.firstCenter
		);
		expect(hovered).toBe(true);
		await page.waitForFunction(() => {
			const tooltip = document.querySelector(".pea-shift-timeline-tooltip");
			if (!tooltip || getComputedStyle(tooltip).display === "none") {
				return false;
			}
			return (tooltip.textContent || "").includes("OK Qty");
		});
		const clicked = await dispatchTimelineCanvasEvent(
			page,
			"custom_shift_timeline_html",
			"click",
			canvasData.firstCenter
		);
		expect(clicked).toBe(true);
		await page.waitForURL(/\/app\/stock-entry\//);
		await page.waitForFunction(
			(expected) =>
				window.cur_frm?.doctype === "Stock Entry" &&
				window.cur_frm?.doc?.name === expected,
			stockEntry?.name
		);
	});

	test("@regression timeline renders contiguous full-shift production entries across entire duration", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const testPrefix = `${lifecycle.getPrefix()}-fullshift`;
		const ctx = await setupFreshContext(page, testPrefix);

		const result = await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.create_e2e_full_shift_stock_entries",
			{ prefix: testPrefix, slot_minutes: 60, rejection_qty: 0 }
		);
		expect(Number(result?.count || 0)).toBeGreaterThanOrEqual(8);

		await openForm(page, "workstation", ctx.workstation);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.custom_shift_timeline_html;
			const canvas = field?.$wrapper?.[0]?.querySelector(".pea-shift-timeline-canvas");
			return Boolean(canvas && (canvas.__peaHitBoxes || []).length > 0);
		});

		const workstationCoverage = await getTimelineCoverageDetails(
			page,
			"custom_shift_timeline_html"
		);
		expect(workstationCoverage?.blockCount).toBe(result.count);
		expect(workstationCoverage?.coveragePct).toBeGreaterThan(95);
		expect(workstationCoverage?.firstX).toBeGreaterThanOrEqual(
			(workstationCoverage?.bar?.x || 0) - 3
		);
		expect(workstationCoverage?.maxRight).toBeLessThanOrEqual(
			(workstationCoverage?.bar?.x || 0) + (workstationCoverage?.bar?.w || 0) + 3
		);

		await openForm(page, "operator", ctx.operator);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.shift_timeline_html;
			const canvas = field?.$wrapper?.[0]?.querySelector(".pea-shift-timeline-canvas");
			return Boolean(canvas && (canvas.__peaHitBoxes || []).length > 0);
		});
		const operatorCoverage = await getTimelineCoverageDetails(page, "shift_timeline_html");
		expect(operatorCoverage?.blockCount).toBe(result.count);
		expect(operatorCoverage?.coveragePct).toBeGreaterThan(95);
	});

	test("@regression workstation timeline includes downtime entries and opens downtime form on click", async ({
		page,
	}) => {
		await page.goto(getRoute("/home"));
		const testPrefix = `${lifecycle.getPrefix()}-downtime`;
		const ctx = await setupFreshContext(page, testPrefix);

		await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.api.create_e2e_downtime_entry",
			{
				prefix: testPrefix,
				from_time: "10:00:00",
				to_time: "10:30:00",
				stop_reason: "Other",
			}
		);

		await openForm(page, "workstation", ctx.workstation);
		await page.waitForFunction(() => {
			const field = window.cur_frm?.fields_dict?.custom_shift_timeline_html;
			const canvas = field?.$wrapper?.[0]?.querySelector(".pea-shift-timeline-canvas");
			const boxes = canvas?.__peaHitBoxes || [];
			return boxes.some((box) => box?.entry?.entry_type === "downtime");
		});

		const canvasData = await getTimelineCanvasDetails(page, "custom_shift_timeline_html");
		expect(canvasData?.downtimeCenter).toBeTruthy();
		const hovered = await dispatchTimelineCanvasEvent(
			page,
			"custom_shift_timeline_html",
			"mousemove",
			canvasData.downtimeCenter
		);
		expect(hovered).toBe(true);
		await page.waitForFunction(() => {
			const tooltip = document.querySelector(".pea-shift-timeline-tooltip");
			if (!tooltip || getComputedStyle(tooltip).display === "none") {
				return false;
			}
			const text = tooltip.textContent || "";
			return text.includes("Type: Downtime") && text.includes("Other");
		});

		const clicked = await dispatchTimelineCanvasEvent(
			page,
			"custom_shift_timeline_html",
			"click",
			canvasData.downtimeCenter
		);
		expect(clicked).toBe(true);
		await page.waitForURL(/\/app\/downtime-entry\/[^/]+$/);
		await page.waitForFunction(() => window.cur_frm?.doctype === "Downtime Entry");
	});
});
