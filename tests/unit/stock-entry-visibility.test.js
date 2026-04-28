const test = require("node:test");
const assert = require("node:assert/strict");

const {
	_normalize_purpose,
	_is_manufacture_doc,
	_did_leave_manufacture,
	_should_override_fg_completed_qty,
	_run_when_app_enabled,
	_sync_native_get_items_access,
	_get_shift_detail_updates,
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

test("fg completed qty override is disabled until required-role access is explicitly allowed", () => {
	const originalWindow = global.window;
	global.window = {
		production_entry_app: {
			access_control: {
				get_cached_access_control_state() {
					return null;
				},
			},
		},
	};

	try {
		assert.equal(_should_override_fg_completed_qty(), false);

		global.window.production_entry_app.access_control.get_cached_access_control_state =
			function () {
				return { enabled: false };
			};
		assert.equal(_should_override_fg_completed_qty(), false);

		global.window.production_entry_app.access_control.get_cached_access_control_state =
			function () {
				return { enabled: true };
			};
		assert.equal(_should_override_fg_completed_qty(), true);
	} finally {
		global.window = originalWindow;
	}
});

test("shift detail updates clear present empty values instead of leaving stale fields", () => {
	const updates = [];
	const frm = {
		set_value(fieldname, value) {
			updates.push([fieldname, value]);
			return Promise.resolve();
		},
	};

	const result = _get_shift_detail_updates(frm, {
		company: "Test Company",
		branch: "",
		custom_pea_planned_start_date: null,
		custom_pea_planned_end_date: "2026-02-22 16:00:00",
		from_warehouse: undefined,
	});

	assert.equal(result.length, 5);
	assert.deepEqual(updates, [
		["company", "Test Company"],
		["branch", ""],
		["custom_pea_planned_start_date", null],
		["custom_pea_planned_end_date", "2026-02-22 16:00:00"],
		["from_warehouse", undefined],
	]);
});

test("app-enabled callbacks stay fail-closed when access lookup rejects", async () => {
	const originalWindow = global.window;
	let rejectReady;
	const readyPromise = new Promise((_resolve, reject) => {
		rejectReady = reject;
	});
	let runCount = 0;
	global.window = {
		production_entry_app: {
			access_control: {
				get_cached_access_control_state() {
					return null;
				},
				when_ready() {
					return readyPromise;
				},
			},
		},
	};

	try {
		_run_when_app_enabled(() => {
			runCount += 1;
		});
		rejectReady(new Error("ACL API failed"));
		await readyPromise.catch(() => {});
		await Promise.resolve();
		assert.equal(runCount, 0);
	} finally {
		global.window = originalWindow;
	}
});

test("native get_items stays hidden while required-role access is unresolved and only reappears for denied users", async () => {
	const originalWindow = global.window;
	let resolveReady;
	const readyPromise = new Promise((resolve) => {
		resolveReady = resolve;
	});
	const calls = [];
	const frm = {
		toggle_display(fieldname, visible) {
			calls.push(["toggle_display", fieldname, visible]);
		},
		set_df_property(fieldname, property, value) {
			calls.push(["set_df_property", fieldname, property, value]);
		},
	};
	global.window = {
		production_entry_app: {
			access_control: {
				get_cached_access_control_state() {
					return null;
				},
				when_ready() {
					return readyPromise;
				},
			},
		},
	};

	try {
		_sync_native_get_items_access(frm);
		assert.deepEqual(calls.slice(0, 3), [
			["toggle_display", "get_items", false],
			["set_df_property", "get_items", "hidden", 1],
			["set_df_property", "get_items", "read_only", 1],
		]);

		resolveReady({ enabled: false });
		await readyPromise;
		await Promise.resolve();
		assert.deepEqual(calls.slice(-3), [
			["toggle_display", "get_items", true],
			["set_df_property", "get_items", "hidden", 0],
			["set_df_property", "get_items", "read_only", 0],
		]);
	} finally {
		global.window = originalWindow;
	}
});

test("native get_items falls back to visible when access lookup rejects", async () => {
	const originalWindow = global.window;
	let rejectReady;
	const readyPromise = new Promise((_resolve, reject) => {
		rejectReady = reject;
	});
	const calls = [];
	const frm = {
		toggle_display(fieldname, visible) {
			calls.push(["toggle_display", fieldname, visible]);
		},
		set_df_property(fieldname, property, value) {
			calls.push(["set_df_property", fieldname, property, value]);
		},
	};
	global.window = {
		production_entry_app: {
			access_control: {
				get_cached_access_control_state() {
					return null;
				},
				when_ready() {
					return readyPromise;
				},
			},
		},
	};

	try {
		_sync_native_get_items_access(frm);
		rejectReady(new Error("ACL API failed"));
		await readyPromise.catch(() => {});
		await Promise.resolve();
		assert.deepEqual(calls.slice(-3), [
			["toggle_display", "get_items", true],
			["set_df_property", "get_items", "hidden", 0],
			["set_df_property", "get_items", "read_only", 0],
		]);
	} finally {
		global.window = originalWindow;
	}
});
