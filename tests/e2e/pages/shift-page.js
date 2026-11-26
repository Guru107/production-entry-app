const { expect } = require("@playwright/test");
const {
	callFrappeMethod,
	saveForm,
	setFieldValue,
	triggerSaveForm,
} = require("../fixtures/frappe");
const {
	escapeRegexLiteral,
	getRoute,
	getRoutePatternSource,
	getRouteRegex,
} = require("../utils/routing");

class ShiftPage {
	constructor(page) {
		this.page = page;
	}

	async runDocAction(methodName) {
		await this.page.evaluate(
			({ action }) =>
				new Promise((resolve, reject) => {
					frappe.call({
						doc: cur_frm.doc,
						method: action,
						callback: () => resolve(true),
						error: (err) => {
							const detail =
								err?._server_messages ||
								err?.message ||
								err?.exc ||
								err?.responseJSON?.message ||
								"";
							reject(new Error(detail || `Failed doc action: ${action}`));
						},
					});
				}),
			{ action: methodName }
		);
	}

	async open(name) {
		const encodedName = encodeURIComponent(name);
		await this.page.goto(getRoute(`/shift/${encodedName}`), { waitUntil: "domcontentloaded" });
		// v16 may append anchor fragment like #tab_overview
		await expect(this.page).toHaveURL(
			new RegExp(
				`${getRoutePatternSource(`/shift/${escapeRegexLiteral(encodedName)}`)}(?:\\#.*)?$`
			)
		);
		await this.page.waitForFunction((docname) => window.cur_frm?.doc?.name === docname, name);
	}

	async openNew() {
		await this.page.goto(getRoute("/shift/new"), { waitUntil: "domcontentloaded" });
		await expect(this.page).toHaveURL(getRouteRegex("/shift/new-shift-"));
		await this.page.waitForFunction(
			() => window.cur_frm?.doctype === "Shift" && window.cur_frm?.is_new?.()
		);
	}

	async createDraftViaApi({
		company,
		department,
		branch,
		date,
		label = "2",
		duration = "8",
		startTime = "10:00:00",
	}) {
		return await callFrappeMethod(this.page, "frappe.client.insert", {
			doc: JSON.stringify({
				doctype: "Shift",
				...(company ? { company } : {}),
				department,
				branch,
				shift_label: label,
				shift_duration: duration,
				shift_date: date,
				planned_start_time: startTime,
			}),
		});
	}

