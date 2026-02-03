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
});
