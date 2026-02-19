// Copyright (c) 2026, Gurudatt Kulkarni and contributors
// For license information, please see license.txt

/* global erpnext */

// Suppress ERPNext's auto-populate on fg_completed_qty change for Manufacture
// entries so the user can set both Qty to Manufacture and Rejection Qty before
// explicitly clicking "Fetch Items".
if (window.erpnext && erpnext.stock && erpnext.stock.StockEntry) {
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

frappe.ui.form.on("Stock Entry", {
	async onload(frm) {
		_hide_standard_get_items(frm);
		await _sync_custom_stock_entry_purpose(frm, false);
		_apply_manufacture_visibility(frm);
	},
	async refresh(frm) {
		// Set filter to only show Running shifts
		frm.set_query("custom_shift", function () {
			return {
				filters: [["Shift", "status", "=", "Running"]],
			};
		});

		_ensure_use_multi_level_bom_unchecked(frm);
		await _sync_custom_stock_entry_purpose(frm, false);
		_apply_manufacture_visibility(frm);

		_hide_standard_get_items(frm);
	},
	async purpose(frm) {
		await _sync_custom_stock_entry_purpose(frm, false);
		_apply_manufacture_visibility(frm);
	},
	async stock_entry_type(frm) {
		await _sync_custom_stock_entry_purpose(frm, true);
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
			async callback(r) {
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
				await _sync_custom_stock_entry_purpose(frm, false);
				_apply_manufacture_visibility(frm);
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

async function _sync_custom_stock_entry_purpose(frm, fetch_from_server) {
	const selectedType = frm.doc.stock_entry_type || "";
	if (!selectedType) {
		_set_custom_stock_entry_purpose(frm, "");
		return "";
	}

	let purpose = frm.doc.custom_stock_entry_purpose || frm.doc.purpose || "";
	if (!purpose && fetch_from_server) {
		try {
			const response = await frappe.db.get_value(
				"Stock Entry Type",
				selectedType,
				"purpose"
			);
			if (frm.doc.stock_entry_type !== selectedType) {
				return frm.doc.custom_stock_entry_purpose || "";
			}
			purpose = response?.message?.purpose || "";
		} catch (error) {
			// Keep the existing value when lookup fails.
		}
	}

	_set_custom_stock_entry_purpose(frm, purpose || "");
	return purpose || "";
}

function _set_custom_stock_entry_purpose(frm, purpose) {
	const normalized = purpose || "";
	if ((frm.doc.custom_stock_entry_purpose || "") === normalized) return;
	frm.doc.custom_stock_entry_purpose = normalized;
	// Keep ERPNext's hidden purpose field in sync so native depends_on rules still work.
	if (normalized && frm.doc.purpose !== normalized) {
		frm.doc.purpose = normalized;
		frm.refresh_field("purpose");
	}
	frm.refresh_field("custom_stock_entry_purpose");
}

function _apply_manufacture_visibility(frm) {
	const isManufacture = _is_manufacture_doc(frm.doc);
	const manufactureFields = [
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
		"process_loss_percentage",
		"process_loss_qty",
	];
	frm.toggle_display(manufactureFields, isManufacture);

	const manufactureSections = [
		"bom_info_section",
		"section_break_7qsm",
		"custom_operation_details_section",
		"custom_workstation_operator_section",
		"custom_unplanned_losses_section",
		"custom_metrics_section",
	];
	manufactureSections.forEach((sectionFieldname) => {
		_set_section_visible(frm, sectionFieldname, isManufacture);
	});
	if (isManufacture) {
		_expand_sections(frm, manufactureSections);
		setTimeout(() => _expand_sections(frm, manufactureSections), 0);
	}

	_toggle_rejection_breakup(frm);
	_update_die_tool_metrics(frm);
}

function _set_section_visible(frm, sectionFieldname, shouldShow) {
	const section = _find_section(frm, sectionFieldname);
	if (!section) return;
	if (shouldShow) {
		section.show();
		if (typeof section.collapse === "function") {
			section.collapse(false);
		}
		return;
	}
	section.hide();
}

function _find_section(frm, sectionFieldname) {
	const labelsByFieldname = {
		bom_info_section: "BOM Info",
		section_break_7qsm: "Process Loss",
		custom_operation_details_section: "Planned & Actual Dates",
		custom_workstation_operator_section: "Workstation & Operator",
		custom_unplanned_losses_section: "Unplanned Losses",
		custom_metrics_section: "Production Metrics",
	};
	const sectionLabel = labelsByFieldname[sectionFieldname];
	return (frm.layout?.sections || []).find((entry) => {
		const fieldname = entry?.df?.fieldname || "";
		const label = entry?.df?.label || "";
		return fieldname === sectionFieldname || (sectionLabel && label === sectionLabel);
	});
}

function _expand_sections(frm, sectionFieldnames) {
	sectionFieldnames.forEach((sectionFieldname) => {
		const section = _find_section(frm, sectionFieldname);
		if (!section) return;
		if (typeof section.collapse === "function") {
			section.collapse(false);
		}
		section.body?.removeClass?.("hide");
		section.head?.removeClass?.("collapsed");
	});
}

function _is_manufacture_doc(doc) {
	const purpose = doc.custom_stock_entry_purpose || doc.purpose || "";
	return purpose === "Manufacture";
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
