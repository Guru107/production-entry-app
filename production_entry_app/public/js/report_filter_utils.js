(() => {
	const PEA = (window.production_entry_app = window.production_entry_app || {});

	function validate_report_date_range(report) {
		const fromDate = report.get_filter_value("from_date");
		const toDate = report.get_filter_value("to_date");
		if (!fromDate || !toDate || fromDate <= toDate) {
			return;
		}
		frappe.msgprint(__("From Date cannot be after To Date."));
		report.set_filter_value("from_date", toDate);
	}

	PEA.report_filter_utils = {
		validate_report_date_range,
	};
})();
