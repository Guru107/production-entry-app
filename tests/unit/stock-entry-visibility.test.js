const test = require("node:test");
const assert = require("node:assert/strict");

const {
	_normalize_purpose,
	_is_manufacture_doc,
	_did_leave_manufacture,
	_apply_native_manufacture_visibility,
	_should_override_fg_completed_qty,
	_run_when_app_enabled,
	_sync_native_get_items_access,
	_apply_shift_detail_updates,
	_apply_fetch_items_response,
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

test("manufacture decision uses custom_pea_stock_entry_purpose only", () => {
	assert.equal(_is_manufacture_doc({ custom_pea_stock_entry_purpose: "Manufacture" }), true);
	assert.equal(
		_is_manufacture_doc({ custom_pea_stock_entry_purpose: "", purpose: "Manufacture" }),
		false
	);
	assert.equal(
		_is_manufacture_doc({
			custom_pea_stock_entry_purpose: "Material Transfer",
			purpose: "Manufacture",
		}),
		false
	);
});

test("manufacture visibility targets include key fields and sections", () => {
	assert.ok(MANUFACTURE_FIELDS.includes("custom_pea_fetch_items"));
	assert.ok(MANUFACTURE_FIELDS.includes("custom_pea_shift"));
	assert.ok(MANUFACTURE_FIELDS.includes("custom_pea_actual_start_date_input"));
	assert.ok(MANUFACTURE_FIELDS.includes("custom_pea_actual_start_time_input"));
	assert.ok(MANUFACTURE_FIELDS.includes("custom_pea_actual_end_date_input"));
	assert.ok(MANUFACTURE_FIELDS.includes("custom_pea_actual_end_time_input"));
	assert.ok(MANUFACTURE_FIELDS.includes("custom_pea_workstation"));
	assert.ok(MANUFACTURE_SECTIONS.includes("bom_info_section"));
	assert.ok(!MANUFACTURE_SECTIONS.includes("section_break_7qsm"));
	assert.ok(ALWAYS_HIDDEN_FIELDS.includes("process_loss_percentage"));
	assert.ok(ALWAYS_HIDDEN_SECTIONS.includes("section_break_7qsm"));
	assert.ok(MANUFACTURE_CLEAR_TABLE_FIELDS.includes("custom_pea_rejection_breakup"));
	assert.ok(MANUFACTURE_CLEAR_TABLE_FIELDS.includes("items"));
});

test("leave-manufacture transition detector works", () => {
	assert.equal(_did_leave_manufacture("Manufacture", "Material Transfer"), true);
	assert.equal(_did_leave_manufacture("Manufacture", "Manufacture"), false);
	assert.equal(_did_leave_manufacture("Material Transfer", "Material Transfer"), false);
});

test("native manufacture fields hide for non-manufacture without app access", () => {
	assert.equal(typeof _apply_native_manufacture_visibility, "function");
	const calls = [];
	const frm = {
		doc: {
			custom_pea_stock_entry_purpose: "Material Transfer",
		},
		toggle_display(fieldnames, visible) {
			calls.push([fieldnames, visible]);
		},
	};

	_apply_native_manufacture_visibility(frm);

	assert.deepEqual(calls, [
		[["from_bom", "bom_no", "use_multi_level_bom", "fg_completed_qty"], false],
		[["bom_info_section"], false],
		[["process_loss_percentage", "process_loss_qty"], false],
		[["section_break_7qsm"], false],
	]);
});

test("stock entry PEA sections are metadata-gated to manufacture", () => {
	const customFields = require("../../production_entry_app/fixtures/custom_field.json");
	const byFieldname = Object.fromEntries(
		customFields.filter((row) => row.dt === "Stock Entry").map((row) => [row.fieldname, row])
	);
	const sectionFieldnames = [
		"custom_pea_operation_details_section",
		"custom_pea_workstation_operator_section",
		"custom_pea_unplanned_losses_section",
		"custom_pea_metrics_section",
	];

	for (const fieldname of sectionFieldnames) {
		const dependsOn = byFieldname[fieldname]?.depends_on || "";
		assert.match(dependsOn, /custom_pea_stock_entry_purpose/);
		assert.match(dependsOn, /Manufacture/);
	}
});

test("fg completed qty override stays enabled for native manufacture flow", () => {
	assert.equal(_should_override_fg_completed_qty(), true);
});

test("fg completed qty prototype patch preserves ERPNext fallback for non-manufacture documents", () => {
	const modulePath = "../../production_entry_app/public/js/stock_entry.js";
	const moduleId = require.resolve(modulePath);
	const cachedModule = require.cache[moduleId];
	const originalErpnext = global.erpnext;
	let originalCallCount = 0;
	const erpnextStub = {
		stock: {
			StockEntry: function StockEntry() {},
		},
	};
	erpnextStub.stock.StockEntry.prototype.fg_completed_qty = function () {
		originalCallCount += 1;
		return "native-result";
	};

	delete require.cache[moduleId];
	global.erpnext = erpnextStub;
	global.window = { erpnext: erpnextStub };

	try {
		require(modulePath);

		const controller = new erpnextStub.stock.StockEntry();
		controller.frm = {
			doc: { custom_pea_stock_entry_purpose: "Material Transfer", from_bom: 1 },
		};

		assert.equal(controller.fg_completed_qty(), "native-result");
		assert.equal(originalCallCount, 1);
	} finally {
		if (cachedModule) {
			require.cache[moduleId] = cachedModule;
		} else {
			delete require.cache[moduleId];
		}
		global.erpnext = originalErpnext;
	}
});

test("shift detail updates clear present empty values instead of leaving stale fields", async () => {
	const updates = [];
	const frm = {
		fields_dict: {
			company: {},
			branch: {},
			custom_pea_planned_start_date: {},
			custom_pea_planned_end_date: {},
			from_warehouse: {},
		},
		set_value(fieldname, value) {
			updates.push([fieldname, value]);
			return Promise.resolve();
		},
	};

	await _apply_shift_detail_updates(frm, {
		company: "Test Company",
		branch: "",
		custom_pea_planned_start_date: null,
		custom_pea_planned_end_date: "2026-02-22 16:00:00",
		from_warehouse: undefined,
	});

	assert.deepEqual(updates, [
		["company", "Test Company"],
		["branch", ""],
		["custom_pea_planned_start_date", null],
		["custom_pea_planned_end_date", "2026-02-22 16:00:00"],
		["from_warehouse", undefined],
	]);
});

test("shift detail updates skip absent fields without aborting later updates", async () => {
	const updates = [];
	const frm = {
		fields_dict: {
			company: {},
			custom_pea_planned_start_date: {},
			from_warehouse: {},
		},
		set_value(fieldname, value) {
			updates.push([fieldname, value]);
			return Promise.resolve();
		},
	};

	await _apply_shift_detail_updates(frm, {
		company: "Test Company",
		branch: "Missing Branch Field",
		custom_pea_planned_start_date: "2026-02-22 08:00:00",
		from_warehouse: "Stores - TC",
	});

	assert.deepEqual(updates, [
		["company", "Test Company"],
		["custom_pea_planned_start_date", "2026-02-22 08:00:00"],
		["from_warehouse", "Stores - TC"],
	]);
});

test("shift detail updates stop when the request becomes stale", async () => {
	const updates = [];
	let current = true;
	const frm = {
		fields_dict: {
			company: {},
			branch: {},
			custom_pea_planned_start_date: {},
		},
		set_value(fieldname, value) {
			updates.push([fieldname, value]);
			current = false;
			return Promise.resolve();
		},
	};

	const applied = await _apply_shift_detail_updates(
		frm,
		{
			company: "Old Company",
			branch: "Old Branch",
			custom_pea_planned_start_date: "2026-02-22 08:00:00",
		},
		() => current
	);

	assert.equal(applied, false);
	assert.deepEqual(updates, [["company", "Old Company"]]);
});

test("fetch items response refreshes form so ERPNext can add alternate item button", () => {
	const originalFrappe = global.frappe;
	const originalFlt = global.flt;
	const originalTranslate = global.__;
	let refreshCount = 0;
	const apiCalls = [];
	global.flt = Number;
	global.__ = (text) => text;
	global.frappe = {
		model: {
			add_child(doc, doctype, fieldname) {
				const row = { doctype };
				doc[fieldname].push(row);
				return row;
			},
		},
		call(options) {
			apiCalls.push(options.method);
		},
	};
	const frm = {
		doc: {
			custom_pea_stock_entry_purpose: "Manufacture",
			custom_pea_rejection_qty: 0,
			items: [{ item_code: "STALE" }],
		},
		fields_dict: {
			custom_pea_die_tool_utilization_pct: {},
			custom_pea_die_tool_maintenance_due: {},
		},
		layout: { sections: [] },
		clear_table(fieldname) {
			this.doc[fieldname] = [];
		},
		refresh_field() {},
		refresh_fields() {},
		toggle_display() {},
		toggle_reqd() {},
		dirty() {},
		refresh() {
			refreshCount += 1;
		},
	};

	try {
		const applied = _apply_fetch_items_response(frm, [
			{ item_code: "RM001", allow_alternative_item: 1 },
			{ item_code: "FG001", is_finished_item: 1 },
		]);

		assert.equal(applied, true);
		assert.equal(refreshCount, 1);
		assert.deepEqual(
			frm.doc.items.map((row) => [row.item_code, row.allow_alternative_item || 0]),
			[
				["RM001", 1],
				["FG001", 0],
			]
		);
		assert.deepEqual(apiCalls, [
			"production_entry_app.production_entry_app.api.get_die_tool_counter",
		]);
	} finally {
		global.frappe = originalFrappe;
		global.flt = originalFlt;
		global.__ = originalTranslate;
	}
});

test("app-enabled callbacks run immediately in the native-only flow", () => {
	let runCount = 0;
	_run_when_app_enabled(() => {
		runCount += 1;
	});
	assert.equal(runCount, 1);
});

test("native get_items remains hidden for non-manufacture documents", () => {
	const calls = [];
	const frm = {
		doc: { custom_pea_stock_entry_purpose: "Material Transfer" },
		toggle_display(fieldname, visible) {
			calls.push(["toggle_display", fieldname, visible]);
		},
		set_df_property(fieldname, property, value) {
			calls.push(["set_df_property", fieldname, property, value]);
		},
	};
	_sync_native_get_items_access(frm);

	assert.deepEqual(calls.slice(-3), [
		["toggle_display", "get_items", false],
		["set_df_property", "get_items", "hidden", 1],
		["set_df_property", "get_items", "read_only", 1],
	]);
});

test("native get_items stays hidden for manufacture documents until explicitly shown elsewhere", () => {
	const calls = [];
	const frm = {
		doc: { custom_pea_stock_entry_purpose: "Manufacture" },
		toggle_display(fieldname, visible) {
			calls.push(["toggle_display", fieldname, visible]);
		},
		set_df_property(fieldname, property, value) {
			calls.push(["set_df_property", fieldname, property, value]);
		},
	};
	_sync_native_get_items_access(frm);

	assert.deepEqual(calls.slice(-3), [
		["toggle_display", "get_items", false],
		["set_df_property", "get_items", "hidden", 1],
		["set_df_property", "get_items", "read_only", 1],
	]);
});
