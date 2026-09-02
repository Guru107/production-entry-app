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
	test("@regression shows selected Rework fields when Rework setup is ambiguous", async ({
		page,
	}) => {
		const suffix = Date.now();
		const stockEntryTypes = [
			`${PREFIX}_AMBIGUOUS_A_${suffix}`,
			`${PREFIX}_AMBIGUOUS_B_${suffix}`,
		];
		const createdStockEntryTypes = [];

		await page.goto(getRoute("/home"));
		try {
			for (const name of stockEntryTypes) {
				await callFrappeMethod(page, "frappe.client.insert", {
					doc: JSON.stringify({
						doctype: "Stock Entry Type",
						name,
						purpose: "Material Transfer",
						custom_pea_rework_entry: 1,
					}),
				});
				createdStockEntryTypes.push(name);
			}

			await page.goto(getRoute("/stock-entry/new"));
			await page.waitForFunction(
				() => window.cur_frm?.doctype === "Stock Entry" && window.cur_frm?.is_new?.()
			);

			await setFieldValue(page, "stock_entry_type", stockEntryTypes[0]);
			await expect
				.poll(async () => {
					return await page.evaluate(() => {
						const frm = window.cur_frm;
						return {
							stockEntryType: frm?.doc?.stock_entry_type || "",
							reworkMarker: frm?.doc?.__pea_rework_stock_entry_type || "",
							reworkTypeVisible: Boolean(
								frm
									?.get_field?.("custom_pea_rework_type")
									?.$wrapper?.is(":visible")
							),
							workstationVisible: Boolean(
								frm
									?.get_field?.("custom_pea_rework_workstation")
									?.$wrapper?.is(":visible")
							),
							operatorsVisible: Boolean(
								frm
									?.get_field?.("custom_pea_rework_operators")
									?.$wrapper?.is(":visible")
							),
						};
					});
				})
				.toEqual({
					stockEntryType: stockEntryTypes[0],
					reworkMarker: stockEntryTypes[0],
					reworkTypeVisible: true,
					workstationVisible: true,
					operatorsVisible: true,
				});
			await expect(page.locator(".modal.show")).toHaveCount(0);
		} finally {
			await page.goto(getRoute("/home")).catch(() => {});
			for (const name of createdStockEntryTypes) {
				await deleteDocIfExists(page, "Stock Entry Type", name);
			}
		}
	});

	test("@regression shows, validates, defaults, and clears rework fields", async ({ page }) => {
		const stockEntryPage = new StockEntryPage(page);
		const suffix = Date.now();
		const reworkType = `${PREFIX} ${suffix}`;
		let contextBootstrapped = false;
		const reworkStockEntryType = `${PREFIX} Material Transfer ${suffix}`;
		let createdReworkType = false;
		let createdReworkStockEntryType = false;

		try {
			await page.goto(getRoute("/home"));
			const context = await callFrappeMethod(
				page,
				"production_entry_app.production_entry_app.e2e_api.bootstrap_e2e_context",
				{ prefix: PREFIX }
			);
			contextBootstrapped = true;
			await callFrappeMethod(page, "frappe.client.insert", {
				doc: JSON.stringify({
					doctype: "Stock Entry Type",
					name: reworkStockEntryType,
					purpose: "Material Transfer",
					custom_pea_rework_entry: 1,
				}),
			});
			createdReworkStockEntryType = true;

			await callFrappeMethod(page, "frappe.client.insert", {
				doc: JSON.stringify({
					doctype: "Rework Type",
					rework_type_name: reworkType,
					default_workstation: context.workstation,
				}),
			});
			createdReworkType = true;

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
			await expectValidationError(
				page,
				/Rework Type.*(?:mandatory|required)|Mandatory.*Rework Type/i
			);
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
			if (createdReworkType) {
				await deleteDocIfExists(page, "Rework Type", reworkType);
			}
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
