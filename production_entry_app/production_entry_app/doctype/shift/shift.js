// Copyright (c) 2026, Gurudatt Kulkarni and contributors
// For license information, please see license.txt

const PLANNED_BREAKS_DEBOUNCE_MS = 300;
const SHIFT_TIME_PRESETS = ["06:00", "08:00", "14:00", "18:00", "20:00", "22:00", "00:00"];
const WAREHOUSE_FIELDS = [
	"raw_material_warehouse",
	"work_in_progress_warehouse",
	"rejection_warehouse",
	"scrap_warehouse",
];

frappe.ui.form.on("Shift", {
	setup(frm) {
		_set_warehouse_queries(frm);
		_set_department_query(frm);
	},
	company(frm) {
		_set_warehouse_queries(frm);
		_set_department_query(frm);
	},
	planned_start_time(frm) {
		_populate_default_breaks_if_draft(frm);
	},
	shift_duration(frm) {
		_populate_default_breaks_if_draft(frm);
	},
	shift_date(frm) {
		_populate_default_breaks_if_draft(frm);
	},
	refresh(frm) {
		_prepare_shift_form(frm);
		_add_status_action_buttons(frm);
		_add_create_buttons(frm);
		_render_shift_sections(frm);
	},
});

function _prepare_shift_form(frm) {
	frm.set_df_property("planned_losses", "read_only", frm.doc.status !== "Draft");
	_set_warehouse_field_editability(frm);
	_toggle_company_field_visibility(frm);
	_set_warehouse_queries(frm);
	_set_department_query(frm);
	frm.after_save = () => {
		_render_shift_summary(frm);
		_render_aggregate_production_entries(frm);
	};
}

function _add_status_action_buttons(frm) {
	const actionsGroup = __("Actions");
	if (frm.doc.status === "Draft") {
		_add_shift_action_button(frm, __("Start Shift"), "start_shift", actionsGroup);
		_add_cancel_shift_button(frm, actionsGroup);
		return;
	}
	if (frm.doc.status === "Completed") {
		_add_cancel_shift_button(frm, actionsGroup);
		return;
	}
	if (frm.doc.status === "Running") {
		frm.add_custom_button(
			__("End Shift"),
			() => {
				frappe.confirm(
					__(
						"End this shift? You can still add post-facto production entries after ending."
					),
					() => {
						_call_shift_transition(frm, "end_shift");
					}
				);
			},
			actionsGroup
		);
	}
}

function _add_cancel_shift_button(frm, actionsGroup) {
	frm.add_custom_button(
		__("Cancel"),
		() => {
			frappe.confirm(__("Cancel this shift?"), () => {
				_call_shift_transition(frm, "cancel_shift");
			});
		},
		actionsGroup
	);
}

function _add_shift_action_button(frm, label, method, group) {
	frm.add_custom_button(
		label,
		() => {
			_call_shift_transition(frm, method);
		},
		group
	);
}

function _call_shift_transition(frm, method) {
	frm.call({
		method,
		doc: frm.doc,
		freeze: true,
		callback: () => {
			frm.reload_doc();
		},
	});
}

function _add_create_buttons(frm) {
	if (frm.doc.__islocal) {
		return;
	}
	frm.add_custom_button(
		__("Downtime Entry"),
		() => {
			frappe.new_doc("Downtime Entry", { custom_pea_shift: frm.doc.name });
		},
		__("Create")
	);
	if (!["Running", "Completed"].includes(frm.doc.status || "")) {
		return;
	}
	frm.add_custom_button(
		__("Production Entry"),
		() => {
			frappe.new_doc("Stock Entry", {
				stock_entry_type: "Manufacture",
				company: frm.doc.company,
				custom_pea_shift: frm.doc.name,
			});
		},
		__("Create")
	);
}

function _render_shift_sections(frm) {
	_render_linked_downtime_entries(frm);
	_render_shift_summary(frm);
	_render_aggregate_production_entries(frm);
	_sync_shift_helper_fields(frm);
	_setup_shift_quick_entry(frm);
}

function _set_warehouse_field_editability(frm) {
	const isLockedStatus = ["Completed", "Cancelled"].includes(frm.doc.status || "");
	WAREHOUSE_FIELDS.forEach((fieldname) => {
		frm.set_df_property(fieldname, "read_only", isLockedStatus ? 1 : 0);
	});
}

function _toggle_company_field_visibility(frm) {
	frappe.db.count("Company").then((count) => {
		frm.toggle_display("company", Number(count || 0) > 1);
	});
}

