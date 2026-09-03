const test = require("node:test");
const assert = require("node:assert/strict");

const {
	_normalize_purpose,
	_is_manufacture_doc,
	_is_joint_doc,
	_is_production_doc,
	_did_leave_manufacture,
	_clear_manufacture_data_on_leave,
	_apply_native_manufacture_visibility,
	_hide_native_get_items,
	_apply_shift_detail_updates,
	_handle_shift_change,
	_sync_rework_source_warehouse,
	_schedule_rework_source_warehouse,
	_default_rework_item_source,
	_apply_fetch_items_response,
	_sync_joint_stock_entry_type,
	_initialize_total_strokes_default_state,
	_default_total_strokes_from_fg,
	_get_rejection_qty_for_visibility,
	_sync_rework_mode_from_stock_entry_type,
	_schedule_rework_workstation_default,
	REWORK_FIELDS,
	MANUFACTURE_FIELDS,
	PEA_MANUFACTURE_FIELDS,
	JOINT_ONLY_PEA_FIELDS,
	MANUFACTURE_SECTIONS,
	ALWAYS_HIDDEN_FIELDS,
	ALWAYS_HIDDEN_SECTIONS,
	MANUFACTURE_CLEAR_TABLE_FIELDS,
} = require("../../production_entry_app/public/js/stock_entry.js");

test("selecting a marked Rework Stock Entry Type shows fields under ambiguous canonical setup", () => {
	const originalFrappe = global.frappe;
	let callCount = 0;
	global.frappe = {
		call(options) {
			callCount += 1;
			assert.deepEqual(options.args, {
				required: 0,
				stock_entry_type: "Rework Material Transfer",
			});
			options.callback({ message: "Rework Material Transfer" });
		},
	};
	const visibility = [];
	const refreshed = [];
	const frm = {
		doc: { stock_entry_type: "Rework Material Transfer" },
		toggle_display(fieldnames, visible) {
			visibility.push([fieldnames, visible]);
		},
		refresh_fields() {},
		refresh_field(fieldname) {
			refreshed.push(fieldname);
		},
	};

	try {
		_sync_rework_mode_from_stock_entry_type(frm);
		_sync_rework_mode_from_stock_entry_type(frm);

		assert.equal(frm.doc.__pea_rework_stock_entry_type, "Rework Material Transfer");
		assert.equal(callCount, 1);
		assert.deepEqual(visibility, [
			[REWORK_FIELDS, true],
			[REWORK_FIELDS, true],
		]);
		assert.deepEqual(refreshed, ["custom_pea_shift", "custom_pea_shift"]);
	} finally {
		global.frappe = originalFrappe;
	}
});

test("blank new Stock Entry hides Rework fields when passive discovery finds no configuration", () => {
	const originalFrappe = global.frappe;
	let errorShown = false;
	const methods = [];
	global.frappe = {
		call(options) {
			methods.push(options.method);
			assert.deepEqual(options.args, { required: 0, stock_entry_type: "" });
			options.callback({ message: "" });
		},
		msgprint() {
			errorShown = true;
		},
	};
	const visibility = [];
	const frm = {
		doc: {
			stock_entry_type: "",
			company: "Test Company",
			branch: "Test Branch",
		},
		toggle_display(fieldnames, visible) {
			visibility.push([fieldnames, visible]);
		},
		refresh_fields() {},
		refresh_field() {},
	};

	try {
		_sync_rework_mode_from_stock_entry_type(frm);

		assert.equal(frm.doc.__pea_rework_stock_entry_type, "");
		assert.deepEqual(visibility, [[REWORK_FIELDS, false]]);
		assert.equal(errorShown, false);
		assert.deepEqual(methods, [
			"production_entry_app.production_entry_app.api.get_rework_stock_entry_type",
		]);
	} finally {
		global.frappe = originalFrappe;
	}
});

test("selecting Rework after cached ordinary type performs a selected-type lookup", () => {
	const originalFrappe = global.frappe;
	const requests = [];
	global.frappe = {
		call(options) {
			requests.push(options);
		},
	};
	const visibility = [];
	const frm = {
		doc: { stock_entry_type: "Material Transfer" },
		toggle_display(_fieldnames, visible) {
			visibility.push(visible);
		},
		refresh_fields() {},
		refresh_field() {},
	};

	try {
		_sync_rework_mode_from_stock_entry_type(frm);
		requests[0].callback({ message: "" });
		frm.doc.stock_entry_type = "Rework Material Transfer";
		_sync_rework_mode_from_stock_entry_type(frm);

		assert.equal(requests.length, 2);
		assert.deepEqual(requests[1].args, {
			required: 0,
			stock_entry_type: "Rework Material Transfer",
		});
		requests[1].callback({ message: "Rework Material Transfer" });
		assert.deepEqual(visibility, [false, true]);
	} finally {
		global.frappe = originalFrappe;
	}
});

test("selecting Shift on rework keeps it context-only", () => {
	const originalFrappe = global.frappe;
	let callCount = 0;
	global.frappe = {
		call() {
			callCount += 1;
		},
	};
	const frm = {
		doc: {
			stock_entry_type: "Rework Material Transfer",
			__pea_rework_stock_entry_type: "Rework Material Transfer",
			custom_pea_shift: "SHIFT-REWORK",
			company: "Original Company",
			branch: "Original Branch",
			from_warehouse: "Rejection Warehouse",
			to_warehouse: "Good Warehouse",
		},
	};

	try {
		_handle_shift_change(frm);
		assert.equal(callCount, 0);
		assert.equal(frm.doc.company, "Original Company");
		assert.equal(frm.doc.branch, "Original Branch");
		assert.equal(frm.doc.from_warehouse, "Rejection Warehouse");
		assert.equal(frm.doc.to_warehouse, "Good Warehouse");
	} finally {
		global.frappe = originalFrappe;
	}
});

