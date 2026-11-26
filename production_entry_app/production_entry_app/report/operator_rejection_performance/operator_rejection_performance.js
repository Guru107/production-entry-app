frappe.query_reports["Operator Rejection Performance"] = {
	filters: [
		...(window.production_entry_app?.report_filter_utils?.get_standard_report_date_filters?.() ??
			[]),
		...(window.production_entry_app?.report_filter_utils?.get_production_dimension_filters?.() ??
			[]),
	],
	formatter: window.production_entry_app?.report_filter_utils?.overall_row_formatter,
};
