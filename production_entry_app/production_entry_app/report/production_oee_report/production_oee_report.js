function _validate_report_date_range(report) {
	const fromDate = report.get_filter_value("from_date");
	const toDate = report.get_filter_value("to_date");
	if (!fromDate || !toDate || fromDate <= toDate) {
		return;
	}
	frappe.msgprint(__("From Date cannot be after To Date."));
	report.set_filter_value("from_date", toDate);
}

frappe.query_reports["Production OEE Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_start(),
			on_change(report) {
				_validate_report_date_range(report);
			},
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_end(),
			on_change(report) {
				_validate_report_date_range(report);
			},
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
			fieldname: "custom_workstation",
			label: __("Workstation"),
			fieldtype: "Link",
			options: "Workstation",
		},
		{
			fieldname: "fg_item",
			label: __("Die Tool Item"),
			fieldtype: "Link",
			options: "Item",
		},
	],
};
