// Copyright (c) 2026, Gurudatt Kulkarni and contributors
// For license information, please see license.txt

frappe.ui.form.on("Stock Entry", {
	refresh(frm) {
		// Set filter to only show Running shifts
		frm.set_query("custom_shift", function() {
			return {
				filters: [
					["Shift", "status", "=", "Running"]
				]
			};
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
							frm.set_value("custom_branch", data.branch);
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
			frm.set_value("custom_branch", "");
			frm.set_value("custom_planned_start_date", "");
			frm.set_value("custom_planned_end_date", "");
			frm.set_value("from_warehouse", "");
			frm.set_value("to_warehouse", "");
		}
	},
});