test("configured rejection warehouse defaults blank rework header and item sources", async () => {
	const originalFrappe = global.frappe;
	let request;
	const row = { doctype: "Stock Entry Detail", name: "ROW-1", s_warehouse: "" };
	global.frappe = {
		call(options) {
			request = options;
		},
		model: {
			set_value(_doctype, _name, fieldname, value) {
				row[fieldname] = value;
				return Promise.resolve();
			},
		},
	};
	const frm = {
		doc: {
			stock_entry_type: "Rework Material Transfer",
			__pea_rework_stock_entry_type: "Rework Material Transfer",
			company: "Test Company",
			branch: "Test Branch",
			from_warehouse: "",
			items: [row],
		},
		set_value(fieldname, value) {
			this.doc[fieldname] = value;
			return Promise.resolve();
		},
		refresh_field() {},
	};

	try {
		_sync_rework_source_warehouse(frm);
		assert.equal(
			request.method,
			"production_entry_app.production_entry_app.api.get_rework_source_warehouse"
		);
		assert.deepEqual(request.args, { company: "Test Company", branch: "Test Branch" });
		request.callback({ message: "Rejection Warehouse" });
		await new Promise((resolve) => setImmediate(resolve));

		assert.equal(frm.doc.from_warehouse, "Rejection Warehouse");
		assert.equal(row.s_warehouse, "Rejection Warehouse");
	} finally {
		global.frappe = originalFrappe;
	}
});

test("rework source default preserves an explicit source for route validation", async () => {
	const originalFrappe = global.frappe;
	let request;
	const row = {
		doctype: "Stock Entry Detail",
		name: "ROW-1",
		s_warehouse: "Wrong Warehouse",
	};
	global.frappe = {
		call(options) {
			request = options;
		},
		model: { set_value() {} },
	};
	const frm = {
		doc: {
			stock_entry_type: "Rework Material Transfer",
			__pea_rework_stock_entry_type: "Rework Material Transfer",
			company: "Test Company",
			branch: "Test Branch",
			from_warehouse: "Wrong Warehouse",
			items: [row],
		},
		set_value() {
			throw new Error("explicit header source must not be replaced");
		},
		refresh_field() {},
	};

	try {
		_sync_rework_source_warehouse(frm);
		request.callback({ message: "Rejection Warehouse" });
		await new Promise((resolve) => setImmediate(resolve));
		assert.equal(frm.doc.from_warehouse, "Wrong Warehouse");
		assert.equal(row.s_warehouse, "Wrong Warehouse");
	} finally {
		global.frappe = originalFrappe;
	}
});

test("changing branch replaces the prior automatic rework source", async () => {
	const originalFrappe = global.frappe;
	let request;
	const row = {
		doctype: "Stock Entry Detail",
		name: "ROW-1",
		s_warehouse: "Old Rejection Warehouse",
	};
	global.frappe = {
		call(options) {
			request = options;
		},
		model: {
			set_value(_doctype, _name, fieldname, value) {
				row[fieldname] = value;
				return Promise.resolve();
			},
		},
	};
	const frm = {
		__peaReworkSourceWarehouseDefault: "Old Rejection Warehouse",
		doc: {
			stock_entry_type: "Rework Material Transfer",
			__pea_rework_stock_entry_type: "Rework Material Transfer",
			company: "Test Company",
			branch: "New Branch",
			from_warehouse: "Old Rejection Warehouse",
			items: [row],
		},
		set_value(fieldname, value) {
			this.doc[fieldname] = value;
			return Promise.resolve();
		},
		refresh_field() {},
	};

	try {
		_sync_rework_source_warehouse(frm);
		request.callback({ message: "New Rejection Warehouse" });
		await new Promise((resolve) => setImmediate(resolve));
		assert.equal(frm.doc.from_warehouse, "New Rejection Warehouse");
		assert.equal(row.s_warehouse, "New Rejection Warehouse");
	} finally {
		global.frappe = originalFrappe;
	}
});

test("rework source requests debounce rapid type company and branch changes", (t) => {
	t.mock.timers.enable({ apis: ["setTimeout"] });
	const originalFrappe = global.frappe;
	const requests = [];
	global.frappe = {
		call(options) {
			requests.push(options);
		},
	};
	const frm = {
		doc: {
			stock_entry_type: "Rework Material Transfer",
			__pea_rework_stock_entry_type: "Rework Material Transfer",
			company: "Company A",
			branch: "Branch A",
			items: [],
		},
	};

	try {
		_schedule_rework_source_warehouse(frm);
		frm.doc.company = "Company B";
		_schedule_rework_source_warehouse(frm);
		frm.doc.branch = "Branch B";
		_schedule_rework_source_warehouse(frm);

		assert.equal(requests.length, 0);
		t.mock.timers.tick(299);
		assert.equal(requests.length, 0);
		t.mock.timers.tick(1);
		assert.equal(requests.length, 1);
		assert.deepEqual(requests[0].args, { company: "Company B", branch: "Branch B" });
	} finally {
		global.frappe = originalFrappe;
	}
});

test("rework source keeps the latest in-flight response after debouncing", async (t) => {
	t.mock.timers.enable({ apis: ["setTimeout"] });
	const originalFrappe = global.frappe;
	const requests = [];
	global.frappe = {
		call(options) {
			requests.push(options);
		},
		model: { set_value() {} },
	};
	const frm = {
		doc: {
			stock_entry_type: "Rework Material Transfer",
			__pea_rework_stock_entry_type: "Rework Material Transfer",
			company: "Test Company",
			branch: "Branch A",
			from_warehouse: "",
			items: [],
		},
		set_value(fieldname, value) {
			this.doc[fieldname] = value;
			return Promise.resolve();
		},
		refresh_field() {},
	};

	try {
		_schedule_rework_source_warehouse(frm);
		t.mock.timers.tick(300);
		frm.doc.branch = "Branch B";
		_schedule_rework_source_warehouse(frm);
		t.mock.timers.tick(300);
		assert.equal(requests.length, 2);

		requests[1].callback({ message: "Branch B Rejection" });
		requests[0].callback({ message: "Branch A Rejection" });
		await new Promise((resolve) => setImmediate(resolve));
		assert.equal(frm.doc.from_warehouse, "Branch B Rejection");
	} finally {
		global.frappe = originalFrappe;
	}
});

