// Copyright (c) 2026, Gurudatt Kulkarni and contributors
// For license information, please see license.txt

/* global erpnext */

const NATIVE_MANUFACTURE_FIELDS = [
	"from_bom",
	"bom_no",
	"use_multi_level_bom",
	"fg_completed_qty",
];

const PEA_MANUFACTURE_FIELDS = [
	"custom_pea_rejection_qty",
	"custom_pea_ok_qty",
	"custom_pea_rework_qty",
	"custom_pea_fetch_items",
	"custom_pea_rejection_breakup",
	"custom_pea_shift",
	"custom_pea_planned_start_date",
	"custom_pea_planned_end_date",
	"custom_pea_operation_details_col_break",
	"custom_pea_actual_start_date_input",
	"custom_pea_actual_start_time_input",
	"custom_pea_actual_start_date",
	"custom_pea_actual_end_date_input",
	"custom_pea_actual_end_time_input",
	"custom_pea_actual_end_date",
	"custom_pea_workstation",
	"custom_pea_standard_spm",
	"custom_pea_workstation_operator_col_break",
	"custom_pea_operator",
	"custom_pea_unplanned_losses",
	"custom_pea_actual_duration_mins",
	"custom_pea_production_time_mins",
	"custom_pea_actual_spm",
	"custom_pea_cycle_time_sec",
	"custom_pea_metrics_col_break",
	"custom_pea_operator_efficiency_pct",
	"custom_pea_metrics_note",
	"custom_pea_die_tool_utilization_pct",
	"custom_pea_die_tool_maintenance_due",
];

const MANUFACTURE_FIELDS = [...NATIVE_MANUFACTURE_FIELDS, ...PEA_MANUFACTURE_FIELDS];

const NATIVE_MANUFACTURE_SECTIONS = ["bom_info_section"];

const PEA_MANUFACTURE_SECTIONS = [
	"custom_pea_operation_details_section",
	"custom_pea_workstation_operator_section",
	"custom_pea_unplanned_losses_section",
	"custom_pea_metrics_section",
];

const MANUFACTURE_SECTIONS = [...NATIVE_MANUFACTURE_SECTIONS, ...PEA_MANUFACTURE_SECTIONS];

const ALWAYS_HIDDEN_FIELDS = ["process_loss_percentage", "process_loss_qty"];
const ALWAYS_HIDDEN_SECTIONS = ["section_break_7qsm"];
const MANUFACTURE_CLEAR_TABLE_FIELDS = [
	"custom_pea_unplanned_losses",
	"custom_pea_rejection_breakup",
	"items",
];
let _dieToolRequestId = 0;
let _shiftDetailsRequestId = 0;

function _get_access_control_api() {
	return window.production_entry_app?.access_control || null;
}

function _ignore_access_control_lookup_error() {
	return false;
}

function _run_when_app_enabled(fn) {
	const accessControl = _get_access_control_api();
	if (!accessControl) {
		fn();
		return;
	}
	const cached = accessControl.get_cached_access_control_state?.();
	if (cached && cached.enabled === false) {
		return;
	}
	if (cached && cached.enabled === true) {
		fn();
		return;
	}
	const ready = accessControl.when_ready?.();
	if (ready?.then) {
		void ready
			.then((state) => {
				if (state?.enabled) {
					fn();
				}
			})
			.catch(_ignore_access_control_lookup_error);
	}
}

function _apply_custom_field_visibility(frm) {
	window.production_entry_app?.custom_field_visibility?.apply_field_visibility?.(
		frm,
		"Stock Entry"
	);
}

function _should_override_fg_completed_qty() {
	const accessControl = _get_access_control_api();
	const state = accessControl?.get_cached_access_control_state?.();
	return state?.enabled === true;
}

function _hide_native_get_items(frm) {
	frm.toggle_display("get_items", false);
	frm.set_df_property("get_items", "hidden", 1);
	frm.set_df_property("get_items", "read_only", 1);
}

function _show_native_get_items(frm) {
	frm.toggle_display("get_items", true);
	frm.set_df_property("get_items", "hidden", 0);
	frm.set_df_property("get_items", "read_only", 0);
}

