const { test, expect } = require("@playwright/test");

const { expectValidationError } = require("../fixtures/assertions");
const { callFrappeMethod, setFieldValue } = require("../fixtures/frappe");
const { StockEntryPage } = require("../pages/stock-entry-page");
const { getRoute } = require("../utils/routing");

const PREFIX = "E2E_REWORK_FIELDS";

async function deleteDocIfExists(page, doctype, name) {
	if (!name) return;
	try {
		await callFrappeMethod(page, "frappe.client.delete", { doctype, name });
	} catch (error) {
		if (!String(error?.message || "").match(/DoesNotExistError|not found/i)) {
			throw error;
		}
	}
}

test.describe("Rework fields on Stock Entry", () => {
	test("@regression shows, validates, defaults, and clears rework fields", async ({ page }) => {
		const stockEntryPage = new StockEntryPage(page);
		const reworkType = `${PREFIX} ${Date.now()}`;
		let contextBootstrapped = false;
		let reworkStockEntryType = "";
		let createdReworkStockEntryType = false;

		try {
			const context = await callFrappeMethod(
				page,
				"production_entry_app.production_entry_app.e2e_api.bootstrap_e2e_context",
				{ prefix: PREFIX }
			);
			contextBootstrapped = true;
			try {
				reworkStockEntryType = await callFrappeMethod(
					page,
					"production_entry_app.production_entry_app.api.get_rework_stock_entry_type"
				);
			} catch (error) {
				if (!String(error?.message || "").match(/Configure a Material Transfer/i)) {
					throw error;
				}
				reworkStockEntryType = `${PREFIX} Material Transfer`;
				await callFrappeMethod(page, "frappe.client.insert", {
					doc: JSON.stringify({
						doctype: "Stock Entry Type",
						name: reworkStockEntryType,
						purpose: "Material Transfer",
						custom_pea_rework_entry: 1,
					}),
				});
				createdReworkStockEntryType = true;
			}

			await callFrappeMethod(page, "frappe.client.insert", {
				doc: JSON.stringify({
					doctype: "Rework Type",
					rework_type_name: reworkType,
					default_workstation: context.workstation,
				}),
			});

			await stockEntryPage.openNew();
			await setFieldValue(page, "stock_entry_type", reworkStockEntryType);
			await page.waitForFunction((expectedType) => {
				const frm = window.cur_frm;
				const field = frm?.get_field?.("custom_pea_rework_type");
				return (
					frm?.doc?.__pea_rework_stock_entry_type === expectedType &&
					field?.$wrapper?.is(":visible")
				);
			}, reworkStockEntryType);

			await stockEntryPage.attemptSaveDraft();
			await expectValidationError(page, /Rework Type.*mandatory|Mandatory.*Rework Type/i);
			await page.keyboard.press("Escape");

			await setFieldValue(page, "custom_pea_rework_type", reworkType);
			await stockEntryPage.waitForFieldValue(
				"custom_pea_rework_workstation",
				context.workstation
			);
			expect(await stockEntryPage.isFieldVisible("custom_pea_rework_operators")).toBe(true);

			await page.evaluate((operator) => {
				cur_frm.add_child("custom_pea_rework_operators", { operator });
				cur_frm.refresh_field("custom_pea_rework_operators");
			}, context.operator);
			await setFieldValue(
				page,
				"custom_pea_rework_actual_start",
				`${context.shift_date} 08:00:00`
			);
			await setFieldValue(
				page,
				"custom_pea_rework_actual_end",
				`${context.shift_date} 09:00:00`
			);

			await setFieldValue(page, "stock_entry_type", "Material Transfer");
			await page.waitForFunction(() => {
				const doc = window.cur_frm?.doc || {};
				return (
					!doc.custom_pea_rework_type &&
					!doc.custom_pea_rework_workstation &&
					!doc.custom_pea_rework_actual_start &&
					!doc.custom_pea_rework_actual_end &&
					(doc.custom_pea_rework_operators || []).length === 0 &&
					!doc.custom_pea_rework_cost
				);
			});
			expect(await stockEntryPage.isFieldVisible("custom_pea_rework_type")).toBe(false);
		} finally {
			await page.goto(getRoute("/home")).catch(() => {});
			await deleteDocIfExists(page, "Rework Type", reworkType);
			if (createdReworkStockEntryType) {
				await deleteDocIfExists(page, "Stock Entry Type", reworkStockEntryType);
			}
			if (contextBootstrapped) {
				await callFrappeMethod(
					page,
					"production_entry_app.production_entry_app.e2e_api.cleanup_e2e_context",
					{ prefix: PREFIX }
				);
			}
		}
	});
});
