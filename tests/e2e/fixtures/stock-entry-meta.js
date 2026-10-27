const { callFrappeMethod } = require("./frappe");

async function hasStockEntryBranchField(page) {
	// Server-side equivalent of frappe.meta.get_docfield("Stock Entry", "branch"):
	// usable before any Desk page is loaded. branch is host-owned (tests/e2e/README.md).
	// v15 rejects client.get_list on the DocField child table (check_parent_permission),
	// so read the DocType doc for standard fields and query Custom Field (standalone).
	const meta = await callFrappeMethod(page, "frappe.client.get", {
		doctype: "DocType",
		name: "Stock Entry",
	});
	if ((meta.fields || []).some((field) => field.fieldname === "branch")) {
		return true;
	}
	const customFields = await callFrappeMethod(page, "frappe.client.get_list", {
		doctype: "Custom Field",
		fields: JSON.stringify(["name"]),
		filters: JSON.stringify([
			["dt", "=", "Stock Entry"],
			["fieldname", "=", "branch"],
		]),
		limit_page_length: 1,
	});
	return customFields.length > 0;
}

async function hasCurrentStockEntryBranchField(page) {
	return await page.evaluate(() => Boolean(window.cur_frm?.fields_dict?.branch));
}

module.exports = { hasCurrentStockEntryBranchField, hasStockEntryBranchField };
