frappe.query_reports["Workstation Rejection Reason Matrix"] = {
	filters: [
		...(window.production_entry_app?.report_filter_utils?.get_standard_report_date_filters?.() ??
			[]),
		{
			fieldname: "top_n_reasons",
			label: __("Top N Reasons"),
			fieldtype: "Int",
			default: 10,
			min_value: 1,
			max_value: 20,
		},
		...(window.production_entry_app?.report_filter_utils?.get_production_dimension_filters?.() ??
			[]),
	],
	formatter: window.production_entry_app?.report_filter_utils?.overall_row_formatter,
};
