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
		}

		if (frm.doc.status === "Running") {
			frm.add_custom_button(__("End Shift"), () => {
				return frm.call("end_shift").then(() => frm.reload_doc());
			});
		}
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
