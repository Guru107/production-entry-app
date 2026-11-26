frappe.query_reports["Item BOM Rework Hotspots"] = {
	filters: [
		...(window.production_entry_app?.report_filter_utils?.get_standard_report_date_filters?.() ??
			[]),
		...(window.production_entry_app?.report_filter_utils?.get_production_dimension_filters?.() ??
			[]),
		...(window.production_entry_app?.report_filter_utils?.get_operation_filter?.()
			? [window.production_entry_app.report_filter_utils.get_operation_filter()]
			: []),
	],
	formatter: window.production_entry_app?.report_filter_utils?.overall_row_formatter,
};
