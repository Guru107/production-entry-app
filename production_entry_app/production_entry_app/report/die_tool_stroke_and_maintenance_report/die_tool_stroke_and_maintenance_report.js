frappe.query_reports["Die Tool Stroke and Maintenance Report"] = {
	filters: [
		{
			fieldname: "item_code",
			label: __("Die Tool Item"),
			fieldtype: "Link",
			options: "Item",
		},
	],
	formatter: window.production_entry_app?.report_filter_utils?.overall_row_formatter,
};
