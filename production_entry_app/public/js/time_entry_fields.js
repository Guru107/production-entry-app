// Copyright (c) 2026, Gurudatt Kulkarni and contributors
// For license information, please see license.txt

const INVALID_TIME_MESSAGE = "Enter a valid time in HH:MM format.";

function _pad2(value) {
	return String(value).padStart(2, "0");
}

function parse_time(input) {
	const raw = String(input || "").trim();
	if (!raw) {
		return { hh: "", mm: "", frappe_time: "" };
	}

	let hh;
	let mm;

	if (/^\d{1,2}$/.test(raw)) {
		hh = raw;
		mm = "0";
	} else if (/^\d{3}$/.test(raw)) {
		hh = raw.slice(0, 1);
		mm = raw.slice(1);
	} else if (/^\d{4}$/.test(raw)) {
		hh = raw.slice(0, 2);
		mm = raw.slice(2);
	} else {
		const match = raw.match(/^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$/);
		if (!match) {
			return { error: INVALID_TIME_MESSAGE };
		}
		hh = match[1];
		mm = match[2];
	}

	const hours = Number(hh);
	const minutes = Number(mm);
	if (
		!Number.isInteger(hours) ||
		!Number.isInteger(minutes) ||
		hours < 0 ||
		hours > 23 ||
		minutes < 0 ||
		minutes > 59
	) {
		return { error: INVALID_TIME_MESSAGE };
	}

	const paddedHours = _pad2(hours);
	const paddedMinutes = _pad2(minutes);
	return {
		hh: paddedHours,
		mm: paddedMinutes,
		frappe_time: `${paddedHours}:${paddedMinutes}:00`,
	};
}

function format_time_display(value) {
	const parsed = parse_time(value);
	return parsed.error ? "" : parsed.frappe_time.slice(0, 5);
}

function format_datetime_display(value) {
	const raw = String(value || "").trim();
	if (!raw) {
		return { date: "", time: "" };
	}
	const normalized = raw.replace("T", " ");
	const [datePart, timePart] = normalized.split(" ");
	return {
		date: datePart || "",
		time: format_time_display(timePart || ""),
	};
}

function _set_doc_value(doc, fieldname, value) {
	if (doc && doc[fieldname] !== value) {
		doc[fieldname] = value;
		return true;
	}
	return false;
}

function sync_time_display_from_doc(frm, helperFieldname, canonicalFieldname) {
	if (!frm?.doc) return;
	const displayValue = format_time_display(frm.doc[canonicalFieldname] || "");
	if (_set_doc_value(frm.doc, helperFieldname, displayValue)) {
		frm.refresh_field(helperFieldname);
	}
}

function sync_datetime_display_from_doc(frm, dateHelperFieldname, timeHelperFieldname, canonicalFieldname) {
	if (!frm?.doc) return;
	const display = format_datetime_display(frm.doc[canonicalFieldname] || "");
	let changed = false;
	changed = _set_doc_value(frm.doc, dateHelperFieldname, display.date) || changed;
	changed = _set_doc_value(frm.doc, timeHelperFieldname, display.time) || changed;
	if (changed) {
		frm.refresh_fields([dateHelperFieldname, timeHelperFieldname]);
	}
}

function _diff_minutes(startTime, endTime) {
	const startParts = parse_time(startTime);
	const endParts = parse_time(endTime);
	if (startParts.error || endParts.error || !startParts.frappe_time || !endParts.frappe_time) {
		return "";
	}
	let startMinutes = Number(startParts.hh) * 60 + Number(startParts.mm);
	let endMinutes = Number(endParts.hh) * 60 + Number(endParts.mm);
	if (endMinutes < startMinutes) {
		endMinutes += 24 * 60;
	}
	return endMinutes - startMinutes;
}

function sync_loss_entry_rows(frm, tableFieldname) {
	if (!frm?.doc) return;
	const rows = frm.doc[tableFieldname] || [];
	let changed = false;
	for (const row of rows) {
		const startDisplay = format_time_display(row.start_time || "");
		const endDisplay = format_time_display(row.end_time || "");
		const durationValue =
			row.start_time && row.end_time ? _diff_minutes(row.start_time, row.end_time) : "";
		changed = _set_doc_value(row, "start_time_input", startDisplay) || changed;
		changed = _set_doc_value(row, "end_time_input", endDisplay) || changed;
		changed = _set_doc_value(row, "duration_mins_input", durationValue) || changed;
	}
	if (changed) {
		frm.refresh_field(tableFieldname);
	}
}

