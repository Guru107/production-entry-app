const { callFrappeMethod } = require("./frappe");

async function deleteJointStockEntryTypeIfExists(page, name) {
	if (!name) return;
	const rows = await callFrappeMethod(page, "frappe.client.get_list", {
		doctype: "Stock Entry Type",
		fields: JSON.stringify(["name"]),
		filters: JSON.stringify({ name }),
		limit_page_length: 1,
	});
	if (rows?.length) {
		await callFrappeMethod(page, "frappe.client.delete", {
			doctype: "Stock Entry Type",
			name,
		});
	}
}

async function ensureJointStockEntryType(page, prefix) {
	const name = `${prefix} Joint LH RH`;
	await deleteJointStockEntryTypeIfExists(page, name);
	await callFrappeMethod(page, "frappe.client.insert", {
		doc: JSON.stringify({
			doctype: "Stock Entry Type",
			name,
			purpose: "Repack",
			custom_pea_joint_lh_rh_production: 1,
		}),
	});
	return name;
}

module.exports = { deleteJointStockEntryTypeIfExists, ensureJointStockEntryType };