function _sync_native_get_items_access(frm) {
	const accessControl = _get_access_control_api();
	_hide_native_get_items(frm);
	if (!_is_manufacture_doc(frm.doc)) {
		return;
	}
	if (!accessControl) {
		_show_native_get_items(frm);
		return;
	}
	const cached = accessControl.get_cached_access_control_state?.();
	if (cached?.enabled === false) {
		_show_native_get_items(frm);
		return;
	}
	if (cached?.enabled === true) {
		return;
	}
	const ready = accessControl.when_ready?.();
	if (ready?.then) {
		void ready
			.then((state) => {
				if (state?.enabled === false && _is_manufacture_doc(frm.doc)) {
					_show_native_get_items(frm);
					return;
				}
				_hide_native_get_items(frm);
			})
			.catch(() => {
				if (_is_manufacture_doc(frm.doc)) {
					_show_native_get_items(frm);
				}
			});
	}
}

// Suppress ERPNext's auto-populate on fg_completed_qty change for Manufacture
// entries so the user can set both Qty to Manufacture and Rejection Qty before
// explicitly clicking "Fetch Items".
// Depends on ERPNext v15/v16 `erpnext.stock.StockEntry.prototype.fg_completed_qty`
// from erpnext/stock/doctype/stock_entry/stock_entry.js. Keep the original
// method fallback so ERPNext changes fail visibly instead of replacing behavior globally.
if (typeof window !== "undefined" && window.erpnext && erpnext.stock && erpnext.stock.StockEntry) {
	const originalFgCompletedQty = erpnext.stock.StockEntry.prototype.fg_completed_qty;
	if (typeof originalFgCompletedQty !== "function") {
		// ERPNext changed the client controller surface; leave native behavior untouched.
	} else {
		erpnext.stock.StockEntry.prototype.fg_completed_qty = function () {
			if (!_should_override_fg_completed_qty()) {
				return originalFgCompletedQty.call(this);
			}
			if (_is_manufacture_doc(this.frm.doc) && this.frm.doc.from_bom) {
				// Skip the standard get_items() call for Manufacture; handled by Fetch Items.
				return;
			}
			// For all other purposes, keep the standard behaviour.
			return originalFgCompletedQty.call(this);
		};
	}
}

