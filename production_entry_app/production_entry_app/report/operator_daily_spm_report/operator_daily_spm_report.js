frappe.query_reports["Operator Daily SPM Report"] = {
	filters: [
		...window.production_entry_app.report_filter_utils.get_standard_report_date_filters(),
		{
			fieldname: "custom_pea_operator",
			label: __("Operator"),
			fieldtype: "Link",
			options: "Operator",
		},
		{
			fieldname: "custom_pea_workstation",
			label: __("Workstation"),
			fieldtype: "Link",
			options: "Workstation",
		},
		{
			fieldname: "custom_pea_shift",
			label: __("Shift"),
			fieldtype: "Link",
			options: "Shift",
		},
	],
};
