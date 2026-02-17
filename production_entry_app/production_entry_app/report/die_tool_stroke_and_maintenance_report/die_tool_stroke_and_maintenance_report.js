frappe.query_reports["Die Tool Stroke and Maintenance Report"] = {
	filters: [
		{
			fieldname: "item_code",
			label: __("Die Tool Item"),
			fieldtype: "Link",
			options: "Item",
		},
	],
};