if (typeof frappe !== "undefined" && frappe.ui && frappe.ui.form) {
	frappe.ui.form.on("Stock Entry", {
		onload(frm) {
			_set_prev_purpose(frm);
			_sync_native_get_items_access(frm);
			_apply_native_manufacture_visibility(frm);
			_apply_custom_field_visibility(frm);
			_run_when_app_enabled(() => {
				_apply_manufacture_visibility(frm);
			});
		},
		refresh(frm) {
			_set_prev_purpose(frm);
			_sync_native_get_items_access(frm);
			_apply_native_manufacture_visibility(frm);
			_apply_custom_field_visibility(frm);
			_run_when_app_enabled(() => {
				// Set filter to show shifts that can accept post-facto entries.
				frm.set_query("custom_pea_shift", function () {
					return {
						filters: [["Shift", "status", "in", ["Running", "Completed"]]],
					};
				});

				_ensure_use_multi_level_bom_unchecked(frm);
				_apply_manufacture_visibility(frm);
				_hide_standard_get_items(frm);
				_sync_stock_entry_helper_fields(frm);
				_setup_stock_entry_quick_entry(frm);
			});
		},
		stock_entry_type(frm) {
			_sync_native_get_items_access(frm);
			_apply_native_manufacture_visibility(frm);
			_run_when_app_enabled(() => {
				// custom_pea_stock_entry_purpose is fetched via fetch_from and will re-trigger visibility.
				_apply_manufacture_visibility(frm);
				_sync_stock_entry_helper_fields(frm);
				_setup_stock_entry_quick_entry(frm);
			});
		},
		custom_pea_stock_entry_purpose(frm) {
			_sync_native_get_items_access(frm);
			_apply_native_manufacture_visibility(frm);
			_run_when_app_enabled(() => {
				_clear_manufacture_data_on_leave(frm);
				_apply_manufacture_visibility(frm);
				_set_prev_purpose(frm);
				_sync_stock_entry_helper_fields(frm);
				_setup_stock_entry_quick_entry(frm);
			});
		},
		from_bom(frm) {
			_sync_native_get_items_access(frm);
			_apply_native_manufacture_visibility(frm);
			_run_when_app_enabled(() => {
				_ensure_use_multi_level_bom_unchecked(frm);
				_hide_standard_get_items(frm);
				_apply_manufacture_visibility(frm);
			});
		},
		bom_no(frm) {
			_sync_native_get_items_access(frm);
			_apply_native_manufacture_visibility(frm);
			_run_when_app_enabled(() => {
				_hide_standard_get_items(frm);
				_apply_manufacture_visibility(frm);
			});
		},
		custom_pea_actual_start_date_input(frm) {
			_run_when_app_enabled(() => {
				_combine_actual_datetime(frm, {
					date_fieldname: "custom_pea_actual_start_date_input",
					time_fieldname: "custom_pea_actual_start_time_input",
					canonical_fieldname: "custom_pea_actual_start_date",
				});
			});
		},
		custom_pea_actual_end_date_input(frm) {
			_run_when_app_enabled(() => {
				_combine_actual_datetime(frm, {
					date_fieldname: "custom_pea_actual_end_date_input",
					time_fieldname: "custom_pea_actual_end_time_input",
					canonical_fieldname: "custom_pea_actual_end_date",
				});
			});
		},
		custom_pea_rejection_qty(frm) {
			_run_when_app_enabled(() => {
				_toggle_rejection_breakup(frm);
				_update_die_tool_metrics(frm);
			});
		},
		custom_pea_fetch_items(frm) {
			_run_when_app_enabled(() => {
				if (!frm.doc.fg_completed_qty) {
					frappe.msgprint(__("Please set Qty to Manufacture before fetching items."));
					return;
				}
				frappe.call({
					method: "production_entry_app.production_entry_app.api.get_items_with_rejection",
					args: { doc: frm.doc },
					freeze: true,
					freeze_message: __("Fetching items..."),
					callback(r) {
						if (!r.message || !r.message.length) return;
						frm.clear_table("items");
						r.message.forEach(function (item) {
							const d = frappe.model.add_child(
								frm.doc,
								"Stock Entry Detail",
								"items"
							);
							Object.keys(item).forEach(function (key) {
								d[key] = item[key];
							});
						});
						frm.refresh_field("items");
						frm.dirty();
						_apply_manufacture_visibility(frm);
						_update_die_tool_metrics(frm);
					},
					error(error) {
						_notify_call_error(__("Failed to fetch items."), error);
					},
				});
			});
		},
		custom_pea_shift(frm) {
			_run_when_app_enabled(() => {
				_handle_shift_change(frm);
			});
		},
	});
}

function _hide_standard_get_items(frm) {
	// Hide the standard "Get Items" button field — our "Fetch Items" replaces it.
	_hide_native_get_items(frm);
}

function _apply_native_manufacture_visibility(frm) {
	const isManufacture = _is_manufacture_doc(frm.doc);
	frm.toggle_display(NATIVE_MANUFACTURE_FIELDS, isManufacture);
	frm.toggle_display(NATIVE_MANUFACTURE_SECTIONS, isManufacture);
	frm.toggle_display(ALWAYS_HIDDEN_FIELDS, false);
	frm.toggle_display(ALWAYS_HIDDEN_SECTIONS, false);
	if (isManufacture) {
		_expand_sections(frm, NATIVE_MANUFACTURE_SECTIONS);
	}
}

function _apply_manufacture_visibility(frm) {
	const isManufacture = _is_manufacture_doc(frm.doc);
	_apply_native_manufacture_visibility(frm);
	// Keep this explicit list in sync with Stock Entry custom manufacture-only fields.
	frm.toggle_display(PEA_MANUFACTURE_FIELDS, isManufacture);
	frm.toggle_display(PEA_MANUFACTURE_SECTIONS, isManufacture);
	if (isManufacture) {
		_expand_sections(frm, PEA_MANUFACTURE_SECTIONS);
	}

	_toggle_rejection_breakup(frm);
	_update_die_tool_metrics(frm);
}

