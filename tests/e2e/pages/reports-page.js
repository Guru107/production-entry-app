const { expect } = require("@playwright/test");

class ReportsPage {
	constructor(page) {
		this.page = page;
	}

	async open(reportName) {
		const encodedName = encodeURIComponent(reportName);
		await this.page.goto(`/app/query-report/${encodedName}`);
		await expect(this.page).toHaveURL(new RegExp(`/app/query-report/${encodedName}`));
		await this.page.waitForFunction(
			(name) =>
				Boolean(window.frappe?.query_report) &&
				window.frappe.query_report.report_name === name,
			reportName
		);
		await this.page.waitForFunction(() => {
			const report = window.frappe?.query_report;
			return Boolean(
				report &&
					(Array.isArray(report.filters) ||
						Array.isArray(report.report_settings?.filters))
			);
		});
	}

	async setFilterByFieldname(fieldname, value) {
		await this.page.evaluate(
			async ({ key, val }) => {
				const report = window.frappe?.query_report;
				if (!report) {
					throw new Error("Query report is not loaded.");
				}
				const filter =
					typeof report.get_filter === "function" ? report.get_filter(key) : null;
				if (!filter) {
					throw new Error(`Filter not found by fieldname: ${key}`);
				}
				if (typeof filter.set_value === "function") {
					await filter.set_value(val);
					return;
				}
				if (typeof filter.set_input === "function") {
					filter.set_input(val);
					return;
				}
				throw new Error(`Unsupported filter control for: ${key}`);
			},
			{ key: fieldname, val: value }
		);
	}

	async setFilterByLabel(label, value) {
		await this.page.evaluate(
			async ({ filterLabel, val }) => {
				const report = window.frappe?.query_report;
				if (!report) {
					throw new Error("Query report is not loaded.");
				}
				const filter = (report.filters || []).find(
					(row) => row?.df?.label === filterLabel
				);
				if (!filter) {
					throw new Error(`Filter not found by label: ${filterLabel}`);
				}
				if (typeof filter.set_value === "function") {
					await filter.set_value(val);
					return;
				}
				if (typeof filter.set_input === "function") {
					filter.set_input(val);
					return;
				}
				throw new Error(`Unsupported filter control for label: ${filterLabel}`);
			},
			{ filterLabel: label, val: value }
		);
	}

	async clickRefresh() {
		await this.page.evaluate(async () => {
			const report = window.frappe?.query_report;
			if (!report) {
				throw new Error("Query report is not loaded.");
			}
			if (!Array.isArray(report.filters) && typeof report.setup_filters === "function") {
				await report.setup_filters();
			}
			report.refresh();
			const ajax = report.last_ajax;
			if (ajax && typeof ajax.then === "function") {
				await ajax;
			}
		});
		await this.page.waitForFunction(() => Array.isArray(window.frappe?.query_report?.data));
	}

	async waitForRows(minRows = 1) {
		await this.page.waitForFunction((count) => {
			const rows = window.frappe?.query_report?.data || [];
			return rows.length >= count;
		}, minRows);
	}

	async getRows() {
		return await this.page.evaluate(() => {
			const rows = window.frappe?.query_report?.data || [];
			return rows.map((row) => ({ ...row }));
		});
	}

	async getFilterValues() {
		return await this.page.evaluate(() => {
			const report = window.frappe?.query_report;
			if (!report || typeof report.get_filter_values !== "function") {
				return {};
			}
			return report.get_filter_values() || {};
		});
	}

	async getFirstRowFields(fieldnames) {
		return await this.page.evaluate((keys) => {
			const first = (window.frappe?.query_report?.data || [])[0] || {};
			return keys.reduce((result, key) => {
				result[key] = first[key];
				return result;
			}, {});
		}, fieldnames);
	}

	async runWithDateRange(fromDate, toDate) {
		await this.setFilterByFieldname("from_date", fromDate);
		await this.setFilterByFieldname("to_date", toDate);
		await this.clickRefresh();
	}
}

module.exports = { ReportsPage };
