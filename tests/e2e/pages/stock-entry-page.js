const { expect } = require("@playwright/test");
const {
	callFrappeMethod,
	retryOnContextDestroyed,
	saveForm,
	setFieldValue,
} = require("../fixtures/frappe");
const { hasCurrentStockEntryBranchField } = require("../fixtures/stock-entry-meta");
const { escapeRegexLiteral, getRoute, getRoutePrefix } = require("../utils/routing");

const STOCK_ENTRY_READY_TIMEOUT_MS = 10_000;
const FETCH_ITEMS_CALL_TIMEOUT_MS = 5_000;

function isStockEntryReady(requireAjaxIdle) {
	if (document.querySelector(".modal.show")) {
		return true;
	}
	const frm = window.cur_frm;
	if (frm?.doctype !== "Stock Entry" || !frm?.is_new?.()) {
		return false;
	}
	return !requireAjaxIdle || window.frappe?.request?.ajax_count === 0;
}

function triggerFetchItems() {
	return window.cur_frm?.script_manager?.trigger("custom_pea_fetch_items");
}

// Runs inside the page, so it must stay self-contained for Playwright serialization.
// It is the single source of the Fetch Items completion state; the other predicates
// receive its serialized source instead of re-implementing it. A red indicator marks a
// Frappe error dialog. Dialogs raised by unrelated form lookups through the app's plain
// message convention carry no indicator and must not fail a fetch whose RPC succeeded;
// the RPC error path in waitForFetchItemsCall is the primary guard for the fetch itself.
function getVisibleFetchItemsState() {
	const modal = document.querySelector(".modal.show");
	return {
		hasErrorIndicator: Boolean(modal?.querySelector?.(".indicator.red, .indicator-pill.red")),
		hasMessageDialog: Boolean(modal),
		itemCount: (window.cur_frm?.doc?.items || []).length,
		modalText: modal ? (modal.innerText || modal.textContent || "").trim() : "",
	};
}

function hasVisibleFetchItemsMessage(stateSource) {
	return Function(`return (${stateSource})`)()().hasMessageDialog;
}

async function waitForFetchItemsCall({ stateSource, timeoutMs }) {
	const getState = Function(`return (${stateSource})`)();
	const fetchMethods = new Set([
		"production_entry_app.production_entry_app.api.get_items_with_rejection",
		"production_entry_app.production_entry_app.api.get_joint_production_items",
	]);
	const originalCall = window.frappe?.call;
	if (typeof originalCall !== "function") {
		throw new Error("frappe.call is not available.");
	}
	let restoreCall = () => {
		window.frappe.call = originalCall;
		restoreCall = () => {};
	};
	let rejectFetchResult = (error) => {
		throw error;
	};
	const fetchResult = new Promise((resolve, reject) => {
		rejectFetchResult = reject;
		const timeout = setTimeout(() => {
			reject(
				new Error(
					`Fetch Items did not call the server. State: ${JSON.stringify(getState())}`
				)
			);
		}, timeoutMs);

		window.frappe.call = function (options) {
			const method = typeof options === "string" ? options : options?.method;
			if (!fetchMethods.has(method)) {
				return originalCall.apply(this, arguments);
			}

			const wrappedOptions = { ...options };
			const originalCallback = options.callback;
			const originalError = options.error;
			wrappedOptions.callback = async function (response) {
				try {
					clearTimeout(timeout);
					await originalCallback?.apply(this, arguments);
					resolve({
						rowCount: Array.isArray(response?.message)
							? response.message.length
							: null,
					});
				} catch (error) {
					clearTimeout(timeout);
					reject(error);
				}
			};
			wrappedOptions.error = function (error) {
				try {
					originalError?.apply(this, arguments);
				} finally {
					clearTimeout(timeout);
					reject(
						new Error(
							`Fetch Items call failed. State: ${JSON.stringify(
								getState()
							)} Error: ${JSON.stringify(error || {})}`
						)
					);
				}
			};
			return originalCall.call(this, wrappedOptions);
		};
	});

	try {
		const triggerResult = window.cur_frm?.script_manager?.trigger("custom_pea_fetch_items");
		if (triggerResult?.catch) {
			triggerResult.catch((error) => rejectFetchResult(error));
		}
		const result = await fetchResult;
		await window.frappe.after_ajax?.();
		return { ...result, ...getState() };
	} finally {
		restoreCall();
	}
}

