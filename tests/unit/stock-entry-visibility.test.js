const test = require("node:test");
const assert = require("node:assert/strict");

const {
	_normalize_purpose,
	_is_manufacture_doc,
	_did_leave_manufacture,
	MANUFACTURE_FIELDS,
	MANUFACTURE_SECTIONS,
	ALWAYS_HIDDEN_FIELDS,
	ALWAYS_HIDDEN_SECTIONS,
	MANUFACTURE_CLEAR_TABLE_FIELDS,
} = require("../../production_entry_app/public/js/stock_entry.js");

test("normalize purpose trims whitespace and handles empty values", () => {
	assert.equal(_normalize_purpose(" Manufacture "), "Manufacture");
	assert.equal(_normalize_purpose(""), "");
	assert.equal(_normalize_purpose(null), "");
});

test("manufacture decision uses custom_stock_entry_purpose only", () => {
	assert.equal(_is_manufacture_doc({ custom_stock_entry_purpose: "Manufacture" }), true);
	assert.equal(
		_is_manufacture_doc({ custom_stock_entry_purpose: "", purpose: "Manufacture" }),
		false
	);
	assert.equal(
		_is_manufacture_doc({
			custom_stock_entry_purpose: "Material Transfer",
			purpose: "Manufacture",
		}),
		false
	);
});

test("manufacture visibility targets include key fields and sections", () => {
	assert.ok(MANUFACTURE_FIELDS.includes("custom_fetch_items"));
	assert.ok(MANUFACTURE_FIELDS.includes("custom_shift"));
	assert.ok(MANUFACTURE_FIELDS.includes("custom_actual_start_date_input"));
	assert.ok(MANUFACTURE_FIELDS.includes("custom_actual_start_time_input"));
	assert.ok(MANUFACTURE_FIELDS.includes("custom_actual_end_date_input"));
	assert.ok(MANUFACTURE_FIELDS.includes("custom_actual_end_time_input"));
	assert.ok(MANUFACTURE_FIELDS.includes("custom_workstation"));
	assert.ok(MANUFACTURE_SECTIONS.includes("bom_info_section"));
	assert.ok(!MANUFACTURE_SECTIONS.includes("section_break_7qsm"));
	assert.ok(ALWAYS_HIDDEN_FIELDS.includes("process_loss_percentage"));
	assert.ok(ALWAYS_HIDDEN_SECTIONS.includes("section_break_7qsm"));
	assert.ok(MANUFACTURE_CLEAR_TABLE_FIELDS.includes("custom_rejection_breakup"));
	assert.ok(MANUFACTURE_CLEAR_TABLE_FIELDS.includes("items"));
});

test("leave-manufacture transition detector works", () => {
	assert.equal(_did_leave_manufacture("Manufacture", "Material Transfer"), true);
	assert.equal(_did_leave_manufacture("Manufacture", "Manufacture"), false);
	assert.equal(_did_leave_manufacture("Material Transfer", "Material Transfer"), false);
});
