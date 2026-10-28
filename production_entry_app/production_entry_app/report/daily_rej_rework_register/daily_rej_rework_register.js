frappe.query_reports["Daily Rej Rework Register"] = {
	filters: [
		...(window.production_entry_app?.report_filter_utils?.get_standard_report_date_filters?.() ??
			[]),
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
		},
		{
			fieldname: "rejection_reason",
			label: __("Rejection Reason"),
			fieldtype: "Link",
			options: "Rejection Reason",
		},
		...(window.production_entry_app?.report_filter_utils?.get_operation_filter?.()
			? [window.production_entry_app.report_filter_utils.get_operation_filter()]
			: []),
	],
	formatter(value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);
		return data && data.bold ? `<b>${formatted}</b>` : formatted;
	},
};
