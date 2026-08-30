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

const NORMAL_ONLY_PEA_FIELDS = ["custom_pea_rejection_qty", "custom_pea_rework_qty"];
const JOINT_ONLY_PEA_FIELDS = ["custom_pea_joint_fetch_items"];

const MANUFACTURE_FIELDS = [...NATIVE_MANUFACTURE_FIELDS, ...PEA_MANUFACTURE_FIELDS];

const NATIVE_MANUFACTURE_SECTIONS = ["bom_info_section"];

const PEA_MANUFACTURE_SECTIONS = [
	"custom_pea_operation_details_section",
	"custom_pea_workstation_operator_section",
	"custom_pea_unplanned_losses_section",
	"custom_pea_rejection_section",
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
const PRODUCTION_MODE_SCALAR_FIELDS = [
	"from_bom",
	"bom_no",
	"use_multi_level_bom",
	"fg_completed_qty",
	"custom_pea_rejection_qty",
	"custom_pea_ok_qty",
	"custom_pea_rework_qty",
	"custom_pea_lh_bom",
	"custom_pea_lh_gross_qty",
	"custom_pea_lh_rejection_qty",
	"custom_pea_rh_bom",
	"custom_pea_rh_gross_qty",
	"custom_pea_rh_rejection_qty",
	"custom_pea_total_strokes",
	"custom_pea_die_tool_item",
	"custom_pea_total_rm_consumption",
];
const PRODUCTION_MODE_CLEAR_TABLE_FIELDS = ["custom_pea_rejection_breakup", "items"];
let _dieToolRequestId = 0;
let _shiftDetailsRequestId = 0;
let _jointStockEntryTypeRequestId = 0;
const _rejectionSideRequestIds = new Map();
const JOINT_RM_DEBOUNCE_MS = 300;

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
	_hide_native_get_items(frm);
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
			if (
				_is_manufacture_doc(this.frm.doc) &&
				this.frm.doc.from_bom &&
				this.frm.doc.custom_pea_shift &&
				!this.frm.doc.job_card
			) {
				// Shift-linked direct manufacture: item fetch is handled by
				// the PEA "Fetch Items" button. Preserve v16's native Job Card
				// guard and native behavior for non-Shift entries.
				return;
			}
			// For all other purposes, keep the standard behaviour.
			return originalFgCompletedQty.call(this);
		};
	}
}

