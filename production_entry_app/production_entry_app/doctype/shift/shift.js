frappe.ui.form.on("Shift", {
	refresh(frm) {
		// Only show actions once the document is saved
		if (frm.is_new()) {
			return;
		}

		if (frm.doc.status === "Draft") {
			frm.add_custom_button(__("Start Shift"), () => {
				return frm.call("start_shift").then(() => frm.reload_doc());
			});
			frm.add_custom_button(__("Cancel"), () => {
				return frm.call("cancel_shift").then(() => frm.reload_doc());
			});
		}

		if (frm.doc.status === "Running") {
			frm.add_custom_button(__("End Shift"), () => {
				return frm.call("end_shift").then(() => frm.reload_doc());
			});
			frm.set_df_property("planned_losses", "read_only", 1);
		}

		if (frm.doc.status === "Completed" || frm.doc.status === "Cancelled") {
			frm.disable_form();
		}

		_render_linked_downtime_entries(frm);
	},

	shift_duration(frm) {
		_trigger_planned_losses_refresh(frm);
	},

	planned_start_time(frm) {
		_trigger_planned_losses_refresh(frm);
	},

	shift_date(frm) {
		_trigger_planned_losses_refresh(frm);
	},
});

function _trigger_planned_losses_refresh(frm) {
	if (!frm.doc.shift_duration || !frm.doc.planned_start_time || !frm.doc.shift_date) {
		return;
	}
	frm.call({
		method: "get_planned_losses_for_duration",
		args: {
			shift_duration: frm.doc.shift_duration,
			planned_start_time: frm.doc.planned_start_time,
			shift_date: frm.doc.shift_date,
		},
		callback(r) {
			if (r.message && r.message.length) {
				frm.clear_table("planned_losses");
				r.message.forEach((row) => frm.add_child("planned_losses", row));
				frm.refresh_field("planned_losses");
			}
		},
	});
}

function _render_linked_downtime_entries(frm) {
	if (frm.is_new() || !frm.doc.name) return;

	frm.call({
		method: "get_linked_downtime_entries",
		args: { shift_name: frm.doc.name },
		callback(r) {
			const entries = r.message || [];
			let html = "";
			if (entries.length === 0) {
				html =
					"<p class='text-muted'>" +
					__("No Downtime Entries linked to this Shift.") +
					"</p>";
			} else {
				html =
					"<table class='table table-bordered table-condensed'>" +
					"<thead><tr><th>" +
					__("Name") +
					"</th><th>" +
					__("Workstation") +
					"</th><th>" +
					__("From Time") +
					"</th><th>" +
					__("To Time") +
					"</th><th>" +
					__("Downtime (mins)") +
					"</th><th>" +
					__("Stop Reason") +
					"</th></tr></thead><tbody>";
				entries.forEach((row) => {
					html +=
						"<tr>" +
						"<td><a href='/app/downtime-entry/" +
						encodeURIComponent(row.name) +
						"'>" +
						frappe.escape_html(row.name) +
						"</a></td>" +
						"<td>" +
						frappe.escape_html(row.workstation || "") +
						"</td>" +
						"<td>" +
						frappe.escape_html(row.from_time || "") +
						"</td>" +
						"<td>" +
						frappe.escape_html(row.to_time || "") +
						"</td>" +
						"<td>" +
						frappe.escape_html(row.downtime != null ? row.downtime : "") +
						"</td>" +
						"<td>" +
						frappe.escape_html(row.stop_reason || "") +
						"</td></tr>";
				});
				html += "</tbody></table>";
			}
			frm.set_df_property("linked_downtime_entries", "options", html);
			frm.refresh_field("linked_downtime_entries");
		},
	});
}