async function waitForStockEntryReady(page) {
	await retryOnContextDestroyed(
		page,
		async () => {
			await page.waitForFunction(isStockEntryReady, false, {
				timeout: STOCK_ENTRY_READY_TIMEOUT_MS,
			});
			await page.waitForFunction(isStockEntryReady, true, {
				timeout: STOCK_ENTRY_READY_TIMEOUT_MS,
			});
		},
		5
	);
}

class StockEntryPage {
	constructor(page) {
		this.page = page;
	}

	async openNew() {
		await this.page.goto(getRoute("/stock-entry/new"));
		await expect(this.page).toHaveURL(
			new RegExp(`/${getRoutePrefix()}/stock-entry/(?:new|new-stock-entry-)`)
		);
		await waitForStockEntryReady(this.page);
		await expect(this.page.locator(".modal.show")).toHaveCount(0);
	}

	async open(name) {
		const encodedName = encodeURIComponent(name);
		await this.page.goto(getRoute(`/stock-entry/${encodedName}`));
		// v16 may append anchor fragment like #tab_overview
		await expect(this.page).toHaveURL(
			new RegExp(
				`${getRoutePrefix()}/stock-entry/${escapeRegexLiteral(encodedName)}(?:\\#.*)?$`
			)
		);
		await this.page.waitForFunction((docname) => window.cur_frm?.doc?.name === docname, name);
	}

	async openInDesk(name) {
		// Preserve the Desk and its reused Stock Entry form instance.
		await this.page.evaluate(async (docname) => {
			await frappe.set_route("Form", "Stock Entry", docname);
			await frappe.after_ajax();
		}, name);
		await this.page.waitForFunction((docname) => window.cur_frm?.doc?.name === docname, name);
	}

	async reload() {
		await this.page.evaluate(async () => {
			await window.cur_frm.reload_doc();
			await frappe.after_ajax();
		});
	}

	async fillManufactureEntry(ctx) {
		await setFieldValue(this.page, "stock_entry_type", "Manufacture");
		await setFieldValue(this.page, "custom_pea_stock_entry_purpose", "Manufacture");
		await setFieldValue(this.page, "company", ctx.company);
		await this.setPostingDate(ctx.shift_date);
		await setFieldValue(this.page, "from_bom", 1);
		await setFieldValue(this.page, "bom_no", ctx.bom);
		await setFieldValue(this.page, "custom_pea_shift", ctx.shift_name);
		await setFieldValue(this.page, "from_warehouse", ctx.wip_warehouse);
		await setFieldValue(this.page, "to_warehouse", ctx.wip_warehouse);
		await setFieldValue(this.page, "fg_completed_qty", 100);
		await setFieldValue(this.page, "custom_pea_rejection_qty", 5);
		await setFieldValue(this.page, "custom_pea_workstation", ctx.workstation);
		await setFieldValue(this.page, "custom_pea_operator", ctx.operator);
		await setFieldValue(
			this.page,
			"custom_pea_actual_start_date",
			`${ctx.shift_date} 08:00:00`
		);
		await setFieldValue(this.page, "custom_pea_actual_end_date", `${ctx.shift_date} 09:00:00`);
	}

