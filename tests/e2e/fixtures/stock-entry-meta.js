async function hasStockEntryBranchField(page) {
	return await page.evaluate(async () => {
		await frappe.model.with_doctype("Stock Entry");
		return Boolean(frappe.meta.get_docfield("Stock Entry", "branch"));
	});
}

async function hasCurrentStockEntryBranchField(page) {
	return await page.evaluate(() => Boolean(window.cur_frm?.fields_dict?.branch));
}

module.exports = { hasCurrentStockEntryBranchField, hasStockEntryBranchField };