test("new rework item rows inherit the configured header source", async () => {
	const originalFrappe = global.frappe;
	const row = { doctype: "Stock Entry Detail", name: "ROW-1", s_warehouse: "" };
	global.frappe = {
		model: {
			set_value(_doctype, _name, fieldname, value) {
				row[fieldname] = value;
				return Promise.resolve();
			},
		},
	};
	const frm = {
		doc: {
			stock_entry_type: "Rework Material Transfer",
			__pea_rework_stock_entry_type: "Rework Material Transfer",
			from_warehouse: "Rejection Warehouse",
		},
	};

	try {
		await _default_rework_item_source(frm, row);
		assert.equal(row.s_warehouse, "Rejection Warehouse");
	} finally {
		global.frappe = originalFrappe;
	}
});

test("leaving the Rework Stock Entry Type clears all rework-owned fields", () => {
	const originalFrappe = global.frappe;
	global.frappe = {
		call(options) {
			assert.deepEqual(options.args, {
				required: 0,
				stock_entry_type: "Material Transfer",
			});
			options.callback({ message: "" });
		},
	};
	const frm = {
		doc: {
			stock_entry_type: "Material Transfer",
			__pea_rework_stock_entry_type: "Rework Material Transfer",
			__pea_rework_stock_entry_type_checked: "Rework Material Transfer",
			custom_pea_rework_type: "Deburring",
			custom_pea_rework_workstation: "Rework Workstation",
			custom_pea_rework_actual_start: "2026-09-01 08:00:00",
			custom_pea_rework_actual_end: "2026-09-01 09:00:00",
			custom_pea_rework_operators: [{ operator: "Operator One" }],
			custom_pea_rework_cost: 50,
		},
		get_field(fieldname) {
			return {
				df: { fieldtype: fieldname === "custom_pea_rework_cost" ? "Currency" : "Data" },
			};
		},
		clear_table(fieldname) {
			this.doc[fieldname] = [];
		},
		refresh_fields() {},
		toggle_display() {},
		dirty() {},
	};
	frm.__peaReworkTypeTimer = setTimeout(() => {}, 10_000);

	try {
		_sync_rework_mode_from_stock_entry_type(frm, {
			previousStockEntryType: "Rework Material Transfer",
		});

		assert.equal(frm.doc.custom_pea_rework_type, "");
		assert.equal(frm.doc.custom_pea_rework_workstation, "");
		assert.equal(frm.doc.custom_pea_rework_actual_start, "");
		assert.equal(frm.doc.custom_pea_rework_actual_end, "");
		assert.deepEqual(frm.doc.custom_pea_rework_operators, []);
		assert.equal(frm.doc.custom_pea_rework_cost, "");
	} finally {
		global.frappe = originalFrappe;
	}
});

test("Rework Type workstation default is debounced and last selection wins", async (t) => {
	t.mock.timers.enable({ apis: ["setTimeout"] });
	const originalFrappe = global.frappe;
	const requests = new Map();
	global.frappe = {
		db: {
			get_value(_doctype, name) {
				return new Promise((resolve, reject) => requests.set(name, { resolve, reject }));
			},
		},
	};
	const frm = {
		doc: {
			stock_entry_type: "Rework Material Transfer",
			__pea_rework_stock_entry_type: "Rework Material Transfer",
			custom_pea_rework_type: "Deburring",
			custom_pea_rework_workstation: "Old Workstation",
		},
		set_value(fieldname, value) {
			this.doc[fieldname] = value;
		},
	};

	try {
		_schedule_rework_workstation_default(frm);
		assert.equal(requests.size, 0);
		t.mock.timers.tick(300);
		assert.ok(requests.has("Deburring"));

		frm.doc.custom_pea_rework_type = "Polishing";
		_schedule_rework_workstation_default(frm);
		t.mock.timers.tick(300);
		assert.ok(requests.has("Polishing"));

		requests.get("Polishing").resolve({ message: { default_workstation: "Polishing Bench" } });
		await Promise.resolve();
		requests.get("Deburring").resolve({ message: { default_workstation: "Deburring Bench" } });
		await Promise.resolve();

		assert.equal(frm.doc.custom_pea_rework_workstation, "Polishing Bench");
	} finally {
		global.frappe = originalFrappe;
	}
});

