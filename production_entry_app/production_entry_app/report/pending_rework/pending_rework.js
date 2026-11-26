frappe.query_reports["Pending Rework"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
		},
		{
			// Data, not Link: Branch read is HR-only and HRMS's Custom DocPerm shadows app DocPerm fixtures.
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Data",
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
		},
	],
};
