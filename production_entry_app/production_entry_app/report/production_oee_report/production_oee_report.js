frappe.query_reports["Production OEE Report"] = {
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
	],
};