test("Stock Entry refresh restores Rework classification stripped by draft save", () => {
	const modulePath = "../../production_entry_app/public/js/stock_entry.js";
	const moduleId = require.resolve(modulePath);
	const cachedModule = require.cache[moduleId];
	const originalFrappe = global.frappe;
	const originalFlt = global.flt;
	const originalWindow = global.window;
	const registered = {};
	let reworkLookupCount = 0;
	const refreshedFields = [];
	delete require.cache[moduleId];
	global.flt = Number;
	global.window = {};
	global.frappe = {
		call(options) {
			const isReworkLookup = options.method.endsWith("get_rework_stock_entry_type");
			if (isReworkLookup) reworkLookupCount += 1;
			const message = isReworkLookup ? "Rework Material Transfer" : "Joint LH RH Repack";
			options.callback({ message });
		},
		ui: {
			form: {
				on(doctype, handlers) {
					registered[doctype] = handlers;
				},
			},
		},
	};
	const frm = {
		doc: {
			stock_entry_type: "Rework Material Transfer",
			custom_pea_stock_entry_purpose: "Material Transfer",
			custom_pea_is_joint_lh_rh: 0,
			custom_pea_rework_type: "",
			custom_pea_rework_operators: [],
			items: [],
		},
		fields_dict: {},
		layout: { sections: [] },
		clear_table(fieldname) {
			this.doc[fieldname] = [];
		},
		dirty() {},
		get_field() {
			return { df: { fieldtype: "Data" } };
		},
		refresh_field() {},
		refresh_fields(fieldnames) {
			refreshedFields.push(...fieldnames);
		},
		set_query() {},
		set_df_property() {},
		set_value(fieldname, value) {
			this.doc[fieldname] = value;
		},
		toggle_display() {},
		toggle_reqd() {},
	};

	try {
		require(modulePath);
		assert.equal(typeof registered["Stock Entry"].custom_pea_rework_type, "function");
		registered["Stock Entry"].onload(frm);
		registered["Stock Entry"].refresh(frm);
		assert.equal(frm.doc.__pea_rework_stock_entry_type, "Rework Material Transfer");
		assert.equal(reworkLookupCount, 1);
		registered["Stock Entry"].refresh(frm);
		assert.equal(reworkLookupCount, 1, "cached refresh must not repeat the lookup");

		delete frm.doc.__pea_rework_stock_entry_type;
		delete frm.doc.__pea_rework_stock_entry_type_checked;
		registered["Stock Entry"].refresh(frm);
		assert.equal(frm.doc.__pea_rework_stock_entry_type, "Rework Material Transfer");
		assert.equal(reworkLookupCount, 1, "post-save refresh must reuse the form cache");
		assert.ok(refreshedFields.includes("custom_pea_rework_details_section"));

		frm.__pea_prev_stock_entry_type = "Rework Material Transfer";
		frm.doc.stock_entry_type = "Material Transfer";
		frm.doc.custom_pea_rework_type = "Deburring";
		registered["Stock Entry"].stock_entry_type(frm);
		assert.equal(frm.doc.custom_pea_rework_type, "");

		registered["Stock Entry"].custom_pea_rework_type(frm);
	} finally {
		if (cachedModule) {
			require.cache[moduleId] = cachedModule;
		} else {
			delete require.cache[moduleId];
		}
		global.frappe = originalFrappe;
		global.flt = originalFlt;
		global.window = originalWindow;
	}
});

test("same-type Rework classification refreshes share one in-flight lookup", () => {
	const originalFrappe = global.frappe;
	const requests = [];
	global.frappe = {
		call(options) {
			requests.push(options);
		},
	};
	const frm = {
		doc: { stock_entry_type: "Rework A" },
		refresh_fields() {},
		refresh_field() {},
		toggle_display() {},
	};

	try {
		_sync_rework_mode_from_stock_entry_type(frm);
		_sync_rework_mode_from_stock_entry_type(frm);
		assert.equal(requests.length, 1);

		requests[0].callback({ message: "Rework A" });
		frm.doc = { stock_entry_type: "Rework A" };
		_sync_rework_mode_from_stock_entry_type(frm);
		assert.equal(requests.length, 1, "resolved form cache must survive doc replacement");
		assert.equal(frm.doc.__pea_rework_stock_entry_type, "Rework A");
	} finally {
		global.frappe = originalFrappe;
	}
});

test("Rework classification cache is keyed by type and failed lookups can retry", () => {
	const originalFrappe = global.frappe;
	const originalTranslate = global.__;
	const requests = [];
	const messages = [];
	global.__ = (text) => text;
	global.frappe = {
		call(options) {
			requests.push(options);
		},
		msgprint(message) {
			messages.push(message);
		},
	};
	const frm = {
		doc: { stock_entry_type: "Rework A" },
		refresh_fields() {},
		refresh_field() {},
		toggle_display() {},
	};

	try {
		_sync_rework_mode_from_stock_entry_type(frm);
		requests[0].callback({ message: "Rework A" });

		frm.doc = { stock_entry_type: "Ordinary B" };
		_sync_rework_mode_from_stock_entry_type(frm);
		assert.equal(requests.length, 2, "a different type requires its own lookup");
		frm.doc = { stock_entry_type: "Ordinary C" };
		_sync_rework_mode_from_stock_entry_type(frm);
		assert.equal(requests.length, 3, "a newer selected type must start its own lookup");
		requests[1].error(new Error("stale failure"));
		assert.deepEqual(messages, []);
		requests[2].error(new Error("temporary failure"));
		_sync_rework_mode_from_stock_entry_type(frm);
		assert.equal(requests.length, 4, "failed in-flight state must be cleared for retry");
		requests[3].callback({ message: "" });
		assert.equal(frm.doc.__pea_rework_stock_entry_type, "");
		assert.equal(messages.length, 1);
	} finally {
		global.frappe = originalFrappe;
		global.__ = originalTranslate;
	}
});

test("cached ordinary Stock Entry Type applies without another server call", () => {
	const originalFrappe = global.frappe;
	let callCount = 0;
	global.frappe = { call: () => (callCount += 1) };
	const visibility = [];
	const frm = {
		doc: {
			stock_entry_type: "Material Transfer",
			__pea_rework_stock_entry_type: "",
			__pea_rework_stock_entry_type_checked: "Material Transfer",
		},
		refresh_fields() {},
		toggle_display(_fieldnames, visible) {
			visibility.push(visible);
		},
	};

	try {
		_sync_rework_mode_from_stock_entry_type(frm);
		assert.equal(callCount, 0);
		assert.deepEqual(visibility, [false]);
	} finally {
		global.frappe = originalFrappe;
	}
});

test("stale Rework Stock Entry Type lookup responses do not change visibility", () => {
	const originalFrappe = global.frappe;
	const callbacks = [];
	global.frappe = {
		call(options) {
			callbacks.push(options.callback);
		},
	};
	const visibility = [];
	const frm = {
		doc: { stock_entry_type: "Material Transfer" },
		refresh_fields() {},
		toggle_display(_fieldnames, visible) {
			visibility.push(visible);
		},
	};

	try {
		_sync_rework_mode_from_stock_entry_type(frm);
		frm.doc.stock_entry_type = "Rework Material Transfer";
		_sync_rework_mode_from_stock_entry_type(frm);
		callbacks[0]({ message: "Rework Material Transfer" });
		callbacks[1]({ message: "Rework Material Transfer" });

		assert.deepEqual(visibility, [true]);
	} finally {
		global.frappe = originalFrappe;
	}
});

