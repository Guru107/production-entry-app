frappe.ui.form.on("Die Tool Counter", {
	refresh(frm) {
		if (!frm.doc.die_tool_item) {
			return;
		}

		frm.add_custom_button(__("Reset Counter"), () => {
			frappe.prompt(
				[
					{
						fieldname: "maintenance_date",
						fieldtype: "Datetime",
						label: __("Maintenance Date"),
						reqd: 1,
						default: frappe.datetime.now_datetime(),
					},
				],
				(values) => {
					frappe.call({
						method: "production_entry_app.production_entry_app.api.reset_die_tool_counter",
						args: {
							die_tool_code: frm.doc.die_tool_item,
							maintenance_date: values.maintenance_date,
						},
						freeze: true,
						freeze_message: __("Resetting die tool counter..."),
						callback() {
							frm.reload_doc();
							frappe.show_alert(
								{
									message: __("Die tool counter reset completed."),
									indicator: "green",
								},
								5
							);
						},
						error() {
							frappe.msgprint(__("Unable to reset die tool counter."));
						},
					});
				},
				__("Reset Counter"),
				__("Reset")
			);
		});
	},
});
