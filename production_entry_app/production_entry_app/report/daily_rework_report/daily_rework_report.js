frappe.query_reports["Daily Rework Report"] = {
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
		{
			fieldname: "operation",
			label: __("Operation"),
			fieldtype: "Link",
			options: "Operation",
		},
		{
			fieldname: "workstation",
			label: __("Workstation"),
			fieldtype: "Link",
			options: "Workstation",
		},
		{
			fieldname: "operator",
			label: __("Operator"),
			fieldtype: "Link",
			options: "Operator",
		},
		{
			fieldname: "rework_type",
			label: __("Rework Type"),
			fieldtype: "Link",
			options: "Rework Type",
		},
	],
	formatter(value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);
		return data && data.bold ? `<b>${formatted}</b>` : formatted;
	},
};