test("latest ordinary lookup clears Rework data after an intermediate response is stale", () => {
	const originalFrappe = global.frappe;
	const callbacks = [];
	global.frappe = {
		call(options) {
			callbacks.push(options.callback);
		},
	};
	let clearCount = 0;
	let dirtyCount = 0;
	const frm = {
		doc: {
			stock_entry_type: "Ordinary B",
			__pea_rework_stock_entry_type: "Rework A",
			__pea_rework_stock_entry_type_checked: "Rework A",
			custom_pea_rework_type: "Deburring",
			custom_pea_rework_workstation: "Rework Workstation",
			custom_pea_rework_actual_start: "2026-09-01 08:00:00",
			custom_pea_rework_actual_end: "2026-09-01 09:00:00",
			custom_pea_rework_operators: [{ operator: "Operator One" }],
			custom_pea_rework_cost: 50,
		},
		get_field(fieldname) {
			return {
				df: { fieldtype: fieldname === "custom_pea_rework_cost" ? "Currency" : "Data" },
			};
		},
		clear_table(fieldname) {
			clearCount += 1;
			this.doc[fieldname] = [];
		},
		dirty() {
			dirtyCount += 1;
		},
		refresh_fields() {},
		refresh_field() {},
		toggle_display() {},
	};

	try {
		_sync_rework_mode_from_stock_entry_type(frm, { previousStockEntryType: "Rework A" });
		frm.doc.stock_entry_type = "Ordinary C";
		_sync_rework_mode_from_stock_entry_type(frm, { previousStockEntryType: "Ordinary B" });

		callbacks[0]({ message: "" });
		assert.equal(frm.doc.custom_pea_rework_type, "Deburring");
		callbacks[1]({ message: "" });

		assert.equal(frm.doc.custom_pea_rework_type, "");
		assert.deepEqual(frm.doc.custom_pea_rework_operators, []);
		assert.equal(clearCount, 1);
		assert.equal(dirtyCount, 1);
	} finally {
		global.frappe = originalFrappe;
	}
});

test("changing between marked Rework Stock Entry Types preserves Rework data", () => {
	const originalFrappe = global.frappe;
	global.frappe = {
		call(options) {
			options.callback({ message: "Rework B" });
		},
	};
	const visibility = [];
	const frm = {
		doc: {
			stock_entry_type: "Rework B",
			__pea_rework_stock_entry_type: "Rework A",
			__pea_rework_stock_entry_type_checked: "Rework A",
			custom_pea_rework_type: "Deburring",
			custom_pea_rework_operators: [{ operator: "Operator One" }],
		},
		clear_table() {
			assert.fail("Rework data must not be cleared");
		},
		refresh_fields() {},
		refresh_field() {},
		toggle_display(_fieldnames, visible) {
			visibility.push(visible);
		},
	};

	try {
		_sync_rework_mode_from_stock_entry_type(frm, { previousStockEntryType: "Rework A" });

		assert.equal(frm.doc.custom_pea_rework_type, "Deburring");
		assert.deepEqual(frm.doc.custom_pea_rework_operators, [{ operator: "Operator One" }]);
		assert.deepEqual(visibility, [true]);
		assert.equal(frm.__peaPendingReworkExit, undefined);
	} finally {
		global.frappe = originalFrappe;
	}
});

test("cached Rework Stock Entry Type applies without another server call", () => {
	const originalFrappe = global.frappe;
	let callCount = 0;
	global.frappe = { call: () => (callCount += 1) };
	const visibility = [];
	const frm = {
		doc: {
			stock_entry_type: "Rework Material Transfer",
			__pea_rework_stock_entry_type: "Rework Material Transfer",
		},
		refresh_fields() {},
		toggle_display(_fieldnames, visible) {
			visibility.push(visible);
		},
	};

	try {
		_sync_rework_mode_from_stock_entry_type(frm);
		assert.equal(callCount, 0);
		assert.deepEqual(visibility, [true]);
	} finally {
		global.frappe = originalFrappe;
	}
});

test("current Rework Stock Entry Type lookup failures notify the user", () => {
	const originalFrappe = global.frappe;
	const originalTranslate = global.__;
	const messages = [];
	global.__ = (text) => text;
	global.frappe = {
		call(options) {
			options.error(new Error("lookup unavailable"));
		},
		msgprint(message) {
			messages.push(message);
		},
	};

	try {
		_sync_rework_mode_from_stock_entry_type({
			doc: { stock_entry_type: "Material Transfer" },
		});
		assert.deepEqual(messages, [
			"Failed to identify the Rework Stock Entry Type. lookup unavailable",
		]);
	} finally {
		global.frappe = originalFrappe;
		global.__ = originalTranslate;
	}
});

test("Rework Workstation defaulting cancels a pending debounce", async (t) => {
	t.mock.timers.enable({ apis: ["setTimeout"] });
	const originalFrappe = global.frappe;
	const requestedTypes = [];
	global.frappe = {
		db: {
			get_value(_doctype, name) {
				requestedTypes.push(name);
				return Promise.resolve({ message: { default_workstation: "Bench" } });
			},
		},
	};
	const frm = {
		doc: {
			stock_entry_type: "Rework Material Transfer",
			__pea_rework_stock_entry_type: "Rework Material Transfer",
			custom_pea_rework_type: "Deburring",
		},
		set_value(fieldname, value) {
			this.doc[fieldname] = value;
		},
	};

	try {
		_schedule_rework_workstation_default(frm);
		frm.doc.custom_pea_rework_type = "Polishing";
		_schedule_rework_workstation_default(frm);
		t.mock.timers.tick(300);
		await Promise.resolve();

		assert.deepEqual(requestedTypes, ["Polishing"]);
	} finally {
		global.frappe = originalFrappe;
	}
});

