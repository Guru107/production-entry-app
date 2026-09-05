from __future__ import annotations

import frappe


def execute() -> None:
	if frappe.db.exists("Custom Field", "Stock Entry-custom_pea_is_joint_lh_rh"):
		frappe.delete_doc(
			"Custom Field",
			"Stock Entry-custom_pea_is_joint_lh_rh",
			force=True,
			ignore_permissions=True,
		)