function _set_prev_purpose(frm) {
	frm.__pea_prev_stock_entry_purpose = _normalize_purpose(
		frm.doc?.custom_pea_stock_entry_purpose
	);
}

function _did_leave_manufacture(previousPurpose, currentPurpose) {
	return (
		_normalize_purpose(previousPurpose) === "Manufacture" &&
		_normalize_purpose(currentPurpose) !== "Manufacture"
	);
}

function _clear_manufacture_data_on_leave(frm) {
	const previousPurpose = frm.__pea_prev_stock_entry_purpose;
	const currentPurpose = frm.doc?.custom_pea_stock_entry_purpose;
	if (!_did_leave_manufacture(previousPurpose, currentPurpose)) {
		return;
	}

	_shiftDetailsRequestId++;
	_dieToolRequestId++;

	const refreshFieldnames = new Set();
	const scalarChanged = _clear_manufacture_scalar_fields(frm, refreshFieldnames);
	const tableChanged = _clear_manufacture_table_fields(frm, refreshFieldnames);
	const changed = scalarChanged || tableChanged;

	if (refreshFieldnames.size > 0) {
		frm.refresh_fields(Array.from(refreshFieldnames));
	}

	_clear_die_tool_alert(frm);
	if (changed) {
		frm.dirty();
	}
}

function _clear_manufacture_scalar_fields(frm, refreshFieldnames) {
	let changed = false;
	for (const fieldname of MANUFACTURE_FIELDS) {
		changed = _clear_manufacture_scalar_field(frm, fieldname, refreshFieldnames) || changed;
	}
	return changed;
}

function _clear_manufacture_scalar_field(frm, fieldname, refreshFieldnames) {
	const field = frm.get_field(fieldname);
	const fieldtype = field?.df?.fieldtype || "";
	if (_is_layout_or_table_field(fieldtype)) {
		return false;
	}
	const clearValue = fieldtype === "Check" ? 0 : "";
	if (frm.doc?.[fieldname] === clearValue) {
		return false;
	}
	frm.doc[fieldname] = clearValue;
	refreshFieldnames.add(fieldname);
	return true;
}

function _is_layout_or_table_field(fieldtype) {
	return [
		"Button",
		"Section Break",
		"Column Break",
		"HTML",
		"Table",
		"Table MultiSelect",
	].includes(fieldtype);
}

function _clear_manufacture_table_fields(frm, refreshFieldnames) {
	let changed = false;
	for (const tableField of MANUFACTURE_CLEAR_TABLE_FIELDS) {
		const rows = frm.doc?.[tableField] || [];
		if (!Array.isArray(rows) || rows.length === 0) {
			continue;
		}
		frm.clear_table(tableField);
		refreshFieldnames.add(tableField);
		changed = true;
	}
	return changed;
}

function _expand_sections(frm, sectionFieldnames) {
	sectionFieldnames.forEach((sectionFieldname) => {
		const section = (frm.layout?.sections || []).find(
			(entry) => (entry?.df?.fieldname || "") === sectionFieldname
		);
		if (!section) return;
		if (typeof section.collapse === "function") {
			section.collapse(false);
		}
		section.body?.removeClass?.("hide");
		section.head?.removeClass?.("collapsed");
	});
}

function _is_manufacture_doc(doc) {
	return _normalize_purpose(doc?.custom_pea_stock_entry_purpose) === "Manufacture";
}

function _get_time_entry_api() {
	return window.production_entry_app?.time_entry || null;
}

function _sync_stock_entry_helper_fields(frm) {
	const timeEntry = _get_time_entry_api();
	if (!timeEntry || !_is_manufacture_doc(frm.doc)) {
		return;
	}
	const plannedStartDate = timeEntry.format_datetime_display(
		frm.doc?.custom_pea_planned_start_date || ""
	).date;
	_sync_actual_datetime_helper_fields(frm, {
		date_fieldname: "custom_pea_actual_start_date_input",
		time_fieldname: "custom_pea_actual_start_time_input",
		canonical_fieldname: "custom_pea_actual_start_date",
		default_date: plannedStartDate,
	});
	_sync_actual_datetime_helper_fields(frm, {
		date_fieldname: "custom_pea_actual_end_date_input",
		time_fieldname: "custom_pea_actual_end_time_input",
		canonical_fieldname: "custom_pea_actual_end_date",
		default_date: plannedStartDate,
	});
	timeEntry.sync_loss_entry_rows(frm, "custom_pea_unplanned_losses");
}