test("Rework Workstation defaulting preserves an override made while loading", async (t) => {
	t.mock.timers.enable({ apis: ["setTimeout"] });
	const originalFrappe = global.frappe;
	let resolveRequest;
	global.frappe = {
		db: {
			get_value() {
				return new Promise((resolve) => (resolveRequest = resolve));
			},
		},
	};
	const frm = {
		doc: {
			stock_entry_type: "Rework Material Transfer",
			__pea_rework_stock_entry_type: "Rework Material Transfer",
			custom_pea_rework_type: "Deburring",
		},
		set_value(fieldname, value) {
			this.doc[fieldname] = value;
		},
	};

	try {
		_schedule_rework_workstation_default(frm);
		t.mock.timers.tick(300);
		frm.doc.custom_pea_rework_workstation = "Manual Bench";
		resolveRequest({ message: { default_workstation: "Default Bench" } });
		await Promise.resolve();

		assert.equal(frm.doc.custom_pea_rework_workstation, "Manual Bench");
	} finally {
		global.frappe = originalFrappe;
	}
});

test("Rework Workstation defaulting returns when Rework Type is empty", () => {
	const originalFrappe = global.frappe;
	global.frappe = { db: { get_value: () => Promise.resolve() } };
	const frm = {
		doc: {
			stock_entry_type: "Rework Material Transfer",
			__pea_rework_stock_entry_type: "Rework Material Transfer",
			custom_pea_rework_type: "",
			custom_pea_rework_workstation: "Stale Bench",
		},
		set_value(fieldname, value) {
			this.doc[fieldname] = value;
		},
	};

	try {
		_schedule_rework_workstation_default(frm);
		assert.equal(frm.doc.custom_pea_rework_workstation, "");
		assert.equal(frm.__peaReworkTypeTimer, undefined);
	} finally {
		global.frappe = originalFrappe;
	}
});

test("current Rework Workstation default failures notify the user", async (t) => {
	t.mock.timers.enable({ apis: ["setTimeout"] });
	const originalFrappe = global.frappe;
	const originalTranslate = global.__;
	const messages = [];
	global.__ = (text) => text;
	global.frappe = {
		db: {
			get_value() {
				return Promise.reject(new Error("network unavailable"));
			},
		},
		msgprint(message) {
			messages.push(message);
		},
	};
	const frm = {
		doc: {
			stock_entry_type: "Rework Material Transfer",
			__pea_rework_stock_entry_type: "Rework Material Transfer",
			custom_pea_rework_type: "Deburring",
			custom_pea_rework_workstation: "",
		},
		set_value(fieldname, value) {
			this.doc[fieldname] = value;
		},
	};

	try {
		_schedule_rework_workstation_default(frm);
		t.mock.timers.tick(300);
		await Promise.resolve();
		await Promise.resolve();

		assert.deepEqual(messages, [
			"Failed to load the default Rework Workstation. network unavailable",
		]);
	} finally {
		global.frappe = originalFrappe;
		global.__ = originalTranslate;
	}
});

test("manufacture strokes follow quantity until the operator edits them", async () => {
	const frm = {
		doc: {
			__islocal: 1,
			custom_pea_stock_entry_purpose: "Manufacture",
			custom_pea_is_joint_lh_rh: 0,
			fg_completed_qty: 100,
			custom_pea_total_strokes: 0,
		},
		set_value(fieldname, value) {
			this.doc[fieldname] = value;
			return Promise.resolve();
		},
	};

	await _default_total_strokes_from_fg(frm);
	assert.equal(frm.doc.custom_pea_total_strokes, 100);

	frm.doc.fg_completed_qty = 120;
	await _default_total_strokes_from_fg(frm);
	assert.equal(frm.doc.custom_pea_total_strokes, 120);

	frm.doc.custom_pea_total_strokes = 40;
	frm.doc.fg_completed_qty = 130;
	await _default_total_strokes_from_fg(frm);
	assert.equal(frm.doc.custom_pea_total_strokes, 40);
});

test("saved manufacture strokes keep following quantity only while auto-derived", async () => {
	const makeForm = (totalStrokes) => ({
		doc: {
			__islocal: 0,
			custom_pea_stock_entry_purpose: "Manufacture",
			custom_pea_is_joint_lh_rh: 0,
			fg_completed_qty: 100,
			custom_pea_total_strokes: totalStrokes,
		},
		set_value(fieldname, value) {
			this.doc[fieldname] = value;
			return Promise.resolve();
		},
	});

	const autoDerived = makeForm(100);
	_initialize_total_strokes_default_state(autoDerived);
	autoDerived.doc.fg_completed_qty = 120;
	await _default_total_strokes_from_fg(autoDerived);
	assert.equal(autoDerived.doc.custom_pea_total_strokes, 120);

	const manuallyEdited = makeForm(40);
	_initialize_total_strokes_default_state(manuallyEdited);
	manuallyEdited.doc.fg_completed_qty = 120;
	await _default_total_strokes_from_fg(manuallyEdited);
	assert.equal(manuallyEdited.doc.custom_pea_total_strokes, 40);
});

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

test("joint LH/RH Repack uses the common production form without native BOM fields", () => {
	const doc = {
		custom_pea_stock_entry_purpose: "Repack",
		custom_pea_is_joint_lh_rh: 1,
	};

	assert.equal(_is_manufacture_doc(doc), false);
	assert.equal(_is_joint_doc(doc), true);
	assert.equal(_is_production_doc(doc), true);
});

