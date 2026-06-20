frappe.query_reports["Operator Efficiency Report"] = {
	filters: [
		...window.production_entry_app.report_filter_utils.get_standard_report_date_filters(),
		{
			fieldname: "custom_pea_operator",
			label: __("Operator"),
			fieldtype: "Link",
			options: "Operator",
		},
		{
			fieldname: "custom_pea_shift",
			label: __("Shift"),
			fieldtype: "Link",
			options: "Shift",
		},
		{
			fieldname: "custom_pea_workstation",
			label: __("Workstation"),
			fieldtype: "Link",
			options: "Workstation",
		},
		{
			fieldname: "fg_item",
			label: __("Die Tool Item"),
			fieldtype: "Link",
			options: "Item",
		},
	],
};
