// Copyright (c) 2026, Gurudatt Kulkarni and contributors
// For license information, please see license.txt

frappe.ui.form.on("Shift", {
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
	},
});

function _populate_default_breaks_if_draft(frm) {
	if (
		frm.doc.status !== "Draft" ||
		!frm.doc.shift_duration ||
		!frm.doc.planned_start_time ||
		!frm.doc.shift_date
	) {
		return;
	}
	frappe.call({
		method: "production_entry_app.production_entry_app.doctype.shift.shift.get_planned_losses_for_duration",
		args: {
			shift_duration: frm.doc.shift_duration,
			planned_start_time: frm.doc.planned_start_time,
			shift_date: frm.doc.shift_date,
		},
		callback(r) {
			if (r.message && r.message.length > 0) {
				frm.clear_table("planned_losses");
				r.message.forEach((row) => frm.add_child("planned_losses", row));
				frm.refresh_field("planned_losses");
			}
		},
	});
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
				html = '<p class="text-muted">No Downtime Entries linked to this Shift.</p>';
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
				html = `<table class="table table-bordered table-condensed"><thead><tr><th>Name</th><th>Workstation</th><th>From Time</th><th>To Time</th><th>Downtime (mins)</th><th>Stop Reason</th></tr></thead><tbody>${rows}</tbody></table>`;
			}
			_set_html_field(frm, "linked_downtime_entries", html);
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
				_set_html_field(
					frm,
					"shift_metrics",
					'<p class="text-muted">No production entries linked to this shift yet.</p>'
				);
				return;
			}

			const rows = [
				["Entries", metrics.entry_count],
				["Good Qty", metrics.total_good_qty],
				["Rejection Qty", metrics.total_rejection_qty],
				["OK Qty", metrics.total_ok_qty],
				["Total Duration (mins)", metrics.total_duration_mins],
				["Avg Actual SPM", metrics.avg_actual_spm],
				["Avg Efficiency (%)", metrics.avg_efficiency_pct],
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
			_set_html_field(frm, "shift_metrics", html);
		},
	});
}

function _set_html_field(frm, fieldname, html) {
	const update_display = () => {
		const field = frm.fields_dict[fieldname];
		if (field) {
			field.df.options = html;
			field.html(html);
		}
	};
	update_display();
	if (!frm.fields_dict[fieldname]) {
		setTimeout(update_display, 100);
	}
}