test("manufacture visibility targets include key fields and sections", () => {
	assert.ok(MANUFACTURE_FIELDS.includes("custom_pea_fetch_items"));
	assert.ok(!MANUFACTURE_FIELDS.includes("custom_pea_joint_fetch_items"));
	assert.ok(!PEA_MANUFACTURE_FIELDS.includes("custom_pea_joint_fetch_items"));
	assert.deepEqual(JOINT_ONLY_PEA_FIELDS, ["custom_pea_joint_fetch_items"]);
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

test("rejection visibility quantity sums joint sides and uses normal rejection otherwise", () => {
	const originalFlt = global.flt;
	global.flt = Number;
	try {
		assert.equal(
			_get_rejection_qty_for_visibility({
				custom_pea_is_joint_lh_rh: 1,
				custom_pea_lh_rejection_qty: 2,
				custom_pea_rh_rejection_qty: 3,
			}),
			5
		);
		assert.equal(_get_rejection_qty_for_visibility({ custom_pea_rejection_qty: "4" }), 4);
	} finally {
		global.flt = originalFlt;
	}
});

test("leaving joint production restores the user's prior Stock Entry Type", () => {
	const originalFrappe = global.frappe;
	const updates = [];
	global.frappe = {
		call(options) {
			options.callback({ message: "Joint LH RH Repack" });
		},
	};
	const frm = {
		doc: {
			custom_pea_is_joint_lh_rh: 1,
			stock_entry_type: "Shearing",
		},
		set_value(fieldname, value) {
			this.doc[fieldname] = value;
			updates.push([fieldname, value]);
		},
	};

	try {
		_sync_joint_stock_entry_type(frm);
		frm.doc.custom_pea_is_joint_lh_rh = 0;
		_sync_joint_stock_entry_type(frm);

		assert.deepEqual(updates, [
			["stock_entry_type", "Joint LH RH Repack"],
			["stock_entry_type", "Shearing"],
		]);
		assert.equal(frm.__peaStockEntryTypeBeforeJoint, undefined);
	} finally {
		global.frappe = originalFrappe;
	}
});

test("manually selecting a non-joint Stock Entry Type exits joint production and clears joint data", () => {
	const originalFrappe = global.frappe;
	global.frappe = {
		call(options) {
			options.callback({ message: "Joint LH RH Repack" });
		},
	};
	const frm = {
		__peaStockEntryTypeBeforeJoint: "Manufacture",
		fields_dict: {},
		layout: { sections: [] },
		doc: {
			custom_pea_is_joint_lh_rh: 1,
			stock_entry_type: "Manufacture",
			custom_pea_shift: "SHIFT-001",
			custom_pea_lh_bom: "BOM-LH",
			custom_pea_lh_gross_qty: 40,
			custom_pea_lh_rejection_qty: 1,
			custom_pea_rh_bom: "BOM-RH",
			custom_pea_rh_gross_qty: 41,
			custom_pea_rh_rejection_qty: 2,
			custom_pea_total_strokes: 41,
			custom_pea_die_tool_item: "DIE-001",
			custom_pea_total_rm_consumption: 49.125,
			custom_pea_rejection_breakup: [{ output_side: "LH", qty: 1 }],
			items: [{ item_code: "RM-001" }],
		},
		set_value(fieldname, value) {
			this.doc[fieldname] = value;
		},
		clear_table(fieldname) {
			this.doc[fieldname] = [];
		},
		get_field() {
			return { df: { fieldtype: "Data" } };
		},
		refresh_fields() {},
		refresh_field() {},
		toggle_display() {},
		toggle_reqd() {},
		dirty() {},
	};

	try {
		_sync_joint_stock_entry_type(frm, { source: "stock_entry_type" });

		assert.equal(frm.doc.stock_entry_type, "Manufacture");
		assert.equal(frm.doc.custom_pea_is_joint_lh_rh, 0);
		assert.equal(frm.doc.custom_pea_shift, "SHIFT-001");
		assert.equal(frm.doc.custom_pea_lh_bom, "");
		assert.equal(frm.doc.custom_pea_rh_bom, "");
		assert.equal(frm.doc.custom_pea_total_strokes, "");
		assert.equal(frm.doc.custom_pea_die_tool_item, "");
		assert.equal(frm.doc.custom_pea_total_rm_consumption, "");
		assert.deepEqual(frm.doc.custom_pea_rejection_breakup, []);
		assert.deepEqual(frm.doc.items, []);
	} finally {
		global.frappe = originalFrappe;
	}
});

test("manually selecting the joint Stock Entry Type enters joint production and clears normal data", () => {
	const originalFrappe = global.frappe;
	global.frappe = {
		call(options) {
			options.callback({ message: "Joint LH RH Repack" });
		},
	};
	const frm = {
		fields_dict: {},
		layout: { sections: [] },
		doc: {
			custom_pea_is_joint_lh_rh: 0,
			stock_entry_type: "Joint LH RH Repack",
			custom_pea_stock_entry_purpose: "Repack",
			custom_pea_shift: "SHIFT-001",
			from_bom: 1,
			bom_no: "BOM-NORMAL",
			use_multi_level_bom: 1,
			fg_completed_qty: 100,
			custom_pea_rejection_qty: 2,
			custom_pea_total_strokes: 50,
			custom_pea_die_tool_item: "DIE-NORMAL",
			custom_pea_rejection_breakup: [{ qty: 2 }],
			items: [{ item_code: "FG-NORMAL", is_finished_item: 1 }],
		},
		get_field(fieldname) {
			return {
				df: {
					fieldtype: ["from_bom", "use_multi_level_bom"].includes(fieldname)
						? "Check"
						: "Data",
				},
			};
		},
		clear_table(fieldname) {
			this.doc[fieldname] = [];
		},
		refresh_fields() {},
		refresh_field() {},
		toggle_display() {},
		toggle_reqd() {},
		dirty() {},
	};

	try {
		_sync_joint_stock_entry_type(frm, {
			source: "stock_entry_type",
			previousStockEntryType: "Manufacture",
		});

		assert.equal(frm.doc.stock_entry_type, "Joint LH RH Repack");
		assert.equal(frm.doc.custom_pea_is_joint_lh_rh, 1);
		assert.equal(frm.__peaStockEntryTypeBeforeJoint, "Manufacture");
		assert.equal(frm.doc.custom_pea_shift, "SHIFT-001");
		assert.equal(frm.doc.from_bom, 0);
		assert.equal(frm.doc.bom_no, "");
		assert.equal(frm.doc.use_multi_level_bom, 0);
		assert.equal(frm.doc.fg_completed_qty, "");
		assert.equal(frm.doc.custom_pea_rejection_qty, "");
		assert.equal(frm.doc.custom_pea_total_strokes, "");
		assert.equal(frm.doc.custom_pea_die_tool_item, "");
		assert.deepEqual(frm.doc.custom_pea_rejection_breakup, []);
		assert.deepEqual(frm.doc.items, []);
	} finally {
		global.frappe = originalFrappe;
	}
});

test("joint type lookup defers manufacture cleanup so common Shift context survives", () => {
	const originalFrappe = global.frappe;
	const originalTranslate = global.__;
	let jointTypeResponse;
	global.__ = (text) => text;
	global.frappe = {
		call(options) {
			jointTypeResponse = options.callback;
		},
	};
	const frm = {
		__pea_prev_stock_entry_purpose: "Manufacture",
		fields_dict: {},
		layout: { sections: [] },
		doc: {
			custom_pea_is_joint_lh_rh: 0,
			stock_entry_type: "Joint LH RH Repack",
			custom_pea_stock_entry_purpose: "Repack",
			custom_pea_shift: "SHIFT-001",
			custom_pea_actual_start_date: "2026-08-28 08:00:00",
			custom_pea_workstation: "PRESS-001",
			from_bom: 1,
			bom_no: "BOM-NORMAL",
			items: [{ item_code: "FG-NORMAL", is_finished_item: 1 }],
		},
		get_field(fieldname) {
			return { df: { fieldtype: fieldname === "from_bom" ? "Check" : "Data" } };
		},
		clear_table(fieldname) {
			this.doc[fieldname] = [];
		},
		refresh_fields() {},
		refresh_field() {},
		toggle_display() {},
		toggle_reqd() {},
		dirty() {},
	};

	try {
		_sync_joint_stock_entry_type(frm, {
			source: "stock_entry_type",
			previousStockEntryType: "Manufacture",
		});
		_clear_manufacture_data_on_leave(frm);

		assert.equal(frm.doc.custom_pea_shift, "SHIFT-001");
		assert.equal(frm.doc.bom_no, "BOM-NORMAL");
		assert.equal(frm.__peaDeferredManufactureCleanup, true);

		jointTypeResponse({ message: "Joint LH RH Repack" });

		assert.equal(frm.doc.custom_pea_is_joint_lh_rh, 1);
		assert.equal(frm.doc.custom_pea_shift, "SHIFT-001");
		assert.equal(frm.doc.custom_pea_actual_start_date, "2026-08-28 08:00:00");
		assert.equal(frm.doc.custom_pea_workstation, "PRESS-001");
		assert.equal(frm.doc.bom_no, "");
		assert.equal(frm.__peaDeferredManufactureCleanup, undefined);
	} finally {
		global.frappe = originalFrappe;
		global.__ = originalTranslate;
	}
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

test("stock entry PEA sections are metadata-gated to manufacture or joint production", () => {
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
		assert.match(dependsOn, /custom_pea_is_joint_lh_rh/);
	}
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

	await _apply_shift_detail_updates(
		frm,
		{
			company: "Test Company",
			branch: "",
			custom_pea_planned_start_date: null,
			custom_pea_planned_end_date: "2026-02-22 16:00:00",
			from_warehouse: undefined,
		},
		{ clearWarehouses: true }
	);

	assert.deepEqual(updates, [
		["company", "Test Company"],
		["branch", ""],
		["custom_pea_planned_start_date", null],
		["custom_pea_planned_end_date", "2026-02-22 16:00:00"],
		["from_warehouse", undefined],
	]);
});

test("shift selection preserves Work Order warehouses while applying its dates and branch", async () => {
	const updates = {};
	const frm = {
		doc: { work_order: "WO-1" },
		fields_dict: {
			branch: {},
			custom_pea_planned_start_date: {},
			from_warehouse: {},
			to_warehouse: {},
		},
		async set_value(fieldname, value) {
			updates[fieldname] = value;
		},
	};
	await _apply_shift_detail_updates(frm, {
		branch: "BRANCH-1",
		custom_pea_planned_start_date: "2026-08-30 08:00:00",
		from_warehouse: "SHIFT-WIP",
		to_warehouse: "SHIFT-WIP",
	});
	assert.deepEqual(updates, {
		branch: "BRANCH-1",
		custom_pea_planned_start_date: "2026-08-30 08:00:00",
	});
});

test("Shift selection without warehouse defaults preserves manually entered headers", async () => {
	for (const emptyValue of [null, undefined, ""]) {
		const frm = {
			doc: { from_warehouse: "Manual WIP", to_warehouse: "Manual FG" },
			fields_dict: { branch: {}, from_warehouse: {}, to_warehouse: {} },
			async set_value(fieldname, value) {
				this.doc[fieldname] = value;
			},
		};
		await _apply_shift_detail_updates(frm, {
			branch: "BRANCH-1",
			from_warehouse: emptyValue,
			to_warehouse: emptyValue,
		});
		assert.deepEqual(frm.doc, {
			branch: "BRANCH-1",
			from_warehouse: "Manual WIP",
			to_warehouse: "Manual FG",
		});
	}
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
		{ isCurrentRequest: () => current }
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
	_hide_native_get_items(frm);

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
	_hide_native_get_items(frm);

	assert.deepEqual(calls.slice(-3), [
		["toggle_display", "get_items", false],
		["set_df_property", "get_items", "hidden", 1],
		["set_df_property", "get_items", "read_only", 1],
	]);
});
