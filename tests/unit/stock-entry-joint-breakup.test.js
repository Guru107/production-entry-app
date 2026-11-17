const test = require("node:test");
const assert = require("node:assert/strict");

const {
	_prune_joint_production_breakup_rows,
	_drop_breakup_rows_of_remapped_sides,
	_apply_joint_slot_labels,
} = require("../../production_entry_app/public/js/stock_entry.js");

function sameItemFrm(boms, breakup, docname = "SE-1") {
	return {
		docname,
		doc: {
			__pea_same_item_joint_stock_entry_type: "Joint Production",
			stock_entry_type: "Joint Production",
			custom_pea_joint_production_lines: boms.map((bom_no) => ({ bom_no })),
			custom_pea_rejection_breakup: breakup,
		},
	};
}

test("prune writes custom_pea_rb_item_code and no item_code key", () => {
	const row = { output_side: "BOM 1", custom_pea_rb_item_code: "" };
	const frm = sameItemFrm(["B1", "B2"], [row]);

	_prune_joint_production_breakup_rows(frm, new Set(["BOM 1", "BOM 2"]), { "BOM 1": "ITEM-X" });

	assert.equal(row.custom_pea_rb_item_code, "ITEM-X");
	assert.equal("item_code" in row, false);
});

test("a remapped side drops its breakup rows", () => {
	const frm = sameItemFrm(["B1", "B2"], []);
	_drop_breakup_rows_of_remapped_sides(frm);
	frm.doc.custom_pea_rejection_breakup = [{ output_side: "BOM 1" }, { output_side: "BOM 2" }];

	frm.doc.custom_pea_joint_production_lines = [{ bom_no: "B2" }, { bom_no: "B2" }];
	_drop_breakup_rows_of_remapped_sides(frm);

	assert.deepEqual(
		frm.doc.custom_pea_rejection_breakup.map((row) => row.output_side),
		["BOM 2"]
	);
});

test("a side that was empty before keeps its rows when first populated", () => {
	const frm = sameItemFrm(["B1", ""], []);
	_drop_breakup_rows_of_remapped_sides(frm);
	frm.doc.custom_pea_rejection_breakup = [{ output_side: "BOM 2" }];

	frm.doc.custom_pea_joint_production_lines = [{ bom_no: "B1" }, { bom_no: "B2" }];
	_drop_breakup_rows_of_remapped_sides(frm);

	assert.equal(frm.doc.custom_pea_rejection_breakup.length, 1);
});

test("a different docname never drops rows", () => {
	const frm = sameItemFrm(["B1", "B2"], []);
	_drop_breakup_rows_of_remapped_sides(frm);

	frm.docname = "SE-2";
	frm.doc.custom_pea_joint_production_lines = [{ bom_no: "B9" }, { bom_no: "B8" }];
	frm.doc.custom_pea_rejection_breakup = [{ output_side: "BOM 1" }];
	_drop_breakup_rows_of_remapped_sides(frm);

	assert.equal(frm.doc.custom_pea_rejection_breakup.length, 1);
});

test("joint slot labels are re-applied after the docname changes", () => {
	const labelCalls = [];
	const frm = sameItemFrm(["B1", "B2"], []);
	frm.set_df_property = (fieldname, prop, value) => labelCalls.push([fieldname, prop, value]);

	_apply_joint_slot_labels(frm);
	const first = labelCalls.length;
	_apply_joint_slot_labels(frm);
	assert.equal(labelCalls.length, first);

	frm.docname = "SE-2";
	_apply_joint_slot_labels(frm);
	assert.ok(labelCalls.length > first);
});