	async setManufactureFields(ctx, options = {}) {
		const {
			fgQty = 100,
			rejectionQty = 0,
			shiftName = ctx.shift_name,
			actualStart = `${ctx.shift_date} 08:00:00`,
			actualEnd = `${ctx.shift_date} 09:00:00`,
		} = options;

		await setFieldValue(this.page, "stock_entry_type", "Manufacture");
		await setFieldValue(this.page, "custom_pea_stock_entry_purpose", "Manufacture");
		await setFieldValue(this.page, "company", ctx.company);
		await this.setPostingDate(options.postingDate || ctx.shift_date);
		await setFieldValue(this.page, "from_bom", 1);
		await setFieldValue(this.page, "bom_no", ctx.bom);
		await setFieldValue(this.page, "custom_pea_shift", shiftName);
		await setFieldValue(
			this.page,
			"from_warehouse",
			options.fromWarehouse || ctx.wip_warehouse
		);
		await setFieldValue(this.page, "to_warehouse", options.toWarehouse || ctx.wip_warehouse);
		await setFieldValue(this.page, "fg_completed_qty", fgQty);
		await setFieldValue(this.page, "custom_pea_rejection_qty", rejectionQty);
		await setFieldValue(this.page, "custom_pea_workstation", ctx.workstation);
		await setFieldValue(this.page, "custom_pea_operator", ctx.operator);
		if (actualStart !== null && actualStart !== undefined) {
			await setFieldValue(this.page, "custom_pea_actual_start_date", actualStart);
		}
		if (actualEnd !== null && actualEnd !== undefined) {
			await setFieldValue(this.page, "custom_pea_actual_end_date", actualEnd);
		}
	}

	async setPostingDate(postingDate) {
		if (!postingDate) {
			return;
		}
		await setFieldValue(this.page, "set_posting_time", 1);
		await setFieldValue(this.page, "posting_date", postingDate);
		await setFieldValue(this.page, "posting_time", "09:00:00");
	}

	async fillJointProductionFields(ctx, options = {}) {
		await setFieldValue(this.page, "custom_pea_lh_bom", ctx.joint_lh_bom);
		await setFieldValue(this.page, "custom_pea_lh_gross_qty", options.lhGrossQty ?? 40);
		await setFieldValue(this.page, "custom_pea_lh_rejection_qty", options.lhRejectionQty ?? 0);
		await setFieldValue(this.page, "custom_pea_rh_bom", ctx.joint_rh_bom);
		await setFieldValue(this.page, "custom_pea_rh_gross_qty", options.rhGrossQty ?? 41);
		await setFieldValue(this.page, "custom_pea_rh_rejection_qty", options.rhRejectionQty ?? 0);
		await setFieldValue(this.page, "custom_pea_total_strokes", options.totalStrokes ?? 41);
		await setFieldValue(this.page, "custom_pea_die_tool_item", ctx.joint_lh_item);
		await setFieldValue(this.page, "custom_pea_workstation", ctx.workstation);
		await setFieldValue(this.page, "custom_pea_operator", ctx.operator);
		await setFieldValue(
			this.page,
			"custom_pea_actual_start_date",
			options.actualStart || `${ctx.shift_date} 08:00:00`
		);
		await setFieldValue(
			this.page,
			"custom_pea_actual_end_date",
			options.actualEnd || `${ctx.shift_date} 09:00:00`
		);
	}

	async setShift(shiftName) {
		await setFieldValue(this.page, "custom_pea_shift", shiftName);
	}

	async clearShift() {
		await this.page.evaluate(async () => {
			await cur_frm.set_value("custom_pea_shift", null);
		});
	}

	async waitForShiftAutoFill({
		branch,
		plannedStartIncludes,
		plannedEndIncludes,
		warehouse,
		fromWarehouse,
		toWarehouse,
	}) {
		const hasBranchField = await hasCurrentStockEntryBranchField(this.page);
		await this.page.waitForFunction(
			({
				expectedBranch,
				hasBranchField,
				expectedFromWarehouse,
				expectedToWarehouse,
				startSnippet,
				endSnippet,
			}) => {
				const doc = window.cur_frm?.doc || {};
				const plannedStart = String(doc.custom_pea_planned_start_date || "");
				const plannedEnd = String(doc.custom_pea_planned_end_date || "");
				const branchMatch =
					expectedBranch && hasBranchField ? doc.branch === expectedBranch : true;
				const fromWarehouseMatch = expectedFromWarehouse
					? doc.from_warehouse === expectedFromWarehouse
					: true;
				const toWarehouseMatch = expectedToWarehouse
					? doc.to_warehouse === expectedToWarehouse
					: true;
				const startMatch = startSnippet ? plannedStart.includes(startSnippet) : true;
				const endMatch = endSnippet ? plannedEnd.includes(endSnippet) : true;
				return (
					branchMatch && fromWarehouseMatch && toWarehouseMatch && startMatch && endMatch
				);
			},
			{
				expectedBranch: branch || null,
				hasBranchField,
				expectedFromWarehouse: fromWarehouse || warehouse || null,
				expectedToWarehouse: toWarehouse || warehouse || null,
				startSnippet: plannedStartIncludes || null,
				endSnippet: plannedEndIncludes || null,
			}
		);
	}

