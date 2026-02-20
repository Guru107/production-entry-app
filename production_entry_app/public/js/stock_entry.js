// Copyright (c) 2026, Gurudatt Kulkarni and contributors
// For license information, please see license.txt

/* global erpnext */

const MANUFACTURE_FIELDS = [
	"from_bom",
	"bom_no",
	"use_multi_level_bom",
	"fg_completed_qty",
	"custom_rejection_qty",
	"custom_fetch_items",
	"custom_planned_start_date",
	"custom_planned_end_date",
	"custom_actual_start_date",
	"custom_actual_end_date",
	"custom_workstation",
	"custom_standard_spm",
	"custom_operator",
	"custom_unplanned_losses",
	"custom_actual_duration_mins",
	"custom_actual_spm",
	"custom_cycle_time_sec",
	"custom_operator_efficiency_pct",
	"custom_die_tool_utilization_pct",
	"custom_die_tool_maintenance_due",
];

const MANUFACTURE_SECTIONS = [
	"bom_info_section",
	"custom_operation_details_section",
	"custom_workstation_operator_section",
	"custom_unplanned_losses_section",
	"custom_metrics_section",
];

const ALWAYS_HIDDEN_FIELDS = ["process_loss_percentage", "process_loss_qty"];
const ALWAYS_HIDDEN_SECTIONS = ["section_break_7qsm"];
let _dieToolRequestId = 0;
let _shiftDetailsRequestId = 0;

// Suppress ERPNext's auto-populate on fg_completed_qty change for Manufacture
// entries so the user can set both Qty to Manufacture and Rejection Qty before
// explicitly clicking "Fetch Items".
if (typeof window !== "undefined" && window.erpnext && erpnext.stock && erpnext.stock.StockEntry) {
	const _original_fg_completed_qty = erpnext.stock.StockEntry.prototype.fg_completed_qty;

	erpnext.stock.StockEntry.prototype.fg_completed_qty = function () {
		if (_is_manufacture_doc(this.frm.doc) && this.frm.doc.from_bom) {
			// Skip the standard get_items() call — handled by our Fetch Items button
			return;
		}
		// For all other purposes, keep the standard behaviour
		if (_original_fg_completed_qty) {
			return _original_fg_completed_qty.call(this);
		}
	};
}

if (typeof frappe !== "undefined" && frappe.ui && frappe.ui.form) {
	frappe.ui.form.on("Stock Entry", {
		onload(frm) {
			_hide_standard_get_items(frm);
			_apply_manufacture_visibility(frm);
		},
		refresh(frm) {
			// Set filter to only show Running shifts
			frm.set_query("custom_shift", function () {
				return {
					filters: [["Shift", "status", "=", "Running"]],
				};
			});

			_ensure_use_multi_level_bom_unchecked(frm);
			_apply_manufacture_visibility(frm);
			_hide_standard_get_items(frm);
		},
		stock_entry_type(frm) {
			// custom_stock_entry_purpose is fetched via fetch_from and will re-trigger visibility.
			_apply_manufacture_visibility(frm);
		},
		custom_stock_entry_purpose(frm) {
			_apply_manufacture_visibility(frm);
		},
		from_bom(frm) {
			_ensure_use_multi_level_bom_unchecked(frm);
			_hide_standard_get_items(frm);
			_apply_manufacture_visibility(frm);
		},
		bom_no(frm) {
			_hide_standard_get_items(frm);
			_apply_manufacture_visibility(frm);
		},
		custom_rejection_qty(frm) {
			_toggle_rejection_breakup(frm);
			_update_die_tool_metrics(frm);
		},
		custom_fetch_items(frm) {
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
						const d = frappe.model.add_child(frm.doc, "Stock Entry Detail", "items");
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
					console.warn("Failed to fetch stock entry items.", error);
				},
			});
		},
		custom_shift(frm) {
			if (frm.doc.custom_shift) {
				const selectedShift = frm.doc.custom_shift;
				const reqId = ++_shiftDetailsRequestId;
				frappe.call({
					method: "production_entry_app.production_entry_app.api.get_shift_details_for_stock_entry",
					args: { shift_name: selectedShift },
					callback(r) {
						if (
							reqId !== _shiftDetailsRequestId ||
							frm.doc.custom_shift !== selectedShift
						) {
							return;
						}
						if (r.message) {
							const data = r.message;
							if (data.branch) {
								frm.set_value("branch", data.branch);
							}
							if (data.custom_planned_start_date) {
								frm.set_value(
									"custom_planned_start_date",
									data.custom_planned_start_date
								);
							}
							if (data.custom_planned_end_date) {
								frm.set_value(
									"custom_planned_end_date",
									data.custom_planned_end_date
								);
							}
							if (data.from_warehouse) {
								frm.set_value("from_warehouse", data.from_warehouse);
							}
							if (data.to_warehouse) {
								frm.set_value("to_warehouse", data.to_warehouse);
							}
						}
					},
					error(error) {
						if (reqId !== _shiftDetailsRequestId) return;
						console.warn("Failed to fetch shift details for stock entry.", error);
					},
				});
			} else {
				_shiftDetailsRequestId++;
				frm.set_value("branch", "");
				frm.set_value("custom_planned_start_date", "");
				frm.set_value("custom_planned_end_date", "");
				frm.set_value("from_warehouse", "");
				frm.set_value("to_warehouse", "");
			}
		},
	});
}

