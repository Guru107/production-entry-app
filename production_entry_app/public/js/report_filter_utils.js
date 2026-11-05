(function () {
	function get_standard_report_date_filters() {
		return [
			{
				fieldname: "from_date",
				label: __("From Date"),
				fieldtype: "Date",
				reqd: 1,
				default: frappe.datetime.month_start(),
				on_change: validate_report_date_range,
			},
			{
				fieldname: "to_date",
				label: __("To Date"),
				fieldtype: "Date",
				reqd: 1,
				default: frappe.datetime.month_end(),
				on_change: validate_report_date_range,
			},
		];
	}

	function get_operation_filter() {
		return {
			fieldname: "custom_pea_operation",
			label: __("Operation"),
			fieldtype: "Link",
			options: "Operation",
		};
	}

	function get_year_month_filters() {
		const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
		const currentYear = today.getFullYear();
		const currentMonth = today.getMonth() + 1;
		return [
			{
				fieldname: "year",
				label: __("Year"),
				fieldtype: "Int",
				reqd: 1,
				default: currentYear,
			},
			{
				fieldname: "month",
				label: __("Month"),
				fieldtype: "Int",
				reqd: 1,
				default: currentMonth,
			},
		];
	}

	function validate_report_date_range(report) {
		const fromDate = report?.get_filter_value?.("from_date");
		const toDate = report?.get_filter_value?.("to_date");
		if (!fromDate || !toDate || fromDate <= toDate) {
			return;
		}
		if (typeof frappe !== "undefined" && typeof frappe.msgprint === "function") {
			frappe.msgprint(__("From Date cannot be after To Date."));
		}
		if (report && typeof report.set_filter_value === "function") {
			report.set_filter_value("from_date", toDate);
		}
	}

	// Reports ending in an Overall Row (ADR 0010) set `bold` and `is_overall`. Frappe ignores `bold` on
	// its own, and the "Overall" label sits in typed (Date/Link) columns that would blank it or turn it
	// into a link, so format that row by hand.
	function overall_row_formatter(value, row, column, data, default_formatter) {
		if (!data || !data.bold) {
			return default_formatter(value, row, column, data);
		}
		if (!data.is_overall) {
			return `<b>${default_formatter(value, row, column, data)}</b>`;
		}
		if (column.fieldname === data.overall_label_field) {
			return `<b>${frappe.utils.escape_html(value)}</b>`;
		}
		// Columns with no overall figure are blank, not a formatted zero.
		if (value === undefined || value === null || value === "") {
			return "";
		}
		// A Check column holds a count on the Overall Row, so it must not render as a checkbox.
		const display = column.fieldtype === "Check" ? { ...column, fieldtype: "Int" } : column;
		return `<b>${default_formatter(value, row, display, data)}</b>`;
	}

	const api = {
		overall_row_formatter,
		get_standard_report_date_filters,
		get_operation_filter,
		get_year_month_filters,
		validate_report_date_range,
	};

	if (typeof window !== "undefined") {
		const PEA = (window.production_entry_app = window.production_entry_app || {});
		PEA.report_filter_utils = api;
	}

	if (typeof module !== "undefined" && module.exports) {
		module.exports = api;
	}
})();
