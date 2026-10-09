// Copyright (c) 2026, Gurudatt Kulkarni and contributors
// For license information, please see license.txt

frappe.ui.form.on("Downtime Entry", {
	setup(frm) {
		frm.set_query("custom_pea_downtime_reason", () => ({
			filters: { is_active: 1 },
		}));
	},
});