	async setDraftFields({ company, department, branch, date, label, duration, startTime }) {
		if (company !== null && company !== undefined) {
			await setFieldValue(this.page, "company", company);
		}
		if (department !== null && department !== undefined) {
			await setFieldValue(this.page, "department", department);
		}
		if (branch !== null && branch !== undefined) {
			await setFieldValue(this.page, "branch", branch);
		}
		if (label !== null && label !== undefined) {
			await setFieldValue(this.page, "shift_label", String(label));
		}
		if (duration !== null && duration !== undefined) {
			await setFieldValue(this.page, "shift_duration", String(duration));
		}
		if (date !== null && date !== undefined) {
			await setFieldValue(this.page, "shift_date", date);
		}
		if (startTime !== null && startTime !== undefined) {
			await setFieldValue(this.page, "planned_start_time", startTime);
		}
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

	async getFieldValue(fieldname) {
		return await this.page.evaluate((name) => window.cur_frm?.doc?.[name] || "", fieldname);
	}

	async getHelperFieldValue(fieldname) {
		const input = this.page.locator(`[data-fieldname="${fieldname}"] input`).first();
		return await input.inputValue();
	}

	async setPlannedLossHelperRow(rowIndex, values) {
		await this.page.evaluate(
			async ({ index, updates }) => {
				const frm = window.cur_frm;
				const row = frm?.doc?.planned_losses?.[index];
				if (!frm || !row) {
					throw new Error("Planned loss row not found.");
				}
				for (const [fieldname, value] of Object.entries(updates)) {
					await frappe.model.set_value(row.doctype, row.name, fieldname, value);
				}
				frm.refresh_field("planned_losses");
			},
			{ index: rowIndex, updates: values }
		);
	}

	async openPlannedLossRowDialog(rowIndex) {
		await this.page.evaluate((index) => {
			const gridRow = window.cur_frm?.fields_dict?.planned_losses?.grid?.grid_rows?.[index];
			if (!gridRow) {
				throw new Error("Grid row not found.");
			}
			gridRow.toggle_view(true);
		}, rowIndex);
		await this.page
			.locator(".grid-row-open .form-in-grid")
			.first()
			.waitFor({ state: "visible" });
	}

	async closeRowDialog() {
		await this.page.evaluate(() => {
			window.cur_frm?.fields_dict?.planned_losses?.grid?.open_grid_row?.toggle_view(false);
		});
		await this.page.waitForFunction(
			() =>
				window.cur_frm?.fields_dict?.planned_losses?.grid?.open_grid_row?.grid_form?.wrapper?.css(
					"display"
				) === "none"
		);
	}

	async saveDraft() {
		await saveForm(this.page, "Save");
	}

	async attemptSaveDraft() {
		await triggerSaveForm(this.page, "Save");
	}

	async clickStartShiftButton() {
		await this.page.evaluate(() => {
			const button = window.cur_frm?.custom_buttons?.[__("Start Shift")];
			if (!button) {
				throw new Error("Start Shift action button not found on Shift form.");
			}
			button.trigger("click");
		});
	}

	async waitForRename(namePrefix) {
		await this.page.waitForFunction(
			(prefix) => window.cur_frm?.doc?.name?.startsWith(prefix),
			namePrefix
		);
		await expect(this.page).toHaveURL(
			new RegExp(getRoutePatternSource(`/shift/${escapeRegexLiteral(namePrefix)}`))
		);
	}

	async startShift() {
		await this.runDocAction("start_shift");
		await this.page.waitForFunction(() => window.cur_frm?.doc?.status === "Running");
	}

	async cancelShift() {
		await this.runDocAction("cancel_shift");
		await this.page.waitForFunction(() => window.cur_frm?.doc?.status === "Cancelled");
	}

	async createProductionEntryFromShift() {
		await this.page.evaluate(() => {
			const label = __("Production Entry");
			const button = window.cur_frm?.custom_buttons?.[label];
			if (!button) {
				throw new Error("Production Entry action button not found on Shift form.");
			}
			button.trigger("click");
		});
		await expect(this.page).toHaveURL(getRouteRegex("/stock-entry/new-stock-entry-"));
		await this.page.waitForFunction(
			() => window.cur_frm?.doctype === "Stock Entry" && window.cur_frm?.is_new?.()
		);
	}

	async clickActionAndConfirm(label) {
		await this.page.evaluate((buttonLabel) => {
			const button = window.cur_frm?.custom_buttons?.[__(buttonLabel)];
			if (!button) {
				throw new Error(`${buttonLabel} action button not found on Shift form.`);
			}
			button.trigger("click");
		}, label);
		await this.page.locator(".modal:visible").getByRole("button", { name: "Yes" }).click();
	}

	async endShift() {
		await this.runDocAction("end_shift");
		await this.page.waitForFunction(() => window.cur_frm?.doc?.status === "Completed");
	}

	async waitForPlannedLossRows(count, timeoutMs = 30000) {
		await this.page.waitForFunction(
			() => {
				const doc = window.cur_frm?.doc || {};
				return Boolean(doc.shift_duration && doc.planned_start_time && doc.shift_date);
			},
			{ timeout: timeoutMs }
		);
		await this.page.waitForFunction(
			(rowCount) => (window.cur_frm?.doc?.planned_losses || []).length >= rowCount,
			count,
			{ timeout: timeoutMs }
		);
	}

	async getPlannedLosses() {
		return await this.page.evaluate(() =>
			(window.cur_frm?.doc?.planned_losses || []).map((row) => ({
				downtime_reason: row.downtime_reason,
				start_time: row.start_time,
				end_time: row.end_time,
			}))
		);
	}

	async isFieldReadOnly(fieldname) {
		return await this.page.evaluate(
			(name) => Boolean(window.cur_frm?.fields_dict?.[name]?.df?.read_only),
			fieldname
		);
	}

	async hasTodayButton() {
		// Scoped to cur_frm: Frappe keeps previously opened forms in the DOM.
		return await this.page.evaluate(
			() =>
				(window.cur_frm?.fields_dict?.shift_date?.$wrapper?.find(".pea-date-row").length ||
					0) > 0
		);
	}
}

module.exports = { ShiftPage };