function _sync_actual_datetime_helper_fields(
	frm,
	{ date_fieldname, time_fieldname, canonical_fieldname, default_date }
) {
	const timeEntry = _get_time_entry_api();
	if (!timeEntry) {
		return;
	}
	if (frm.doc?.[canonical_fieldname]) {
		timeEntry.sync_datetime_display_from_doc(
			frm,
			date_fieldname,
			time_fieldname,
			canonical_fieldname
		);
		return;
	}

	let changed = false;
	if (default_date && !frm.doc?.[date_fieldname]) {
		frm.doc[date_fieldname] = default_date;
		changed = true;
	}
	if (changed) {
		frm.refresh_fields([date_fieldname, time_fieldname]);
	}
}

function _setup_stock_entry_quick_entry(frm) {
	const timeEntry = _get_time_entry_api();
	if (!timeEntry) {
		return;
	}
	const isManufacture = _is_manufacture_doc(frm.doc);
	timeEntry.attach_datetime_split_chips(
		frm,
		"custom_pea_actual_start_date_input",
		"custom_pea_actual_start_time_input",
		"custom_pea_actual_start_date",
		{ get_shift_ctx: () => _get_shift_ctx(frm), enabled: isManufacture }
	);
	timeEntry.attach_datetime_split_chips(
		frm,
		"custom_pea_actual_end_date_input",
		"custom_pea_actual_end_time_input",
		"custom_pea_actual_end_date",
		{ get_shift_ctx: () => _get_shift_ctx(frm), enabled: isManufacture }
	);
	if (!isManufacture) {
		return;
	}
	timeEntry.bind_committed_time_input(frm, "custom_pea_actual_start_time_input", () =>
		_combine_actual_datetime(frm, {
			date_fieldname: "custom_pea_actual_start_date_input",
			time_fieldname: "custom_pea_actual_start_time_input",
			canonical_fieldname: "custom_pea_actual_start_date",
		})
	);
	timeEntry.bind_committed_time_input(frm, "custom_pea_actual_end_time_input", () =>
		_combine_actual_datetime(frm, {
			date_fieldname: "custom_pea_actual_end_date_input",
			time_fieldname: "custom_pea_actual_end_time_input",
			canonical_fieldname: "custom_pea_actual_end_date",
		})
	);
}

function _combine_actual_datetime(frm, { date_fieldname, time_fieldname, canonical_fieldname }) {
	const timeEntry = _get_time_entry_api();
	if (!timeEntry) {
		return;
	}
	const dateValue = String(frm.doc?.[date_fieldname] || "").trim();
	const timeValue = String(frm.doc?.[time_fieldname] || "").trim();
	if (!dateValue && !timeValue) {
		timeEntry.set_field_invalid(frm, time_fieldname, "");
		frm.set_value(canonical_fieldname, "");
		return;
	}
	if (!dateValue || !timeValue) {
		return;
	}
	const parsed = timeEntry.parse_time(timeValue);
	if (parsed.error) {
		timeEntry.set_field_invalid(frm, time_fieldname, parsed.error);
		return;
	}
	timeEntry.set_field_invalid(frm, time_fieldname, "");
	frm.set_value(time_fieldname, timeEntry.format_time_display(parsed.frappe_time));
	frm.set_value(canonical_fieldname, `${dateValue} ${parsed.frappe_time}`);
}

function _get_shift_ctx(frm) {
	const start = frm.doc?.custom_pea_planned_start_date || "";
	const end = frm.doc?.custom_pea_planned_end_date || "";
	return { start, end };
}

