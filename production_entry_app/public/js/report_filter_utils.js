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
	const api = {
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