function _set_department_query(frm) {
	frm.set_query("department", () => {
		const filters = {};
		if (frm.doc.company) {
			filters.company = frm.doc.company;
		}
		return { filters };
	});
}

function _set_warehouse_queries(frm) {
	WAREHOUSE_FIELDS.forEach((fieldname) => {
		frm.set_query(fieldname, () => {
			const filters = {};
			if (frm.doc.company) {
				filters.company = frm.doc.company;
			}
			return { filters };
		});
	});
}

function _populate_default_breaks_if_draft(frm) {
	if (!_can_populate_default_breaks(frm)) {
		return;
	}
	if (frm.__plannedBreaksDebounceTimer) {
		clearTimeout(frm.__plannedBreaksDebounceTimer);
	}
	frm.__plannedBreaksDebounceTimer = setTimeout(() => {
		frm.__plannedBreaksDebounceTimer = null;
		if (!_can_populate_default_breaks(frm)) {
			return;
		}
		const requestKey = _get_planned_breaks_request_key(frm);
		frm.__plannedBreaksRequestKey = requestKey;
		_fetch_default_breaks(frm, requestKey);
	}, PLANNED_BREAKS_DEBOUNCE_MS);
}

function _can_populate_default_breaks(frm) {
	return Boolean(
		_is_draft_or_new(frm) &&
			frm.doc.shift_duration &&
			frm.doc.planned_start_time &&
			frm.doc.shift_date
	);
}

function _get_planned_breaks_request_key(frm) {
	return [
		String(frm.doc.shift_duration || ""),
		String(frm.doc.planned_start_time || ""),
		String(frm.doc.shift_date || ""),
	].join("|");
}

function _fetch_default_breaks(frm, requestKey) {
	frappe.call({
		method: "production_entry_app.production_entry_app.doctype.shift.shift.get_planned_losses_for_duration",
		args: {
			shift_duration: frm.doc.shift_duration,
			planned_start_time: frm.doc.planned_start_time,
			shift_date: frm.doc.shift_date,
		},
		callback(r) {
			if (
				_get_planned_breaks_request_key(frm) !== requestKey ||
				frm.__plannedBreaksRequestKey !== requestKey ||
				!_can_populate_default_breaks(frm)
			) {
				return;
			}
			frm.clear_table("planned_losses");
			(r.message || []).forEach((row) => frm.add_child("planned_losses", row));
			frm.refresh_field("planned_losses");
			_sync_shift_helper_fields(frm);
		},
		error() {
			frappe.msgprint(__("Failed to load planned breaks. Please retry."));
		},
	});
}

function _is_draft_or_new(frm) {
	return Boolean(frm.doc.__islocal || !frm.doc.status || frm.doc.status === "Draft");
}

function _get_time_entry_api() {
	return window.production_entry_app?.time_entry || null;
}

function _sync_shift_helper_fields(frm) {
	const timeEntry = _get_time_entry_api();
	if (!timeEntry) {
		return;
	}
	timeEntry.sync_time_display_from_doc(frm, "planned_start_time_input", "planned_start_time");
	timeEntry.sync_loss_entry_rows(frm, "planned_losses");
}

function _setup_shift_quick_entry(frm) {
	const timeEntry = _get_time_entry_api();
	if (!timeEntry) {
		return;
	}

	timeEntry.attach_today_button(frm, "shift_date");
	const onCommit = (input) => {
		if (!input) {
			timeEntry.set_field_invalid(frm, "planned_start_time_input", "");
			frm.set_value("planned_start_time", "");
			return;
		}
		const parsed = timeEntry.parse_time(input);
		if (parsed.error) {
			timeEntry.set_field_invalid(frm, "planned_start_time_input", parsed.error);
			return;
		}
		timeEntry.set_field_invalid(frm, "planned_start_time_input", "");
		frm.set_value(
			"planned_start_time_input",
			timeEntry.format_time_display(parsed.frappe_time)
		);
		frm.set_value("planned_start_time", parsed.frappe_time);
	};

	timeEntry.attach_time_chips(frm, "planned_start_time_input", {
		presets: SHIFT_TIME_PRESETS,
		show_now: true,
		on_commit: onCommit,
	});
	timeEntry.bind_committed_time_input(frm, "planned_start_time_input", onCommit);
}