	async waitForShiftCleared() {
		await this.page.waitForFunction(() => {
			const doc = window.cur_frm?.doc || {};
			return (
				!doc.custom_pea_shift &&
				!doc.custom_pea_planned_start_date &&
				!doc.custom_pea_planned_end_date &&
				!doc.from_warehouse &&
				!doc.to_warehouse
			);
		});
	}

	async getFieldValues(fieldnames) {
		return await this.page.evaluate((keys) => {
			const doc = window.cur_frm?.doc || {};
			return keys.reduce((acc, key) => {
				acc[key] = doc[key];
				return acc;
			}, {});
		}, fieldnames);
	}

	async fillHelperField(fieldname, value) {
		const input = this.page.locator(`[data-fieldname="${fieldname}"] input`).first();
		await input.waitFor({ state: "visible" });
		await input.fill(value);
		await input.blur();
	}

	async clickFieldChip(fieldname, label) {
		const button = this.page
			.locator(`[data-fieldname="${fieldname}"] .pea-chip-row .pea-chip`)
			.filter({ hasText: label })
			.first();
		await button.click();
	}

	async waitForFieldValue(fieldname, expectedValue) {
		await this.page.waitForFunction(
			({ name, value }) => {
				const doc = window.cur_frm?.doc || {};
				return doc[name] === value;
			},
			{ name: fieldname, value: expectedValue }
		);
	}

	async setRejectionBreakupRows(rows) {
		await this.page.evaluate((dataRows) => {
			cur_frm.clear_table("custom_pea_rejection_breakup");
			for (const row of dataRows) {
				cur_frm.add_child("custom_pea_rejection_breakup", row);
			}
			cur_frm.refresh_field("custom_pea_rejection_breakup");
		}, rows);
	}

	async addUnplannedLossRow(row) {
		await this.page.evaluate((data) => {
			cur_frm.add_child("custom_pea_unplanned_losses", data);
			cur_frm.refresh_field("custom_pea_unplanned_losses");
		}, row);
	}

	async setUnplannedLossHelperRow(rowIndex, values) {
		await this.page.evaluate(
			async ({ index, updates }) => {
				const frm = window.cur_frm;
				const row = frm?.doc?.custom_pea_unplanned_losses?.[index];
				if (!frm || !row) {
					throw new Error("Unplanned loss row not found.");
				}
				const normalizedUpdates = { ...updates };
				const timeEntry = window.production_entry_app?.time_entry;
				if (updates.start_time_input && timeEntry?.parse_time) {
					const parsed = timeEntry.parse_time(updates.start_time_input);
					if (parsed?.error) {
						throw new Error(parsed.error);
					}
					normalizedUpdates.start_time = parsed.frappe_time;
					normalizedUpdates.start_time_input = timeEntry.format_time_display(
						parsed.frappe_time
					);
				}
				if (updates.end_time_input && timeEntry?.parse_time) {
					const parsed = timeEntry.parse_time(updates.end_time_input);
					if (parsed?.error) {
						throw new Error(parsed.error);
					}
					normalizedUpdates.end_time = parsed.frappe_time;
					normalizedUpdates.end_time_input = timeEntry.format_time_display(
						parsed.frappe_time
					);
				}
				for (const [fieldname, value] of Object.entries(normalizedUpdates)) {
					await frappe.model.set_value(row.doctype, row.name, fieldname, value);
				}
				frm.refresh_field("custom_pea_unplanned_losses");
			},
			{ index: rowIndex, updates: values }
		);
	}

