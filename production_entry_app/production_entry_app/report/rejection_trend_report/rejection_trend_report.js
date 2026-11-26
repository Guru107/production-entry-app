frappe.query_reports["Rejection Trend Report"] = {
	filters: [
		...(window.production_entry_app?.report_filter_utils?.get_standard_report_date_filters?.() ??
			[]),
		{
			fieldname: "time_grain",
			label: __("Time Grain"),
			fieldtype: "Select",
			options: ["Daily", "Weekly", "Monthly"],
			default: "Daily",
		},
		...(window.production_entry_app?.report_filter_utils?.get_production_dimension_filters?.() ??
			[]),
	],
	formatter: window.production_entry_app?.report_filter_utils?.overall_row_formatter,
};