function _render_linked_downtime_entries(frm) {
	if (!frm.doc.name) {
		return;
	}
	frappe.call({
		method: "production_entry_app.production_entry_app.doctype.shift.shift.get_linked_downtime_entries",
		args: { shift_name: frm.doc.name },
		callback(r) {
			const list = r.message || [];
			let html;
			if (list.length === 0) {
				html = `<p class="text-muted">${__(
					"No Downtime Entries linked to this Shift."
				)}</p>`;
			} else {
				const escape = (s) =>
					s !== null && s !== undefined ? frappe.utils.escape_html(String(s)) : "";
				const rows = list
					.map(
						(d) =>
							`<tr><td><a href="/app/downtime-entry/${encodeURIComponent(
								d.name || ""
							)}">${escape(d.name)}</a></td><td>${escape(
								d.workstation
							)}</td><td>${escape(d.from_time)}</td><td>${escape(
								d.to_time
							)}</td><td>${escape(d.downtime)}</td><td>${escape(
								d.stop_reason
							)}</td></tr>`
					)
					.join("");
				html = `<table class="table table-bordered table-condensed"><thead><tr><th>${__(
					"Name"
				)}</th><th>${__("Workstation")}</th><th>${__("From Time")}</th><th>${__(
					"To Time"
				)}</th><th>${__("Downtime (mins)")}</th><th>${__(
					"Stop Reason"
				)}</th></tr></thead><tbody>${rows}</tbody></table>`;
			}
			_set_shared_html_field(frm, "linked_downtime_entries", html);
		},
		error() {
			_set_shared_html_field(
				frm,
				"linked_downtime_entries",
				`<p class="text-muted">${__("Unable to load linked downtime entries.")}</p>`
			);
		},
	});
}

function _render_shift_summary(frm) {
	if (!frm.doc.name) {
		return;
	}
	frappe.call({
		method: "production_entry_app.production_entry_app.doctype.shift.shift.get_shift_summary",
		args: { shift_name: frm.doc.name },
		callback(r) {
			_set_shared_html_field(
				frm,
				"shift_metrics",
				_build_shift_summary_html(r.message || {})
			);
		},
		error() {
			_set_shared_html_field(
				frm,
				"shift_metrics",
				`<p class="text-muted">${__("Unable to load shift summary.")}</p>`
			);
		},
	});
}

function _build_shift_summary_html(summary) {
	const floatPrecision = _resolve_summary_float_precision(summary);
	const sections = [];
	sections.push(..._build_completeness_sections(summary.completeness || {}));
	sections.push(
		..._build_outcome_sections(summary.snapshot || {}, summary.losses || {}, floatPrecision)
	);
	sections.push(..._build_downtime_sections(summary.logged_downtime || {}, floatPrecision));
	sections.push(..._build_exception_sections(summary.exceptions || {}, floatPrecision));
	sections.push(
		..._build_positive_signal_sections(summary.positive_signal || null, floatPrecision)
	);
	return sections.join("");
}

function _build_completeness_sections(completeness) {
	if (!completeness.show_banner || !(completeness.messages || []).length) {
		return [];
	}
	return [
		`<div class="alert alert-warning">${(completeness.messages || [])
			.map((message) => frappe.utils.escape_html(String(message)))
			.join("<br>")}</div>`,
	];
}

function _build_outcome_sections(snapshot, losses, floatPrecision) {
	if (!Number(snapshot.entry_count || 0)) {
		return [
			`<p class="text-muted">${__(
				"No production entries are recorded for this shift yet."
			)}</p>`,
		];
	}
	return [
		_render_summary_table(
			__("Outcome Snapshot"),
			_get_snapshot_rows(snapshot),
			null,
			floatPrecision
		),
		_render_summary_table(
			__("Loss And Variance"),
			_get_loss_rows(losses),
			null,
			floatPrecision
		),
	];
}

function _get_snapshot_rows(snapshot) {
	const efficiencyMissing =
		snapshot.overall_shift_efficiency_pct === null ||
		snapshot.overall_shift_efficiency_pct === undefined;
	return [
		{ label: __("Entries"), value: snapshot.entry_count, fieldtype: "Int" },
		{ label: __("Total Qty"), value: snapshot.total_qty, fieldtype: "Float" },
		{ label: __("OK Qty"), value: snapshot.ok_qty, fieldtype: "Float" },
		{ label: __("Rejection Qty"), value: snapshot.rejection_qty, fieldtype: "Float" },
		{ label: __("Rejection (%)"), value: snapshot.rejection_pct, fieldtype: "Float" },
		{
			label: __("Recorded Production Mins"),
			value: snapshot.recorded_production_mins,
			fieldtype: "Float",
		},
		{
			label: __("Overall Throughput SPM"),
			value: snapshot.overall_throughput_spm,
			fieldtype: "Float",
		},
		{ label: __("Overall OK SPM"), value: snapshot.overall_ok_spm, fieldtype: "Float" },
		{
			label: __("Target Coverage (%)"),
			value: snapshot.target_coverage_pct,
			fieldtype: "Float",
		},
		{
			label: __("Overall Shift Efficiency (%)"),
			value: efficiencyMissing
				? __("Insufficient target coverage")
				: snapshot.overall_shift_efficiency_pct,
			fieldtype: efficiencyMissing ? null : "Float",
		},
	];
}