function _get_field_wrapper(frm, fieldname) {
	const field = frm?.get_field?.(fieldname);
	const inputArea = field?.$wrapper?.find?.(".control-input-wrapper");
	if (!field || !inputArea?.length) {
		return { field, inputArea: null };
	}
	return { field, inputArea };
}

function bind_committed_time_input(frm, helperFieldname, onCommit) {
	const field = frm?.get_field?.(helperFieldname);
	if (!field?.$input?.length || typeof onCommit !== "function") return;
	field.$input.off("blur.pea_commit").on("blur.pea_commit", () => onCommit(field.$input.val()));
	field.$input.off("keydown.pea_commit").on("keydown.pea_commit", (event) => {
		if (event.key === "Enter") {
			onCommit(field.$input.val());
		}
	});
}

function attach_time_chips(frm, helperFieldname, opts = {}) {
	const { field, inputArea } = _get_field_wrapper(frm, helperFieldname);
	if (!field || !inputArea) return;
	const existing = field.$wrapper.find(".pea-chip-row");
	if (existing.length) existing.remove();

	const row = $(`<div class="pea-chip-row" data-fieldname="${helperFieldname}"></div>`);
	for (const preset of opts.presets || []) {
		const button = $(`<button type="button" class="pea-chip btn btn-default btn-xs"></button>`);
		button.text(preset);
		button.on("click", () => {
			frm.set_value(helperFieldname, preset);
			opts.on_commit?.(preset);
		});
		row.append(button);
	}
	if (opts.show_now) {
		const nowButton = $(
			`<button type="button" class="pea-chip btn btn-default btn-xs">${__("Now")}</button>`
		);
		nowButton.on("click", () => {
			const now = format_time_display(frappe.datetime.now_time());
			frm.set_value(helperFieldname, now);
			opts.on_commit?.(now);
		});
		row.append(nowButton);
	}
	inputArea.after(row);
}

function attach_today_button(frm, fieldname) {
	const { field, inputArea } = _get_field_wrapper(frm, fieldname);
	if (!field || !inputArea) return;
	field.$wrapper.find(".pea-date-row").remove();
	const row = $(`<div class="pea-chip-row pea-date-row"></div>`);
	const button = $(
		`<button type="button" class="pea-chip btn btn-default btn-xs">${__("Today")}</button>`
	);
	button.on("click", () => frm.set_value(fieldname, frappe.datetime.get_today()));
	row.append(button);
	inputArea.after(row);
}

function _get_shift_chip_values(canonicalFieldname, shiftCtx) {
	if (!shiftCtx) {
		return [];
	}
	const isStartField = canonicalFieldname.includes("start");
	const shiftValue = isStartField ? shiftCtx.start : shiftCtx.end;
	const label = isStartField ? __("Shift Start") : __("Shift End");
	const values = [];
	if (shiftValue) {
		values.push({ label, value: shiftValue });
	}
	return values;
}

function attach_datetime_split_chips(
	frm,
	dateHelperFieldname,
	timeHelperFieldname,
	canonicalFieldname,
	opts = {}
) {
	const { field, inputArea } = _get_field_wrapper(frm, timeHelperFieldname);
	if (!field || !inputArea) return;
	field.$wrapper.find(".pea-datetime-row").remove();
	if (!opts.enabled) return;

	const row = $(`<div class="pea-chip-row pea-datetime-row"></div>`);
	const shiftCtx = opts.get_shift_ctx?.() || null;
	for (const chip of _get_shift_chip_values(canonicalFieldname, shiftCtx)) {
		const button = $(`<button type="button" class="pea-chip btn btn-default btn-xs"></button>`);
		button.text(chip.label);
		button.on("click", () => {
			const display = format_datetime_display(chip.value);
			frm.set_value(dateHelperFieldname, display.date);
			frm.set_value(timeHelperFieldname, display.time);
			frm.set_value(canonicalFieldname, chip.value);
		});
		row.append(button);
	}
	const nowButton = $(
		`<button type="button" class="pea-chip btn btn-default btn-xs">${__("Now")}</button>`
	);
	nowButton.on("click", () => {
		const now = frappe.datetime.now_datetime();
		const display = format_datetime_display(now);
		frm.set_value(dateHelperFieldname, display.date);
		frm.set_value(timeHelperFieldname, display.time);
		frm.set_value(canonicalFieldname, now);
	});
	row.append(nowButton);
	inputArea.after(row);
}

