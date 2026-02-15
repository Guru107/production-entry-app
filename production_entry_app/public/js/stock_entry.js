// Copyright (c) 2026, Gurudatt Kulkarni and contributors
// For license information, please see license.txt

/* global erpnext */

// Suppress ERPNext's auto-populate on fg_completed_qty change for Manufacture
// entries so the user can set both Qty to Manufacture and Rejection Qty before
// explicitly clicking "Fetch Items".
if (erpnext.stock && erpnext.stock.StockEntry) {
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
	refresh(frm) {
		// Set filter to only show Running shifts
		frm.set_query("custom_shift", function () {
			return {
				filters: [["Shift", "status", "=", "Running"]],
			};
		});

		frm.toggle_display(["custom_planned_start_date", "custom_planned_end_date"], true);

		// Hide the standard "Get Items" button field — our "Fetch Items" replaces it
		frm.set_df_property("get_items", "hidden", 1);
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
