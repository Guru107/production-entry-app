frappe.query_reports["Daily Strokes SPM Monitor"] = {
	filters: [
		{
			fieldname: "fiscal_year",
			label: __("Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			reqd: 1,
			default: frappe.defaults.get_user_default("fiscal_year"),
		},
		{
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Select",
			options: [
				"April",
				"May",
				"June",
				"July",
				"August",
				"September",
				"October",
				"November",
				"December",
				"January",
				"February",
				"March",
			].join("\n"),
			reqd: 1,
			default: moment().format("MMMM"),
		},
		{
			fieldname: "custom_operator",
			label: __("Operator"),
			fieldtype: "Link",
			options: "Operator",
		},
	],
};