if (typeof frappe !== "undefined" && frappe.ui && frappe.ui.form) {
	frappe.ui.form.on("Stock Entry", {
		before_load(frm) {
			// Desk reuses this form when loading a different document.
			_initialize_total_strokes_default_state(frm);
		},
		onload(frm) {
			_set_prev_purpose(frm);
			_set_prev_stock_entry_type(frm);
			_sync_native_get_items_access(frm);
			_apply_native_manufacture_visibility(frm);
			_apply_manufacture_visibility(frm);
		},
		refresh(frm) {
			// Covers cached navigation, reloads, and the new-to-saved document rename.
			_initialize_total_strokes_default_state(frm);
			_set_prev_purpose(frm);
			_set_prev_stock_entry_type(frm);
			_sync_native_get_items_access(frm);
			_apply_native_manufacture_visibility(frm);
			// Set filter to show shifts that can accept post-facto entries.
			frm.set_query("custom_pea_shift", function () {
				return {
					filters: [["Shift", "status", "in", ["Running", "Completed"]]],
				};
			});
			for (const fieldname of ["custom_pea_lh_bom", "custom_pea_rh_bom"]) {
				frm.set_query(fieldname, function () {
					return {
						filters: { docstatus: 1, is_active: 1, company: frm.doc.company },
					};
				});
			}

			_ensure_use_multi_level_bom_unchecked(frm);
			_apply_manufacture_visibility(frm);
			_hide_standard_get_items(frm);
			_sync_stock_entry_helper_fields(frm);
			_setup_stock_entry_quick_entry(frm);
		},
		stock_entry_type(frm) {
			const previousStockEntryType = frm.__pea_prev_stock_entry_type || "";
			_sync_joint_stock_entry_type(frm, {
				source: "stock_entry_type",
				previousStockEntryType,
			});
			_set_prev_stock_entry_type(frm);
			_sync_native_get_items_access(frm);
			_apply_native_manufacture_visibility(frm);
			// custom_pea_stock_entry_purpose is fetched via fetch_from and will re-trigger visibility.
			_apply_manufacture_visibility(frm);
			_sync_stock_entry_helper_fields(frm);
			_setup_stock_entry_quick_entry(frm);
		},
		custom_pea_stock_entry_purpose(frm) {
			_sync_native_get_items_access(frm);
			_apply_native_manufacture_visibility(frm);
			_clear_manufacture_data_on_leave(frm);
			_apply_manufacture_visibility(frm);
			_set_prev_purpose(frm);
			_sync_stock_entry_helper_fields(frm);
			_setup_stock_entry_quick_entry(frm);
		},
		fg_completed_qty(frm) {
			_default_total_strokes_from_fg(frm);
		},
		custom_pea_is_joint_lh_rh(frm) {
			_apply_native_manufacture_visibility(frm);
			_apply_manufacture_visibility(frm);
			_sync_stock_entry_helper_fields(frm);
			_setup_stock_entry_quick_entry(frm);
			_schedule_joint_rm_consumption(frm);
			_sync_joint_stock_entry_type(frm);
		},
		custom_pea_lh_bom(frm) {
			_schedule_joint_rm_consumption(frm);
			_refresh_joint_rejection_items(frm, "LH");
		},
		custom_pea_rh_bom(frm) {
			_schedule_joint_rm_consumption(frm);
			_refresh_joint_rejection_items(frm, "RH");
		},
		custom_pea_lh_gross_qty(frm) {
			_schedule_joint_rm_consumption(frm);
		},
		custom_pea_rh_gross_qty(frm) {
			_schedule_joint_rm_consumption(frm);
		},
		from_bom(frm) {
			_sync_native_get_items_access(frm);
			_apply_native_manufacture_visibility(frm);
			_ensure_use_multi_level_bom_unchecked(frm);
			_hide_standard_get_items(frm);
			_apply_manufacture_visibility(frm);
		},
		bom_no(frm) {
			_sync_native_get_items_access(frm);
			_apply_native_manufacture_visibility(frm);
			_hide_standard_get_items(frm);
			_apply_manufacture_visibility(frm);
		},
		custom_pea_actual_start_date_input(frm) {
			_combine_actual_datetime(frm, {
				date_fieldname: "custom_pea_actual_start_date_input",
				time_fieldname: "custom_pea_actual_start_time_input",
				canonical_fieldname: "custom_pea_actual_start_date",
			});
		},
		custom_pea_actual_end_date_input(frm) {
			_combine_actual_datetime(frm, {
				date_fieldname: "custom_pea_actual_end_date_input",
				time_fieldname: "custom_pea_actual_end_time_input",
				canonical_fieldname: "custom_pea_actual_end_date",
			});
		},
		custom_pea_rejection_qty(frm) {
			_toggle_rejection_breakup(frm);
			_update_die_tool_metrics(frm);
		},
		custom_pea_lh_rejection_qty(frm) {
			_toggle_rejection_breakup(frm);
		},
		custom_pea_rh_rejection_qty(frm) {
			_toggle_rejection_breakup(frm);
		},
		custom_pea_die_tool_item(frm) {
			_update_die_tool_metrics(frm);
		},
		custom_pea_fetch_items(frm) {
			const isJoint = _is_joint_doc(frm.doc);
			if (!isJoint && !frm.doc.fg_completed_qty) {
				frappe.msgprint(__("Please set Qty to Manufacture before fetching items."));
				return;
			}
			if (
				isJoint &&
				(!frm.doc.custom_pea_lh_gross_qty || !frm.doc.custom_pea_rh_gross_qty)
			) {
				frappe.msgprint(__("Please set LH and RH Gross Quantity before fetching items."));
				return;
			}
			frappe.call({
				method: isJoint
					? "production_entry_app.production_entry_app.api.get_joint_production_items"
					: "production_entry_app.production_entry_app.api.get_items_with_rejection",
				args: { doc: frm.doc },
				freeze: true,
				freeze_message: __("Fetching items..."),
				callback(r) {
					_apply_fetch_items_response(frm, r.message);
					if (isJoint) {
						const rmRow = (r.message || []).find((row) => row.s_warehouse);
						frm.set_value("custom_pea_total_rm_consumption", rmRow?.qty || 0);
					}
				},
				error(error) {
					_notify_call_error(__("Failed to fetch items."), error);
				},
			});
		},
		custom_pea_joint_fetch_items(frm) {
			return frm.trigger("custom_pea_fetch_items");
		},
		custom_pea_shift(frm) {
			_handle_shift_change(frm);
		},
	});

	frappe.ui.form.on("Rejection Breakup", {
		output_side(frm, cdt, cdn) {
			if (!_is_joint_doc(frm.doc)) return;
			const row = locals[cdt][cdn];
			const selectedSide = row.output_side;
			const requestId = (_rejectionSideRequestIds.get(cdn) || 0) + 1;
			_rejectionSideRequestIds.set(cdn, requestId);
			const bom =
				selectedSide === "LH" ? frm.doc.custom_pea_lh_bom : frm.doc.custom_pea_rh_bom;
			if (!bom) {
				_rejectionSideRequestIds.delete(cdn);
				frappe.model.set_value(cdt, cdn, "item_code", "");
				return;
			}
			frappe.db
				.get_value("BOM", bom, "item")
				.then((response) => {
					const currentRow = locals[cdt]?.[cdn];
					if (
						_rejectionSideRequestIds.get(cdn) !== requestId ||
						!currentRow ||
						currentRow.output_side !== selectedSide
					) {
						return;
					}
					frappe.model.set_value(cdt, cdn, "item_code", response?.message?.item || "");
				})
				.catch((error) => {
					if (_rejectionSideRequestIds.get(cdn) === requestId) {
						_notify_call_error(__("Failed to load the joint output item."), error);
					}
				})
				.finally(() => {
					if (_rejectionSideRequestIds.get(cdn) === requestId) {
						_rejectionSideRequestIds.delete(cdn);
					}
				});
		},
	});
}

