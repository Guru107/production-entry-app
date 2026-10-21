const { callFrappeMethod } = require("./frappe");

const JOINT_STOCK_ENTRY_TYPE = "Joint LH RH Production";
const JOINT_PRODUCTION_STOCK_ENTRY_TYPE = "Joint Production";

async function getJointStockEntryType(page) {
	const name = await callFrappeMethod(
		page,
		"production_entry_app.production_entry_app.api.get_joint_stock_entry_type",
		{ required: 1 }
	);
	if (name !== JOINT_STOCK_ENTRY_TYPE) {
		throw new Error(
			`Expected canonical Joint Stock Entry Type ${JOINT_STOCK_ENTRY_TYPE}, got ${name}`
		);
	}
	return name;
}

async function getJointProductionStockEntryType(page) {
	const name = await callFrappeMethod(
		page,
		"production_entry_app.production_entry_app.api.get_joint_production_stock_entry_type"
	);
	if (name !== JOINT_PRODUCTION_STOCK_ENTRY_TYPE) {
		throw new Error(
			`Expected canonical Joint Production Stock Entry Type ${JOINT_PRODUCTION_STOCK_ENTRY_TYPE}, got ${name}`
		);
	}
	return name;
}

module.exports = {
	JOINT_STOCK_ENTRY_TYPE,
	JOINT_PRODUCTION_STOCK_ENTRY_TYPE,
	getJointStockEntryType,
	getJointProductionStockEntryType,
};
