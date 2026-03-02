frappe.query_reports["Rework Pareto Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_start(),
			on_change(report) {
				window.production_entry_app?.report_filter_utils?.validate_report_date_range?.(
					report
				);
			},
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_end(),
			on_change(report) {
				window.production_entry_app?.report_filter_utils?.validate_report_date_range?.(
					report
				);
			},
		},
		{
			fieldname: "custom_workstation",
			label: __("Workstation"),
			fieldtype: "Link",
			options: "Workstation",
		},
		{
			fieldname: "custom_shift",
			label: __("Shift"),
			fieldtype: "Link",
			options: "Shift",
		},
		{
			fieldname: "custom_operator",
			label: __("Operator"),
			fieldtype: "Link",
			options: "Operator",
		},
		{
			fieldname: "fg_item",
			label: __("FG Item"),
			fieldtype: "Link",
			options: "Item",
		},
		{
			fieldname: "bom_no",
			label: __("BOM"),
			fieldtype: "Link",
			options: "BOM",
		},
	],
};