function _refresh_joint_rejection_items(frm, side) {
	if (!_is_joint_doc(frm.doc)) return;
	const bomFieldname = side === "LH" ? "custom_pea_lh_bom" : "custom_pea_rh_bom";
	const selectedBom = frm.doc[bomFieldname];
	frm.__peaRejectionBomRequestIds ||= {};
	const requestId = (frm.__peaRejectionBomRequestIds[side] || 0) + 1;
	frm.__peaRejectionBomRequestIds[side] = requestId;

	const applyItem = (itemCode) => {
		if (
			frm.__peaRejectionBomRequestIds[side] !== requestId ||
			frm.doc[bomFieldname] !== selectedBom
		) {
			return;
		}
		for (const row of frm.doc.custom_pea_rejection_breakup || []) {
			if (row.output_side === side) row.item_code = itemCode;
		}
		frm.refresh_field("custom_pea_rejection_breakup");
	};

	if (!selectedBom) {
		applyItem("");
		return;
	}
	frappe.db
		.get_value("BOM", selectedBom, "item")
		.then((response) => applyItem(response?.message?.item || ""))
		.catch((error) => {
			if (frm.__peaRejectionBomRequestIds[side] === requestId) {
				_notify_call_error(__("Failed to refresh the joint rejection item."), error);
			}
		});
}

function _schedule_joint_rm_consumption(frm) {
	if (frm.__peaJointRmTimer) {
		clearTimeout(frm.__peaJointRmTimer);
		frm.__peaJointRmTimer = null;
	}
	const requestId = (frm.__peaJointRmRequestId || 0) + 1;
	frm.__peaJointRmRequestId = requestId;
	const hasInputs =
		_is_joint_doc(frm.doc) &&
		frm.doc.custom_pea_lh_bom &&
		frm.doc.custom_pea_rh_bom &&
		Number(frm.doc.custom_pea_lh_gross_qty || 0) > 0 &&
		Number(frm.doc.custom_pea_rh_gross_qty || 0) > 0;
	if (!hasInputs) {
		frm.set_value("custom_pea_total_rm_consumption", 0);
		return;
	}
	frm.__peaJointRmTimer = setTimeout(() => {
		frm.__peaJointRmTimer = null;
		_load_joint_rm_consumption(frm, requestId);
	}, JOINT_RM_DEBOUNCE_MS);
}

