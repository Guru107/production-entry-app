const test = require("node:test");
const assert = require("node:assert/strict");

const {
	get_standard_report_date_filters,
	validate_report_date_range,
} = require("../../production_entry_app/public/js/report_filter_utils.js");

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

test("get_standard_report_date_filters includes required date filters", (t) => {
	const originalFrappe = global.frappe;
	const originalTranslate = global.__;
	t.after(() => {
		global.frappe = originalFrappe;
		global.__ = originalTranslate;
	});

	global.frappe = {
		datetime: {
			month_start() {
				return "2026-06-01";
			},
			month_end() {
				return "2026-06-30";
			},
		},
	};
	global.__ = (text) => text;

	const [fromDateFilter, toDateFilter] = get_standard_report_date_filters();

	assert.equal(fromDateFilter.fieldname, "from_date");
	assert.equal(toDateFilter.fieldname, "to_date");
	assert.equal(fromDateFilter.default, "2026-06-01");
	assert.equal(toDateFilter.default, "2026-06-30");
	assert.equal(fromDateFilter.on_change, validate_report_date_range);
	assert.equal(toDateFilter.on_change, validate_report_date_range);
});