function _get_loss_rows(losses) {
	return [
		{ label: __("Planned Shift Mins"), value: losses.planned_shift_mins, fieldtype: "Float" },
		{ label: __("Planned Loss Mins"), value: losses.planned_loss_mins, fieldtype: "Float" },
		{
			label: __("Planned Usable Mins"),
			value: losses.planned_usable_mins,
			fieldtype: "Float",
		},
		{
			label: __("Production Loss Mins"),
			value: losses.unplanned_loss_mins,
			fieldtype: "Float",
		},
	];
}

function _build_downtime_sections(loggedDowntime, floatPrecision) {
	const sections = [
		_render_summary_table(
			__("Logged Downtime Incidents"),
			[
				{ label: __("Recorded"), value: loggedDowntime.recorded ? __("Yes") : __("No") },
				{
					label: __("Incident Count"),
					value: loggedDowntime.entry_count || 0,
					fieldtype: "Int",
				},
				{
					label: __("Total Logged Mins"),
					value: loggedDowntime.total_mins || 0,
					fieldtype: "Float",
				},
			],
			null,
			floatPrecision
		),
	];
	const topReasonRows = _map_reason_rows(loggedDowntime.top_reasons || []);
	if (topReasonRows.length) {
		sections.push(
			_render_summary_table(
				__("Top Logged Downtime Reasons"),
				topReasonRows,
				__("Reason"),
				floatPrecision
			)
		);
	}
	return sections;
}

function _build_exception_sections(exceptions, floatPrecision) {
	return [
		_optional_summary_table(
			__("Top Production Loss Reasons"),
			_map_reason_rows(exceptions.unplanned_loss_reasons || []),
			__("Reason"),
			floatPrecision
		),
		_optional_summary_table(
			__("Top Workstation Exceptions"),
			_map_workstation_rows(exceptions.workstations || []),
			__("Workstation"),
			floatPrecision
		),
		_optional_summary_table(
			__("Top Item/BOM Exceptions"),
			_map_item_bom_rows(exceptions.item_boms || []),
			__("Item / BOM"),
			floatPrecision
		),
	].filter(Boolean);
}

function _map_reason_rows(rows) {
	return rows.map((row) => ({
		label: row.reason || "",
		value: row.mins || 0,
		fieldtype: "Float",
	}));
}

function _map_workstation_rows(rows) {
	return rows.map((row) => ({
		label: row.workstation || "",
		value:
			row.efficiency_pct === null || row.efficiency_pct === undefined
				? row.throughput_spm || 0
				: row.efficiency_pct,
		fieldtype: "Float",
	}));
}

function _map_item_bom_rows(rows) {
	return rows.map((row) => ({
		label: row.label || row.bom_no || row.item_code || "",
		value: row.rejection_qty || 0,
		fieldtype: "Float",
	}));
}

function _optional_summary_table(title, rows, firstColumnLabel, floatPrecision) {
	return rows.length
		? _render_summary_table(title, rows, firstColumnLabel, floatPrecision)
		: null;
}

function _build_positive_signal_sections(positiveSignal, floatPrecision) {
	if (!positiveSignal) {
		return [];
	}
	const efficiencyMissing =
		positiveSignal.efficiency_pct === null || positiveSignal.efficiency_pct === undefined;
	return [
		_render_summary_table(
			__("Positive Signal"),
			[
				{ label: __("Best Workstation"), value: positiveSignal.workstation || "" },
				{
					label: efficiencyMissing ? __("Throughput SPM") : __("Efficiency (%)"),
					value: efficiencyMissing
						? positiveSignal.throughput_spm || 0
						: positiveSignal.efficiency_pct,
					fieldtype: "Float",
				},
			],
			null,
			floatPrecision
		),
	];
}

