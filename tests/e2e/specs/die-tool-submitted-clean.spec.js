import { test, expect } from "@playwright/test";

const { getRoute } = require("../utils/routing");

// Verifies the fix for: submitted Manufacture entries without a Die Tool Item
// went dirty on open because the BOM auto-fill set the field on load.
test("submitted entry without die tool item stays clean on open", async ({ page, request }) => {
	const exists = await request.get(`api/resource/Stock%20Entry/MAT-STE-01371`, {
		params: { fields: '["name"]' },
	});
	test.skip(exists.status() === 404, "MAT-STE-01371 only exists on the bench15 host");

	await page.goto(getRoute("/stock-entry/MAT-STE-01371"), { waitUntil: "domcontentloaded" });
	await page.waitForFunction(() => window.cur_frm && !window.cur_frm.loading, {
		timeout: 30000,
	});
	// Let the async BOM die-tool fetch settle.
	await page.waitForTimeout(2000);

	const snapshot = await page.evaluate(() => ({
		unsaved: Boolean(window.cur_frm.doc.__unsaved),
		docstatus: window.cur_frm.doc.docstatus,
		die_tool: window.cur_frm.doc.custom_pea_die_tool_item ?? null,
		field_rendered: "custom_pea_die_tool_item" in window.cur_frm.fields_dict,
	}));
	console.log("SNAPSHOT", JSON.stringify(snapshot));

	expect(snapshot.unsaved).toBe(false);
});
