frappe.query_reports["Production OEE Report"] = {
	filters: [
		...(window.production_entry_app?.report_filter_utils?.get_standard_report_date_filters?.() ??
			[]),
		{
			fieldname: "custom_pea_workstation",
			label: __("Workstation"),
			fieldtype: "Link",
			options: "Workstation",
		},
	],
};