function _handle_shift_change(frm) {
	if (!frm.doc.custom_pea_shift) {
		_shiftDetailsRequestId++;
		_clear_shift_derived_fields(frm).finally(() => {
			_sync_stock_entry_helper_fields(frm);
			_setup_stock_entry_quick_entry(frm);
		});
		return;
	}

	const selectedShift = frm.doc.custom_pea_shift;
	const reqId = ++_shiftDetailsRequestId;
	frappe.call({
		method: "production_entry_app.production_entry_app.api.get_shift_details_for_stock_entry",
		args: { shift_name: selectedShift },
		callback(r) {
			_apply_shift_details_response(frm, selectedShift, reqId, r.message);
		},
		error(error) {
			if (reqId !== _shiftDetailsRequestId) {
				return;
			}
			_clear_shift_derived_fields(frm).finally(() => {
				_sync_stock_entry_helper_fields(frm);
				_setup_stock_entry_quick_entry(frm);
			});
			_notify_call_error(__("Failed to fetch shift details."), error);
		},
	});
}

function _apply_shift_details_response(frm, selectedShift, reqId, data) {
	if (reqId !== _shiftDetailsRequestId || frm.doc.custom_pea_shift !== selectedShift) {
		return;
	}
	if (!data) {
		_clear_shift_derived_fields(frm).finally(() => {
			_sync_stock_entry_helper_fields(frm);
			_setup_stock_entry_quick_entry(frm);
		});
		return;
	}
	Promise.all(_get_shift_detail_updates(frm, data)).finally(() => {
		_sync_stock_entry_helper_fields(frm);
		_setup_stock_entry_quick_entry(frm);
	});
}

function _get_shift_detail_updates(frm, data) {
	const fieldMap = {
		company: "company",
		branch: "branch",
		custom_pea_planned_start_date: "custom_pea_planned_start_date",
		custom_pea_planned_end_date: "custom_pea_planned_end_date",
		from_warehouse: "from_warehouse",
		to_warehouse: "to_warehouse",
	};
	return Object.entries(fieldMap)
		.filter(([sourceField]) => Object.prototype.hasOwnProperty.call(data, sourceField))
		.map(([sourceField, targetField]) => frm.set_value(targetField, data[sourceField]));
}

function _clear_shift_derived_fields(frm) {
	return Promise.all([
		frm.set_value("branch", ""),
		frm.set_value("custom_pea_planned_start_date", ""),
		frm.set_value("custom_pea_planned_end_date", ""),
		frm.set_value("from_warehouse", ""),
		frm.set_value("to_warehouse", ""),
	]);
}

function _extract_error_detail(error) {
	const message = String(error?.message || "").trim();
	if (message) {
		return message;
	}
	const responseMessage = String(error?.responseJSON?._error_message || "").trim();
	if (responseMessage) {
		return responseMessage;
	}
	return "";
}

function _notify_call_error(prefix, error) {
	const detail = _extract_error_detail(error);
	frappe.msgprint(prefix + (detail ? ` ${detail}` : ""));
}

function _normalize_purpose(purpose) {
	return (purpose || "").trim();
}

function _toggle_rejection_breakup(frm) {
	if (!_is_manufacture_doc(frm.doc)) {
		frm.toggle_display("custom_pea_rejection_breakup", false);
		frm.toggle_reqd("custom_pea_rejection_breakup", false);
		return;
	}
	const rejection_qty = typeof flt === "function" ? flt(frm.doc.custom_pea_rejection_qty) : 0;
	const has_rejection = rejection_qty > 0;
	frm.toggle_display("custom_pea_rejection_breakup", has_rejection);
	frm.toggle_reqd("custom_pea_rejection_breakup", has_rejection);
}