function _load_joint_rm_consumption(frm, requestId) {
	frappe.call({
		method: "production_entry_app.production_entry_app.api.get_joint_rm_consumption",
		args: {
			lh_bom: frm.doc.custom_pea_lh_bom,
			rh_bom: frm.doc.custom_pea_rh_bom,
			lh_gross_qty: frm.doc.custom_pea_lh_gross_qty,
			rh_gross_qty: frm.doc.custom_pea_rh_gross_qty,
		},
		callback(r) {
			if (requestId !== frm.__peaJointRmRequestId) return;
			frm.set_value("custom_pea_total_rm_consumption", Number(r.message || 0));
		},
		error(error) {
			if (requestId !== frm.__peaJointRmRequestId) return;
			frm.set_value("custom_pea_total_rm_consumption", 0);
			_notify_call_error(__("Failed to calculate Total RM Consumption."), error);
		},
	});
}

function _hide_standard_get_items(frm) {
	// Hide the standard "Get Items" button field — our "Fetch Items" replaces it.
	_hide_native_get_items(frm);
}

function _apply_fetch_items_response(frm, items) {
	if (!items || !items.length) return false;
	frm.clear_table("items");
	items.forEach(function (item) {
		const d = frappe.model.add_child(frm.doc, "Stock Entry Detail", "items");
		Object.keys(item).forEach(function (key) {
			d[key] = item[key];
		});
	});
	frm.refresh_field("items");
	frm.dirty();
	frm.refresh();
	_apply_manufacture_visibility(frm);
	return true;
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
	const isProduction = _is_production_doc(frm.doc);
	_apply_native_manufacture_visibility(frm);
	// Keep this explicit list in sync with Stock Entry custom manufacture-only fields.
	frm.toggle_display(PEA_MANUFACTURE_FIELDS, isProduction);
	frm.toggle_display(PEA_MANUFACTURE_SECTIONS, isProduction);
	frm.toggle_display(NORMAL_ONLY_PEA_FIELDS, isManufacture);
	frm.toggle_display(JOINT_ONLY_PEA_FIELDS, _is_joint_doc(frm.doc));
	if (isProduction) {
		_expand_sections(frm, PEA_MANUFACTURE_SECTIONS);
	}

	_position_rejection_breakup_section(frm);
	_toggle_rejection_breakup(frm);
	_configure_rejection_breakup_grid(frm);
	_update_die_tool_metrics(frm);
}

function _position_rejection_breakup_section(frm) {
	const rejectionSection = frm.fields_dict?.custom_pea_rejection_section;
	const normalFetchSection = frm.fields_dict?.custom_pea_fetch_items?.section;
	const jointResourcesSection = frm.fields_dict?.custom_pea_joint_resources_section;
	const anchorSection = _is_joint_doc(frm.doc) ? jointResourcesSection : normalFetchSection;
	if (
		!rejectionSection?.wrapper ||
		!anchorSection?.wrapper ||
		rejectionSection === anchorSection
	) {
		return;
	}
	rejectionSection.wrapper.insertAfter(anchorSection.wrapper);
}

function _set_prev_purpose(frm) {
	frm.__pea_prev_stock_entry_purpose = _normalize_purpose(
		frm.doc?.custom_pea_stock_entry_purpose
	);
}

function _set_prev_stock_entry_type(frm) {
	frm.__pea_prev_stock_entry_type = frm.doc?.stock_entry_type || "";
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
	if (!_did_leave_manufacture(previousPurpose, currentPurpose) || _is_joint_doc(frm.doc)) {
		return;
	}
	if (frm.__peaJointStockEntryTypeLookup?.stockEntryType === (frm.doc.stock_entry_type || "")) {
		frm.__peaDeferredManufactureCleanup = true;
		return;
	}
	_clear_manufacture_data(frm);
}

