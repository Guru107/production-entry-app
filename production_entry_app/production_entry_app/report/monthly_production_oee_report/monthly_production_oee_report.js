frappe.query_reports["Monthly Production OEE Report"] = {
	filters: [
		...(window.production_entry_app?.report_filter_utils?.get_year_month_filters?.() ?? []),
		{
			fieldname: "custom_pea_workstation",
			label: __("Workstation"),
			fieldtype: "Link",
			options: "Workstation",
		},
		...(window.production_entry_app?.report_filter_utils?.get_operation_filter?.()
			? [window.production_entry_app.report_filter_utils.get_operation_filter()]
			: []),
		{
			fieldname: "downtime_reason",
			label: __("Downtime Reason"),
			fieldtype: "MultiSelectList",
			options: "Downtime Reason",
			get_data: function (txt) {
				return frappe.db.get_link_options("Downtime Reason", txt, {
					is_active: 1,
				});
			},
		},
	],
};