	async saveDraft() {
		await retryOnContextDestroyed(this.page, async () => saveForm(this.page, "Save"), 5);
	}

	async attemptSaveDraft() {
		try {
			await this.saveDraft();
		} catch (error) {
			// Validation errors are asserted by message matchers in tests.
		}
	}

	async searchShiftLinkResults(text) {
		return await retryOnContextDestroyed(this.page, async () => {
			await this.page.waitForFunction(
				() =>
					typeof window.cur_frm?.fields_dict?.custom_pea_shift?.get_query === "function"
			);
			return await this.page.evaluate(async (searchText) => {
				const query = window.cur_frm?.fields_dict?.custom_pea_shift?.get_query?.() || {};
				return await new Promise((resolve, reject) => {
					frappe.call({
						method: "frappe.desk.search.search_link",
						args: {
							doctype: "Shift",
							txt: searchText,
							page_length: 20,
							filters: query.filters || {},
						},
						callback: (r) => resolve(r.message || []),
						error: (err) =>
							reject(
								new Error(err?.message || "Failed to search Shift link options.")
							),
					});
				});
			}, text);
		});
	}

	async fetchItems({ expectValidation = false } = {}) {
		const stateSource = getVisibleFetchItemsState.toString();
		await retryOnContextDestroyed(
			this.page,
			async () => {
				await this.page.waitForFunction(
					() => window.cur_frm?.doctype === "Stock Entry" && Boolean(window.cur_frm?.doc)
				);
				if (expectValidation) {
					await this.page.evaluate(triggerFetchItems);
					await this.page.waitForFunction(hasVisibleFetchItemsMessage, stateSource);
					return;
				}
				const result = await this.page.evaluate(waitForFetchItemsCall, {
					stateSource,
					timeoutMs: FETCH_ITEMS_CALL_TIMEOUT_MS,
				});
				if (!result.itemCount || result.hasErrorIndicator) {
					throw new Error(
						`Fetch Items did not complete cleanly. State: ${JSON.stringify(result)}`
					);
				}
			},
			5
		);
	}

	async isSectionVisible(sectionFieldname) {
		return await this.page.evaluate((fieldname) => {
			const section = (window.cur_frm?.layout?.sections || []).find((entry) => {
				return (entry?.df?.fieldname || "") === fieldname;
			});
			if (!section?.wrapper) return null;
			return !section.wrapper.hasClass("hide-control");
		}, sectionFieldname);
	}

	async waitForSectionVisible(sectionFieldname) {
		await this.page.waitForFunction((fieldname) => {
			const section = (window.cur_frm?.layout?.sections || []).find((entry) => {
				return (entry?.df?.fieldname || "") === fieldname;
			});
			return Boolean(section?.wrapper) && !section.wrapper.hasClass("hide-control");
		}, sectionFieldname);
	}

	async isFieldVisible(fieldname) {
		return await this.page.evaluate((name) => {
			const field = window.cur_frm?.get_field?.(name);
			const wrapper = field?.$wrapper;
			if (!wrapper || !wrapper.length) return null;
			return wrapper.is(":visible") && !wrapper.hasClass("hide-control");
		}, fieldname);
	}

	async setRejectionBreakup() {
		await this.page.evaluate(() => {
			cur_frm.clear_table("custom_pea_rejection_breakup");
			cur_frm.add_child("custom_pea_rejection_breakup", {
				rejection_reason: "Burr",
				qty: 5,
			});
			cur_frm.refresh_field("custom_pea_rejection_breakup");
		});
	}

	async saveAndSubmit() {
		await saveForm(this.page, "Save");
		const name = await this.page.evaluate(() => cur_frm.doc.name);
		const doc = await callFrappeMethod(this.page, "frappe.client.get", {
			doctype: "Stock Entry",
			name,
		});
		await callFrappeMethod(this.page, "frappe.client.submit", { doc: JSON.stringify(doc) });
	}
}

module.exports = {
	getVisibleFetchItemsState,
	hasVisibleFetchItemsMessage,
	isStockEntryReady,
	StockEntryPage,
	triggerFetchItems,
	waitForStockEntryReady,
	waitForFetchItemsCall,
};