function _render_summary_table(title, rows, firstColumnLabel, floatPrecision) {
	const safeTitle = frappe.utils.escape_html(String(title || ""));
	const firstHeader = frappe.utils.escape_html(String(firstColumnLabel || __("Metric")));
	const body = (rows || [])
		.map(
			(row) =>
				`<tr><td>${frappe.utils.escape_html(
					String(row?.label ?? "")
				)}</td><td>${frappe.utils.escape_html(
					_format_summary_value(row, floatPrecision)
				)}</td></tr>`
		)
		.join("");
	return `
		<div class="pea-shift-summary-section">
			<h5>${safeTitle}</h5>
			<table class="table table-condensed table-bordered">
				<thead><tr><th>${firstHeader}</th><th>${__("Value")}</th></tr></thead>
				<tbody>${body}</tbody>
			</table>
		</div>
	`;
}

function _format_summary_value(row, floatPrecision) {
	if (!row) {
		return "";
	}
	const value = row.value;
	if (value === null || value === undefined) {
		return "";
	}
	if (!row.fieldtype || typeof value !== "number" || !Number.isFinite(value)) {
		return String(value);
	}
	if (typeof frappe !== "undefined" && typeof frappe.format === "function") {
		const df = { fieldtype: row.fieldtype };
		if (row.fieldtype === "Float") {
			df.precision = _get_summary_float_precision(floatPrecision);
		}
		return frappe.format(value, df, { only_value: true, always_show_decimals: true });
	}
	return String(value);
}

function _resolve_summary_float_precision(summary) {
	return _get_summary_float_precision(summary?.float_precision);
}

function _get_summary_float_precision(rawPrecision) {
	const resolvedRawPrecision =
		rawPrecision ??
		frappe?.boot?.sysdefaults?.float_precision ??
		frappe?.defaults?.get_default?.("float_precision") ??
		3;
	const numericPrecision = Number(resolvedRawPrecision);
	return Number.isFinite(numericPrecision) ? numericPrecision : 3;
}

function _format_aggregate_metric_value(value, floatPrecision) {
	return _format_summary_value({ value, fieldtype: "Float" }, floatPrecision);
}

function _render_aggregate_production_entries(frm) {
	if (!frm.doc.name) {
		return;
	}
	frappe.call({
		method: "production_entry_app.production_entry_app.doctype.shift.shift.get_shift_aggregate_production_entries",
		args: { shift_name: frm.doc.name },
		callback(r) {
			const rows = r.message || [];
			if (!rows.length) {
				_set_shared_html_field(
					frm,
					"aggregate_production_entries",
					`<p class="text-muted">${__(
						"No production entries linked to this shift yet."
					)}</p>`
				);
				return;
			}
			const floatPrecision = _get_summary_float_precision(rows[0]?.float_precision);

			const headers = [
				__("BOM Used"),
				__("Item Code"),
				__("Total Qty"),
				__("Total OK Qty"),
				__("Total Reject Qty"),
				__("Avg SPM"),
			];
			const thead = `<thead><tr>${headers
				.map((header) => `<th>${frappe.utils.escape_html(String(header))}</th>`)
				.join("")}</tr></thead>`;
			const tbody = `<tbody>${rows
				.map(
					(row) =>
						`<tr><td>${frappe.utils.escape_html(
							String(row.bom_used || "")
						)}</td><td>${frappe.utils.escape_html(
							String(row.item_code || "")
						)}</td><td>${frappe.utils.escape_html(
							_format_aggregate_metric_value(row.total_qty, floatPrecision)
						)}</td><td>${frappe.utils.escape_html(
							_format_aggregate_metric_value(row.total_ok_qty, floatPrecision)
						)}</td><td>${frappe.utils.escape_html(
							_format_aggregate_metric_value(row.total_reject_qty, floatPrecision)
						)}</td><td>${frappe.utils.escape_html(
							_format_aggregate_metric_value(row.avg_spm, floatPrecision)
						)}</td></tr>`
				)
				.join("")}</tbody>`;
			_set_shared_html_field(
				frm,
				"aggregate_production_entries",
				`<table class="table table-condensed table-bordered">${thead}${tbody}</table>`
			);
		},
		error() {
			_set_shared_html_field(
				frm,
				"aggregate_production_entries",
				`<p class="text-muted">${__("Unable to load aggregate production entries.")}</p>`
			);
		},
	});
}

function _set_shared_html_field(frm, fieldname, html) {
	const renderer = window.production_entry_app?.timeline_renderer;
	if (!renderer?.set_html_field) {
		return;
	}
	renderer.set_html_field(frm, fieldname, html);
}
