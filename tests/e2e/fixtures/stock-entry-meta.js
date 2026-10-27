const { callFrappeMethod } = require("./frappe");

async function hasStockEntryBranchField(page) {
	// Server-side equivalent of frappe.meta.get_docfield("Stock Entry", "branch"):
	// usable before any Desk page is loaded. branch is host-owned (tests/e2e/README.md).
	const docfields = await callFrappeMethod(page, "frappe.client.get_list", {
		doctype: "DocField",
		fields: JSON.stringify(["name"]),
		filters: JSON.stringify([
			["parent", "=", "Stock Entry"],
			["fieldname", "=", "branch"],
		]),
		limit_page_length: 1,
	});
	if (docfields.length > 0) {
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
