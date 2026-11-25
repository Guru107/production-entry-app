// RM Batch Trace: filter setup, published as the Report's `javascript` field.
// Branch comes first; the Sales Invoice dropdown lists only that branch's
// submitted, stock-updating, non-return invoices.
frappe.query_reports["RM Batch Trace"] = {
	filters: [
		{
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Branch",
			reqd: 1,
			on_change() {
				// An invoice picked for another branch no longer fits; clearing it refreshes the report.
				const invoice = frappe.query_report.get_filter("sales_invoice");
				if (invoice.get_value()) {
					invoice.set_value("");
				} else {
					frappe.query_report.refresh();
				}
			},
		},
		{
			fieldname: "sales_invoice",
			label: __("Sales Invoice"),
			fieldtype: "Link",
			options: "Sales Invoice",
			reqd: 1,
			get_query() {
				const branch = frappe.query_report.get_filter_value("branch");
				if (!branch) {
					frappe.throw(__("Select a Branch first."));
				}
				return {
					filters: { branch, docstatus: 1, update_stock: 1, is_return: 0 },
				};
			},
		},
		{
			fieldname: "item",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
		},
	],
};
