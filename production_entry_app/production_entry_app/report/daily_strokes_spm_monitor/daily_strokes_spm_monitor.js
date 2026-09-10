frappe.query_reports["Daily Strokes SPM Monitor"] = {
	filters: [
		...(window.production_entry_app?.report_filter_utils?.get_standard_report_date_filters?.() ??
			[]),
		{
			fieldname: "custom_pea_operator",
			label: __("Operator"),
			fieldtype: "Link",
			options: "Operator",
		},
	],
};