function _hide_standard_get_items(frm) {
	// Hide the standard "Get Items" button field — our "Fetch Items" replaces it
	frm.toggle_display("get_items", false);
	frm.set_df_property("get_items", "hidden", 1);
}

function _apply_manufacture_visibility(frm) {
	const isManufacture = _is_manufacture_doc(frm.doc);
	// Keep this explicit list in sync with Stock Entry custom manufacture-only fields.
	frm.toggle_display(MANUFACTURE_FIELDS, isManufacture);
	frm.toggle_display(MANUFACTURE_SECTIONS, isManufacture);
	frm.toggle_display(ALWAYS_HIDDEN_FIELDS, false);
	frm.toggle_display(ALWAYS_HIDDEN_SECTIONS, false);
	if (isManufacture) {
		_expand_sections(frm, MANUFACTURE_SECTIONS);
	}

	_toggle_rejection_breakup(frm);
	_update_die_tool_metrics(frm);
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
	return _normalize_purpose(doc?.custom_stock_entry_purpose) === "Manufacture";
}

function _normalize_purpose(purpose) {
	return (purpose || "").trim();
}

function _toggle_rejection_breakup(frm) {
	if (!_is_manufacture_doc(frm.doc)) {
		frm.toggle_display("custom_rejection_breakup", false);
		frm.toggle_reqd("custom_rejection_breakup", false);
		return;
	}
	const rejection_qty = typeof flt === "function" ? flt(frm.doc.custom_rejection_qty) : 0;
	const has_rejection = rejection_qty > 0;
	frm.toggle_display("custom_rejection_breakup", has_rejection);
	frm.toggle_reqd("custom_rejection_breakup", has_rejection);
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
			const utilization = parseFloat(data.utilization_pct || 0);
			const due = parseInt(data.is_maintenance_due || 0, 10) === 1;
			_set_die_tool_metric_fields(frm, utilization, due ? 1 : 0);

			if (due && frm.dashboard && frm.dashboard.set_headline_alert) {
				const message = __(
					"Die tool {0} has reached {1}% utilization and needs maintenance.",
					[item_code, utilization.toFixed(2)]
				);
				if (frm.__peaDieToolAlertMessage !== message) {
					frm.dashboard.set_headline_alert(message, "orange");
					frm.__peaDieToolAlertMessage = message;
				}
			} else if (!due) {
				frm.__peaDieToolAlertMessage = null;
			}
		},
		error() {
			if (reqId !== _dieToolRequestId) return;
			frappe.msgprint(__("Failed to load die tool metrics. Please refresh."));
		},
	});
}

function _set_die_tool_metric_fields(frm, utilization, due) {
	if (frm.fields_dict.custom_die_tool_utilization_pct) {
		frm.doc.custom_die_tool_utilization_pct = utilization;
	}
	if (frm.fields_dict.custom_die_tool_maintenance_due) {
		frm.doc.custom_die_tool_maintenance_due = due;
	}
	frm.refresh_fields(["custom_die_tool_utilization_pct", "custom_die_tool_maintenance_due"]);
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
		MANUFACTURE_FIELDS,
		MANUFACTURE_SECTIONS,
		ALWAYS_HIDDEN_FIELDS,
		ALWAYS_HIDDEN_SECTIONS,
	};
}