function _clear_manufacture_data(frm) {
	_shiftDetailsRequestId++;
	_dieToolRequestId++;
	delete frm.__peaTotalStrokesDefaultState;

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

function _sync_joint_stock_entry_type(
	frm,
	{ source = "checkbox", previousStockEntryType = "" } = {}
) {
	const requestId = ++_jointStockEntryTypeRequestId;
	if (source === "stock_entry_type") {
		const selectedStockEntryType = frm.doc.stock_entry_type || "";
		const applySelectedType = (jointStockEntryType) => {
			if (
				requestId !== _jointStockEntryTypeRequestId ||
				frm.doc.stock_entry_type !== selectedStockEntryType
			) {
				return;
			}
			if (frm.__peaJointStockEntryTypeLookup?.requestId === requestId) {
				delete frm.__peaJointStockEntryTypeLookup;
			}
			frm.__peaJointStockEntryType = jointStockEntryType || "";
			const shouldBeJoint =
				Boolean(jointStockEntryType) && selectedStockEntryType === jointStockEntryType;
			if (frm.__peaDeferredManufactureCleanup) {
				delete frm.__peaDeferredManufactureCleanup;
				if (!shouldBeJoint) {
					_clear_manufacture_data(frm);
				}
			}
			if (shouldBeJoint === _is_joint_doc(frm.doc)) {
				return;
			}

			if (shouldBeJoint) {
				frm.__peaStockEntryTypeBeforeJoint = previousStockEntryType;
			} else {
				delete frm.__peaStockEntryTypeBeforeJoint;
			}
			_clear_production_mode_data(frm);
			frm.doc.custom_pea_is_joint_lh_rh = shouldBeJoint ? 1 : 0;
			frm.refresh_field?.("custom_pea_is_joint_lh_rh");
			frm.dirty?.();
			_apply_manufacture_visibility(frm);
		};

		if (Object.prototype.hasOwnProperty.call(frm, "__peaJointStockEntryType")) {
			applySelectedType(frm.__peaJointStockEntryType);
			return;
		}

		frm.__peaJointStockEntryTypeLookup = {
			requestId,
			stockEntryType: selectedStockEntryType,
		};
		frappe.call({
			method: "production_entry_app.production_entry_app.api.get_joint_stock_entry_type",
			callback(r) {
				applySelectedType(r.message);
			},
			error(error) {
				if (requestId !== _jointStockEntryTypeRequestId) return;
				delete frm.__peaJointStockEntryTypeLookup;
				if (frm.__peaDeferredManufactureCleanup) {
					delete frm.__peaDeferredManufactureCleanup;
					_clear_manufacture_data(frm);
				}
				_notify_call_error(
					__("Failed to identify the Joint LH/RH Stock Entry Type."),
					error
				);
			},
		});
		return;
	}

	if (!_is_joint_doc(frm.doc)) {
		_clear_production_mode_data(frm);
		if (Object.prototype.hasOwnProperty.call(frm, "__peaStockEntryTypeBeforeJoint")) {
			const previousStockEntryType = frm.__peaStockEntryTypeBeforeJoint;
			delete frm.__peaStockEntryTypeBeforeJoint;
			if (frm.doc.stock_entry_type !== previousStockEntryType) {
				frm.set_value("stock_entry_type", previousStockEntryType || "");
			}
		}
		return;
	}
	if (!Object.prototype.hasOwnProperty.call(frm, "__peaStockEntryTypeBeforeJoint")) {
		frm.__peaStockEntryTypeBeforeJoint = frm.doc.stock_entry_type || "";
	}

	frappe.call({
		method: "production_entry_app.production_entry_app.api.get_joint_stock_entry_type",
		callback(r) {
			if (requestId !== _jointStockEntryTypeRequestId || !_is_joint_doc(frm.doc)) return;
			frm.__peaJointStockEntryType = r.message || "";
			_clear_production_mode_data(frm);
			frm.set_value("stock_entry_type", r.message);
		},
		error(error) {
			if (requestId !== _jointStockEntryTypeRequestId || !_is_joint_doc(frm.doc)) return;
			frm.set_value("custom_pea_is_joint_lh_rh", 0);
			_notify_call_error(__("Failed to select the Joint LH/RH Stock Entry Type."), error);
		},
	});
}

function _clear_production_mode_data(frm) {
	_dieToolRequestId++;
	delete frm.__peaTotalStrokesDefaultState;
	frm.__peaJointRmRequestId = (frm.__peaJointRmRequestId || 0) + 1;
	if (frm.__peaJointRmTimer) {
		clearTimeout(frm.__peaJointRmTimer);
		frm.__peaJointRmTimer = null;
	}

	const refreshFieldnames = new Set();
	let changed = false;
	for (const fieldname of PRODUCTION_MODE_SCALAR_FIELDS) {
		if (!Object.prototype.hasOwnProperty.call(frm.doc, fieldname)) continue;
		const fieldtype = frm.get_field?.(fieldname)?.df?.fieldtype || "";
		const clearValue = fieldtype === "Check" ? 0 : "";
		if (frm.doc[fieldname] === clearValue) continue;
		frm.doc[fieldname] = clearValue;
		refreshFieldnames.add(fieldname);
		changed = true;
	}
	for (const fieldname of PRODUCTION_MODE_CLEAR_TABLE_FIELDS) {
		const rows = frm.doc[fieldname];
		if (!Array.isArray(rows) || rows.length === 0) continue;
		if (typeof frm.clear_table === "function") {
			frm.clear_table(fieldname);
		} else {
			frm.doc[fieldname] = [];
		}
		refreshFieldnames.add(fieldname);
		changed = true;
	}
	if (refreshFieldnames.size > 0) {
		frm.refresh_fields?.(Array.from(refreshFieldnames));
	}
	_clear_die_tool_alert(frm);
	if (changed) {
		frm.dirty?.();
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

function _is_joint_doc(doc) {
	return parseInt(doc?.custom_pea_is_joint_lh_rh || 0, 10) === 1;
}

function _is_production_doc(doc) {
	return _is_manufacture_doc(doc) || _is_joint_doc(doc);
}

function _initialize_total_strokes_default_state(frm) {
	const documentName = frm.doc?.name;
	if (
		frm.__peaTotalStrokesDefaultState &&
		frm.__peaTotalStrokesDefaultState.documentName === documentName &&
		frm.__peaTotalStrokesDefaultState.document === frm.doc
	) {
		return frm.__peaTotalStrokesDefaultState;
	}
	const completedQty = Number(frm.doc?.fg_completed_qty || 0);
	frm.__peaTotalStrokesDefaultState = {
		documentName,
		// reload_doc replaces the document object even when its name is unchanged.
		document: frm.doc,
		defaultStrokeValue: completedQty,
	};
	return frm.__peaTotalStrokesDefaultState;
}

function _default_total_strokes_from_fg(frm) {
	if (!_is_manufacture_doc(frm.doc) || _is_joint_doc(frm.doc)) return;
	const state = _initialize_total_strokes_default_state(frm);
	const currentTotalStrokes = Number(frm.doc.custom_pea_total_strokes || 0);
	if (currentTotalStrokes > 0 && currentTotalStrokes !== state.defaultStrokeValue) {
		return;
	}

	const completedQty = Number(frm.doc.fg_completed_qty || 0);
	if (completedQty > 0) {
		const update = frm.set_value("custom_pea_total_strokes", completedQty);
		return Promise.resolve(update).finally(() => {
			state.defaultStrokeValue = completedQty;
		});
	}
}

function _get_time_entry_api() {
	return window.production_entry_app?.time_entry || null;
}

function _sync_stock_entry_helper_fields(frm) {
	const timeEntry = _get_time_entry_api();
	if (!timeEntry || !_is_production_doc(frm.doc)) {
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
	const isProduction = _is_production_doc(frm.doc);
	timeEntry.attach_datetime_split_chips(
		frm,
		"custom_pea_actual_start_date_input",
		"custom_pea_actual_start_time_input",
		"custom_pea_actual_start_date",
		{ get_shift_ctx: () => _get_shift_ctx(frm), enabled: isProduction }
	);
	timeEntry.attach_datetime_split_chips(
		frm,
		"custom_pea_actual_end_date_input",
		"custom_pea_actual_end_time_input",
		"custom_pea_actual_end_date",
		{ get_shift_ctx: () => _get_shift_ctx(frm), enabled: isProduction }
	);
	if (!isProduction) {
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
		_clear_shift_derived_fields(frm, { clearWarehouses: true }).finally(() => {
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
	const isCurrentRequest = () =>
		reqId === _shiftDetailsRequestId && frm.doc.custom_pea_shift === selectedShift;
	_apply_shift_detail_updates(frm, data, { isCurrentRequest }).then((applied) => {
		if (applied && isCurrentRequest()) {
			_sync_stock_entry_helper_fields(frm);
			_setup_stock_entry_quick_entry(frm);
		}
	});
}

async function _apply_shift_detail_updates(
	frm,
	data,
	{ isCurrentRequest = () => true, clearWarehouses = false } = {}
) {
	const warehouseFields = ["from_warehouse", "to_warehouse"];
	const fields = [
		"company",
		"branch",
		"custom_pea_planned_start_date",
		"custom_pea_planned_end_date",
		...warehouseFields,
	];
	for (const fieldname of fields) {
		if (!isCurrentRequest()) {
			return false;
		}
		if (
			warehouseFields.includes(fieldname) &&
			(frm.doc?.work_order || (!clearWarehouses && !data[fieldname]))
		) {
			continue;
		}
		if (Object.prototype.hasOwnProperty.call(data, fieldname)) {
			await _set_form_value_if_present(frm, fieldname, data[fieldname]);
		}
	}
	return true;
}

function _clear_shift_derived_fields(frm, { clearWarehouses = false } = {}) {
	return _apply_shift_detail_updates(
		frm,
		{
			branch: "",
			custom_pea_planned_start_date: "",
			custom_pea_planned_end_date: "",
			from_warehouse: "",
			to_warehouse: "",
		},
		{ clearWarehouses }
	);
}

async function _set_form_value_if_present(frm, fieldname, value) {
	if (frm.fields_dict?.[fieldname]) {
		await frm.set_value(fieldname, value);
	}
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
	if (!_is_production_doc(frm.doc)) {
		frm.toggle_display("custom_pea_rejection_breakup", false);
		frm.toggle_reqd("custom_pea_rejection_breakup", false);
		return;
	}
	const rejection_qty = _get_rejection_qty_for_visibility(frm.doc);
	const has_rejection = rejection_qty > 0;
	const has_breakup_rows = (frm.doc.custom_pea_rejection_breakup || []).length > 0;
	frm.toggle_display("custom_pea_rejection_breakup", has_rejection || has_breakup_rows);
	frm.toggle_reqd("custom_pea_rejection_breakup", has_rejection);
	_configure_rejection_breakup_grid(frm);
}

function _get_rejection_qty_for_visibility(doc) {
	if (_is_joint_doc(doc)) {
		return (
			Number(doc.custom_pea_lh_rejection_qty || 0) +
			Number(doc.custom_pea_rh_rejection_qty || 0)
		);
	}
	return typeof flt === "function" ? flt(doc.custom_pea_rejection_qty) : 0;
}

function _configure_rejection_breakup_grid(frm) {
	const grid = frm.fields_dict?.custom_pea_rejection_breakup?.grid;
	if (!grid) return;
	const isJoint = _is_joint_doc(frm.doc);
	grid.update_docfield_property("output_side", "hidden", isJoint ? 0 : 1);
	grid.update_docfield_property("output_side", "reqd", isJoint ? 1 : 0);
	grid.update_docfield_property("item_code", "hidden", isJoint ? 0 : 1);
}

function _update_die_tool_metrics(frm) {
	if (!_is_production_doc(frm.doc)) return;

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
	if (_is_joint_doc(frm.doc) && frm.doc.custom_pea_die_tool_item) {
		return frm.doc.custom_pea_die_tool_item;
	}
	if (frm.doc.fg_item) return frm.doc.fg_item;
	const items = frm.doc.items || [];
	const fgRow = items.find((row) => row.is_finished_item);
	return fgRow ? fgRow.item_code : null;
}

if (typeof module !== "undefined" && module.exports) {
	module.exports = {
		_normalize_purpose,
		_is_manufacture_doc,
		_is_joint_doc,
		_is_production_doc,
		_did_leave_manufacture,
		_clear_manufacture_data_on_leave,
		_apply_native_manufacture_visibility,
		NATIVE_MANUFACTURE_FIELDS,
		NATIVE_MANUFACTURE_SECTIONS,
		PEA_MANUFACTURE_FIELDS,
		JOINT_ONLY_PEA_FIELDS,
		PEA_MANUFACTURE_SECTIONS,
		MANUFACTURE_FIELDS,
		MANUFACTURE_SECTIONS,
		ALWAYS_HIDDEN_FIELDS,
		ALWAYS_HIDDEN_SECTIONS,
		MANUFACTURE_CLEAR_TABLE_FIELDS,
		_sync_native_get_items_access,
		_apply_shift_detail_updates,
		_apply_fetch_items_response,
		_apply_manufacture_visibility,
		_sync_joint_stock_entry_type,
		_initialize_total_strokes_default_state,
		_default_total_strokes_from_fg,
		_get_rejection_qty_for_visibility,
		_hide_native_get_items,
		_show_native_get_items,
	};
}
