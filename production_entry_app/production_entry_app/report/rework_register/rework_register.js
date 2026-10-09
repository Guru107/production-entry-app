frappe.query_reports["Rework Register"] = {
	filters: [
		...(window.production_entry_app?.report_filter_utils?.get_standard_report_date_filters?.() ??
			[]),
		{
			fieldname: "rework_type",
			label: __("Rework Type"),
			fieldtype: "Link",
			options: "Rework Type",
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
		},
		{
			fieldname: "workstation",
			label: __("Workstation"),
			fieldtype: "Link",
			options: "Workstation",
		},
	],
};
