// Copyright (c) 2026, Gurudatt Kulkarni and contributors
// For license information, please see license.txt

/* global erpnext */

// Suppress ERPNext's auto-populate on fg_completed_qty change for Manufacture
// entries so the user can set both Qty to Manufacture and Rejection Qty before
// explicitly clicking "Fetch Items".
if (window.erpnext && erpnext.stock && erpnext.stock.StockEntry) {
	const _original_fg_completed_qty = erpnext.stock.StockEntry.prototype.fg_completed_qty;

	erpnext.stock.StockEntry.prototype.fg_completed_qty = function () {
		if (this.frm.doc.purpose === "Manufacture" && this.frm.doc.from_bom) {
			// Skip the standard get_items() call — handled by our Fetch Items button
			return;
		}
		// For all other purposes, keep the standard behaviour
		if (_original_fg_completed_qty) {
			return _original_fg_completed_qty.call(this);
		}
	};
}

frappe.ui.form.on("Stock Entry", {
	onload(frm) {
		_hide_standard_get_items(frm);
	},
	refresh(frm) {
		// Set filter to only show Running shifts
		frm.set_query("custom_shift", function () {
			return {
				filters: [["Shift", "status", "=", "Running"]],
			};
		});

		frm.toggle_display(["custom_planned_start_date", "custom_planned_end_date"], true);
		_ensure_use_multi_level_bom_unchecked(frm);
		_toggle_rejection_breakup(frm);
		_update_die_tool_metrics(frm);

		_hide_standard_get_items(frm);
	},
	from_bom(frm) {
		_ensure_use_multi_level_bom_unchecked(frm);
		_hide_standard_get_items(frm);
	},
	bom_no(frm) {
		_hide_standard_get_items(frm);
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
				_update_die_tool_metrics(frm);
			},
		});
	},
	custom_shift(frm) {
		if (frm.doc.custom_shift) {
			frappe.call({
				method: "production_entry_app.production_entry_app.api.get_shift_details_for_stock_entry",
				args: { shift_name: frm.doc.custom_shift },
				callback(r) {
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
							frm.set_value("custom_planned_end_date", data.custom_planned_end_date);
						}
						if (data.from_warehouse) {
							frm.set_value("from_warehouse", data.from_warehouse);
						}
						if (data.to_warehouse) {
							frm.set_value("to_warehouse", data.to_warehouse);
						}
					}
				},
			});
		} else {
			frm.set_value("branch", "");
			frm.set_value("custom_planned_start_date", "");
			frm.set_value("custom_planned_end_date", "");
			frm.set_value("from_warehouse", "");
			frm.set_value("to_warehouse", "");
		}
	},
});

function _hide_standard_get_items(frm) {
	// Hide the standard "Get Items" button field — our "Fetch Items" replaces it
	frm.toggle_display("get_items", false);
	frm.set_df_property("get_items", "hidden", 1);
}

function _toggle_rejection_breakup(frm) {
	const rejection_qty = typeof flt === "function" ? flt(frm.doc.custom_rejection_qty) : 0;
	const has_rejection = rejection_qty > 0;
	frm.toggle_display("custom_rejection_breakup", has_rejection);
	frm.toggle_reqd("custom_rejection_breakup", has_rejection);
}

function _update_die_tool_metrics(frm) {
	if (frm.doc.purpose !== "Manufacture") return;

	const item_code = _get_die_tool_item_code(frm);
	if (!item_code) {
		_set_die_tool_metric_fields(frm, 0, 0);
		return;
	}

	frappe.call({
		method: "production_entry_app.production_entry_app.api.get_die_tool_counter",
		args: { die_tool_code: item_code },
		callback(r) {
			if (!r.message) return;
			const data = r.message;
			const utilization = parseFloat(data.utilization_pct || 0);
			const due = parseInt(data.is_maintenance_due || 0, 10) === 1;
			_set_die_tool_metric_fields(frm, utilization, due ? 1 : 0);

			if (due && frm.dashboard && frm.dashboard.set_headline_alert) {
				frm.dashboard.set_headline_alert(
					__("Die tool {0} has reached {1}% utilization and needs maintenance.", [
						item_code,
						utilization.toFixed(2),
					]),
					"orange"
				);
			}
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
