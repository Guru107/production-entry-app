const test = require("node:test");
const assert = require("node:assert/strict");

const {
	get_standard_report_date_filters,
	get_operation_filter,
	get_year_month_filters,
	validate_report_date_range,
	overall_row_formatter,
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

test("get_operation_filter exposes the joint operation link filter", () => {
	global.__ = (text) => text;
	const operationFilter = get_operation_filter();
	assert.equal(operationFilter.fieldname, "custom_pea_operation");
	assert.equal(operationFilter.fieldtype, "Link");
	assert.equal(operationFilter.options, "Operation");
});

test("get_year_month_filters defaults to the current calendar month", (t) => {
	const originalFrappe = global.frappe;
	const originalTranslate = global.__;
	t.after(() => {
		global.frappe = originalFrappe;
		global.__ = originalTranslate;
	});

	global.frappe = {
		datetime: {
			get_today() {
				return "2026-10-04";
			},
			str_to_obj(value) {
				const [year, month, day] = value.split("-").map(Number);
				return new Date(year, month - 1, day);
			},
		},
	};
	global.__ = (text) => text;

	const [yearFilter, monthFilter] = get_year_month_filters();

	assert.equal(yearFilter.fieldname, "year");
	assert.equal(monthFilter.fieldname, "month");
	assert.equal(yearFilter.fieldtype, "Int");
	assert.equal(monthFilter.fieldtype, "Int");
	assert.equal(yearFilter.reqd, 1);
	assert.equal(monthFilter.reqd, 1);
	assert.equal(yearFilter.default, 2026);
	assert.equal(monthFilter.default, 10);
});

test("overall_row_formatter leaves ordinary rows to the default formatter", () => {
	const plain = overall_row_formatter("x", 0, { fieldname: "a" }, { a: "x" }, () => "default");
	assert.equal(plain, "default");
});

test("overall_row_formatter bolds other bold rows without changing their content", () => {
	const html = overall_row_formatter("x", 0, { fieldname: "a" }, { bold: 1 }, () => "default");
	assert.equal(html, "<b>default</b>");
});

test("overall_row_formatter shows the Overall label as plain text, not a date or link", (t) => {
	const originalFrappe = global.frappe;
	t.after(() => {
		global.frappe = originalFrappe;
	});
	global.frappe = { utils: { escape_html: (text) => `esc(${text})` } };
	const data = { bold: 1, is_overall: 1, overall_label_field: "operator", operator: "Overall" };

	const label = overall_row_formatter(
		"Overall",
		0,
		{ fieldname: "operator", fieldtype: "Link" },
		data,
		() => {
			throw new Error("the label column must not go through the typed formatter");
		}
	);
	assert.equal(label, "<b>esc(Overall)</b>");

	const seen = [];
	const value = overall_row_formatter(
		3,
		0,
		{ fieldname: "maintenance_due", fieldtype: "Check" },
		data,
		(_value, _row, column) => {
			seen.push(column.fieldtype);
			return "3";
		}
	);
	assert.equal(value, "<b>3</b>");
	// A Check column holds a count on the Overall Row, so it must not render as a checkbox.
	assert.deepEqual(seen, ["Int"]);
});

test("overall_row_formatter leaves missing values blank instead of formatting them as zero", () => {
	const data = { bold: 1, is_overall: 1, overall_label_field: "item" };
	const blank = overall_row_formatter(
		undefined,
		0,
		{ fieldname: "pct", fieldtype: "Percent" },
		data,
		() => "0.0000%"
	);
	assert.equal(blank, "");
	const zero = overall_row_formatter(
		0,
		0,
		{ fieldname: "pct", fieldtype: "Percent" },
		data,
		() => "0.0000%"
	);
	assert.equal(zero, "<b>0.0000%</b>");
});
