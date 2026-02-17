const { callFrappeMethod } = require("./frappe");

async function bootstrapE2E(page, prefix = "E2E") {
	return await callFrappeMethod(
		page,
		"production_entry_app.production_entry_app.api.bootstrap_e2e_context",
		{ prefix }
	);
}

async function cleanupE2E(page, prefix = "E2E") {
	return await callFrappeMethod(
		page,
		"production_entry_app.production_entry_app.api.cleanup_e2e_context",
		{ prefix }
	);
}

async function createSubmittedStockEntry(page, prefix = "E2E", rejectionQty = 0) {
	return await callFrappeMethod(
		page,
		"production_entry_app.production_entry_app.api.create_e2e_submitted_stock_entry",
		{ prefix, rejection_qty: rejectionQty }
	);
}

module.exports = {
	bootstrapE2E,
	cleanupE2E,
	createSubmittedStockEntry,
};
