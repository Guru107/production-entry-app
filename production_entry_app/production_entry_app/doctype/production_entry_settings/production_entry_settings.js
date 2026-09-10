frappe.ui.form.on("Production Entry Settings", {
	setup(frm) {
		for (const fieldname of [
			"raw_material_warehouse",
			"work_in_progress_warehouse",
			"rejection_warehouse",
			"scrap_warehouse",
		]) {
			frm.set_query(fieldname, "branch_warehouse_defaults", (_doc, cdt, cdn) => ({
				filters: { company: locals[cdt][cdn].company || "", is_group: 0, disabled: 0 },
			}));
		}
	},
});

frappe.ui.form.on("Branch Warehouse Default", {
	company(frm, cdt, cdn) {
		return frappe.model.set_value(cdt, cdn, {
			raw_material_warehouse: "",
			work_in_progress_warehouse: "",
			rejection_warehouse: "",
			scrap_warehouse: "",
		});
	},
});