function _update_die_tool_metrics(frm) {
	if (!_is_manufacture_doc(frm.doc)) return;

	const item_code = _get_die_tool_item_code(frm);
	if (!item_code) {
		_set_die_tool_metric_fields(frm, 0, 0);
		return;
	}

	const reqId = ++_dieToolRequestId;
	frappe.call({
		method: "production_entry_app.production_entry_app.api.get_die_tool_counter",
		args: { die_tool_code: item_code },
		callback(r) {
			if (reqId !== _dieToolRequestId) return;
			if (!r.message) return;
			const data = r.message;
			if (parseInt(data.has_die_tool ?? 1, 10) !== 1) {
				_set_die_tool_metric_fields(frm, 0, 0);
				_clear_die_tool_alert(frm);
				return;
			}
			const utilization = parseFloat(data.utilization_pct || 0);
			const due = parseInt(data.is_maintenance_due || 0, 10) === 1;
			_set_die_tool_metric_fields(frm, utilization, due ? 1 : 0);

			if (due && frm.dashboard && frm.dashboard.set_headline_alert) {
				const message = __(
					"Die tool {0} has reached {1}% utilization and needs maintenance.",
					[item_code, _formatFloatFragment(utilization)]
				);
				if (frm.__peaDieToolAlertMessage !== message) {
					frm.dashboard.set_headline_alert(message, "orange");
					frm.__peaDieToolAlertMessage = message;
				}
			} else if (!due) {
				_clear_die_tool_alert(frm);
			}
		},
		error() {
			if (reqId !== _dieToolRequestId) return;
			frappe.msgprint(__("Failed to load die tool metrics. Please refresh."));
		},
	});
}

function _set_die_tool_metric_fields(frm, utilization, due) {
	if (frm.fields_dict.custom_pea_die_tool_utilization_pct) {
		frm.doc.custom_pea_die_tool_utilization_pct = utilization;
	}
	if (frm.fields_dict.custom_pea_die_tool_maintenance_due) {
		frm.doc.custom_pea_die_tool_maintenance_due = due;
	}
	frm.refresh_fields([
		"custom_pea_die_tool_utilization_pct",
		"custom_pea_die_tool_maintenance_due",
	]);
}

function _formatFloatFragment(value) {
	const numericValue = Number(value || 0);
	const precision = _getNumericPrecision(value);
	if (typeof frappe !== "undefined" && typeof frappe.format === "function") {
		return frappe.format(
			numericValue,
			{ fieldtype: "Float", precision },
			{ only_value: true }
		);
	}
	return String(numericValue);
}

function _getNumericPrecision(value) {
	const text = String(value ?? "").trim();
	if (!text) {
		return 0;
	}
	const normalized = text.includes("e") || text.includes("E") ? Number(value).toString() : text;
	const parts = normalized.split(".");
	if (parts.length < 2) {
		return 0;
	}
	return parts[1].replace(/0+$/, "").length;
}

function _clear_die_tool_alert(frm) {
	frm.__peaDieToolAlertMessage = null;
	if (frm.dashboard && typeof frm.dashboard.clear_headline === "function") {
		frm.dashboard.clear_headline();
	}
}

function _ensure_use_multi_level_bom_unchecked(frm) {
	if (frm.doc.from_bom && frm.doc.use_multi_level_bom) {
		frm.doc.use_multi_level_bom = 0;
		frm.refresh_field("use_multi_level_bom");
	}
}

function _get_die_tool_item_code(frm) {
	if (frm.doc.fg_item) return frm.doc.fg_item;
	const items = frm.doc.items || [];
	const fgRow = items.find((row) => row.is_finished_item);
	return fgRow ? fgRow.item_code : null;
}

if (typeof module !== "undefined" && module.exports) {
	module.exports = {
		_normalize_purpose,
		_is_manufacture_doc,
		_did_leave_manufacture,
		_apply_native_manufacture_visibility,
		NATIVE_MANUFACTURE_FIELDS,
		NATIVE_MANUFACTURE_SECTIONS,
		PEA_MANUFACTURE_FIELDS,
		PEA_MANUFACTURE_SECTIONS,
		MANUFACTURE_FIELDS,
		MANUFACTURE_SECTIONS,
		ALWAYS_HIDDEN_FIELDS,
		ALWAYS_HIDDEN_SECTIONS,
		MANUFACTURE_CLEAR_TABLE_FIELDS,
		_should_override_fg_completed_qty,
		_run_when_app_enabled,
		_sync_native_get_items_access,
		_get_shift_detail_updates,
		_hide_native_get_items,
		_show_native_get_items,
	};
}
