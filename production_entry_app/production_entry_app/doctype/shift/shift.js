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
	},
	company(frm) {
		_set_warehouse_queries(frm);
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
		// Prevent editing planned losses after shift has started
		frm.set_df_property("planned_losses", "read_only", frm.doc.status !== "Draft");
		_set_warehouse_field_editability(frm);
		_toggle_company_field_visibility(frm);
		_set_warehouse_queries(frm);

		const actions_group = __("Actions");
		if (frm.doc.status === "Draft") {
			frm.add_custom_button(
				__("Start Shift"),
				function () {
					frm.call({
						method: "start_shift",
						doc: frm.doc,
						freeze: true,
						callback: function () {
							frm.reload_doc();
						},
					});
				},
				actions_group
			);
			frm.add_custom_button(
				__("Cancel"),
				function () {
					frappe.confirm(__("Cancel this shift?"), function () {
						frm.call({
							method: "cancel_shift",
							doc: frm.doc,
							freeze: true,
							callback: function () {
								frm.reload_doc();
							},
						});
					});
				},
				actions_group
			);
		} else if (frm.doc.status === "Running") {
			frm.add_custom_button(
				__("End Shift"),
				function () {
					frappe.confirm(
						__(
							"End this shift? No more production entries can be added after ending."
						),
						function () {
							frm.call({
								method: "end_shift",
								doc: frm.doc,
								freeze: true,
								callback: function () {
									frm.reload_doc();
								},
							});
						}
					);
				},
				actions_group
			);
		}

		if (!frm.doc.__islocal) {
			frm.add_custom_button(
				__("Downtime Entry"),
				function () {
					frappe.new_doc("Downtime Entry", { shift: frm.doc.name });
				},
				__("Create")
			);

			// Only show Production Entry button for Running shifts
			if (frm.doc.status === "Running") {
				frm.add_custom_button(
					__("Production Entry"),
					function () {
						frappe.new_doc("Stock Entry", {
							stock_entry_type: "Manufacture",
							custom_shift: frm.doc.name,
						});
					},
					__("Create")
				);
			}
		}

		_render_linked_downtime_entries(frm);
		_render_shift_metrics(frm);
		_render_aggregate_production_entries(frm);
		_sync_shift_helper_fields(frm);
		_setup_shift_quick_entry(frm);
	},
});

function _set_warehouse_field_editability(frm) {
	const isLockedStatus = ["Completed", "Cancelled"].includes(frm.doc.status || "");
	WAREHOUSE_FIELDS.forEach((fieldname) => {
		frm.set_df_property(fieldname, "read_only", isLockedStatus ? 1 : 0);
	});
}

function _toggle_company_field_visibility(frm) {
	if (typeof frm.__companyCount === "number") {
		frm.toggle_display("company", frm.__companyCount > 1);
		return;
	}

	frappe.db.count("Company").then((count) => {
		frm.__companyCount = Number(count || 0);
		frm.toggle_display("company", frm.__companyCount > 1);
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
	if (
		!_is_draft_or_new(frm) ||
		!frm.doc.shift_duration ||
		!frm.doc.planned_start_time ||
		!frm.doc.shift_date
	) {
		return;
	}
	if (frm.__plannedBreaksDebounceTimer) {
		clearTimeout(frm.__plannedBreaksDebounceTimer);
	}
	frm.__plannedBreaksDebounceTimer = setTimeout(() => {
		frm.__plannedBreaksDebounceTimer = null;
		if (
			!_is_draft_or_new(frm) ||
			!frm.doc.shift_duration ||
			!frm.doc.planned_start_time ||
			!frm.doc.shift_date
		) {
			return;
		}
		const requestKey = [
			String(frm.doc.shift_duration || ""),
			String(frm.doc.planned_start_time || ""),
			String(frm.doc.shift_date || ""),
		].join("|");
		frm.__plannedBreaksRequestKey = requestKey;
		frappe.call({
			method: "production_entry_app.production_entry_app.doctype.shift.shift.get_planned_losses_for_duration",
			args: {
				shift_duration: frm.doc.shift_duration,
				planned_start_time: frm.doc.planned_start_time,
				shift_date: frm.doc.shift_date,
			},
			callback(r) {
				const currentKey = [
					String(frm.doc.shift_duration || ""),
					String(frm.doc.planned_start_time || ""),
					String(frm.doc.shift_date || ""),
				].join("|");
				if (currentKey !== requestKey || frm.__plannedBreaksRequestKey !== requestKey) {
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
	}, PLANNED_BREAKS_DEBOUNCE_MS);
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
				const escape = (s) => (s != null ? frappe.utils.escape_html(String(s)) : "");
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

function _render_shift_metrics(frm) {
	if (!frm.doc.name) {
		return;
	}
	frappe.call({
		method: "production_entry_app.production_entry_app.doctype.shift.shift.get_shift_metrics",
		args: { shift_name: frm.doc.name },
		callback(r) {
			const metrics = r.message || {};
			const entry_count = Number(metrics.entry_count || 0);
			if (!entry_count) {
				_set_shared_html_field(
					frm,
					"shift_metrics",
					`<p class="text-muted">${__(
						"No production entries linked to this shift yet."
					)}</p>`
				);
				return;
			}

			const rows = [
				[__("Entries"), metrics.entry_count],
				[__("Total Qty"), metrics.total_qty],
				[__("Rejection Qty"), metrics.total_rejection_qty],
				[__("OK Qty"), metrics.total_ok_qty],
				[__("Total Duration (mins)"), metrics.total_duration_mins],
				[__("Avg Actual SPM"), metrics.avg_actual_spm],
				[__("Avg Efficiency (%)"), metrics.avg_efficiency_pct],
			];

			const htmlRows = rows
				.map(
					([label, value]) =>
						`<tr><td>${frappe.utils.escape_html(
							String(label)
						)}</td><td>${frappe.utils.escape_html(String(value))}</td></tr>`
				)
				.join("");
			const html = `<table class="table table-condensed table-bordered"><tbody>${htmlRows}</tbody></table>`;
			_set_shared_html_field(frm, "shift_metrics", html);
		},
		error() {
			_set_shared_html_field(
				frm,
				"shift_metrics",
				`<p class="text-muted">${__("Unable to load shift metrics.")}</p>`
			);
		},
	});
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
							String(row.total_qty ?? "")
						)}</td><td>${frappe.utils.escape_html(
							String(row.total_ok_qty ?? "")
						)}</td><td>${frappe.utils.escape_html(
							String(row.total_reject_qty ?? "")
						)}</td><td>${frappe.utils.escape_html(
							String(row.avg_spm ?? "")
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
		console.warn("Production Entry App timeline renderer is not loaded.");
		return;
	}
	renderer.set_html_field(frm, fieldname, html);
}
