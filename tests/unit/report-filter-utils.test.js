const test = require("node:test");
const assert = require("node:assert/strict");

const { validate_report_date_range } = require("../../production_entry_app/public/js/report_filter_utils.js");

test("validate_report_date_range normalizes inverted date ranges", () => {
	let updatedFromDate = null;
	const report = {
		get_filter_value(fieldname) {
			return {
				from_date: "2026-03-01",
				to_date: "2026-02-28",
			}[fieldname];
		},
		set_filter_value(fieldname, value) {
			if (fieldname === "from_date") {
				updatedFromDate = value;
			}
		},
	};

	validate_report_date_range(report);
	assert.equal(updatedFromDate, "2026-02-28");
});
