frappe.query_reports["Rework Pareto Report"] = {
	filters: [
		...(window.production_entry_app?.report_filter_utils?.get_standard_report_date_filters?.() ??
			[]),
		...(window.production_entry_app?.report_filter_utils?.get_production_dimension_filters?.() ??
			[]),
	],
};