function _set_field_invalid(frm, fieldname, message) {
	const field = frm?.get_field?.(fieldname);
	if (!field) return;
	field.df.invalid = message ? 1 : 0;
	field.set_invalid();
	field.set_description(message || "");
}

function _refresh_child_table(doc, cdt, cdn) {
	if (typeof frappe === "undefined") return;
	const grid = frappe.get_meta?.(cdt)?.istable ? frappe.model.get_doc(cdt, cdn) : null;
	if (!grid) return;
}

function _to_time_string(hours, minutes) {
	return `${_pad2(hours)}:${_pad2(minutes)}:00`;
}

function _add_minutes_to_time(startTime, durationMins) {
	const parsed = parse_time(startTime);
	if (parsed.error || !parsed.frappe_time) return "";
	const totalMinutes = Number(parsed.hh) * 60 + Number(parsed.mm) + Number(durationMins || 0);
	const hours = Math.floor(((totalMinutes % (24 * 60)) + 24 * 60) % (24 * 60) / 60);
	const minutes = ((totalMinutes % 60) + 60) % 60;
	return _to_time_string(hours, minutes);
}

function _loss_entry_alert(message) {
	if (typeof frappe !== "undefined") {
		frappe.show_alert({ message, indicator: "red" }, 3);
	}
}

function _set_child_value(cdt, cdn, fieldname, value) {
	if (typeof frappe === "undefined") return;
	const row = frappe.get_doc(cdt, cdn);
	if (row) {
		row[fieldname] = value;
	}
}

function _handle_loss_entry_start(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const parsed = parse_time(row.start_time_input);
	if (parsed.error) {
		_loss_entry_alert(parsed.error);
		return;
	}
	_set_child_value(cdt, cdn, "start_time", parsed.frappe_time);
	_set_child_value(cdt, cdn, "start_time_input", format_time_display(parsed.frappe_time));
	if (row.duration_mins_input) {
		const endTime = _add_minutes_to_time(parsed.frappe_time, row.duration_mins_input);
		_set_child_value(cdt, cdn, "end_time", endTime);
		_set_child_value(cdt, cdn, "end_time_input", format_time_display(endTime));
	} else if (row.end_time) {
		_set_child_value(cdt, cdn, "duration_mins_input", _diff_minutes(row.start_time, row.end_time));
	}
	refresh_field(frm.fields_dict?.[row.parentfield]?.grid?.df?.fieldname || row.parentfield);
}

function _handle_loss_entry_duration(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	if (!row.start_time || !(Number(row.duration_mins_input) > 0)) return;
	const endTime = _add_minutes_to_time(row.start_time, row.duration_mins_input);
	_set_child_value(cdt, cdn, "end_time", endTime);
	_set_child_value(cdt, cdn, "end_time_input", format_time_display(endTime));
	refresh_field(frm.fields_dict?.[row.parentfield]?.grid?.df?.fieldname || row.parentfield);
}

function _handle_loss_entry_end(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const parsed = parse_time(row.end_time_input);
	if (parsed.error) {
		_loss_entry_alert(parsed.error);
		return;
	}
	_set_child_value(cdt, cdn, "end_time", parsed.frappe_time);
	_set_child_value(cdt, cdn, "end_time_input", format_time_display(parsed.frappe_time));
	if (row.start_time) {
		_set_child_value(cdt, cdn, "duration_mins_input", _diff_minutes(row.start_time, row.end_time));
	}
	refresh_field(frm.fields_dict?.[row.parentfield]?.grid?.df?.fieldname || row.parentfield);
}

if (typeof frappe !== "undefined" && frappe.ui?.form) {
	frappe.ui.form.on("Loss Entry", {
		start_time_input(frm, cdt, cdn) {
			_handle_loss_entry_start(frm, cdt, cdn);
		},
		duration_mins_input(frm, cdt, cdn) {
			_handle_loss_entry_duration(frm, cdt, cdn);
		},
		end_time_input(frm, cdt, cdn) {
			_handle_loss_entry_end(frm, cdt, cdn);
		},
	});
}

const api = {
	parse_time,
	format_time_display,
	format_datetime_display,
	sync_time_display_from_doc,
	sync_datetime_display_from_doc,
	sync_loss_entry_rows,
	bind_committed_time_input,
	attach_time_chips,
	attach_today_button,
	attach_datetime_split_chips,
	set_field_invalid: _set_field_invalid,
};

if (typeof window !== "undefined") {
	window.production_entry_app = window.production_entry_app || {};
	window.production_entry_app.time_entry = api;
}

if (typeof module !== "undefined" && module.exports) {
	module.exports = api;
}
