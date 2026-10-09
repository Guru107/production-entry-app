"""Shared test bases and state readers for the install-migration seams.

The install hooks (``install.py``) and the migration patch pair drive the same
guarded engine entry points, so their tests share one host-parity scaffold:
``CleanSiteTestCase`` neutralizes a shared dev site's real staging-style drift,
and ``HostParityInstallTestCase`` builds the production-like state on top (host
custom Downtime Reason with legacy rows and submitted history, Loss Time links,
legacy time-capture fields, client scripts).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.doctype.downtime_reason.downtime_reason import (
	CODE_FORMAT,
)
from production_entry_app.production_entry_app.tests.support import host_parity
from production_entry_app.production_entry_app.utils.downtime_reason_seed import (
	STANDARD_DOWNTIME_REASONS,
)


def reason_rows() -> list[dict]:
	return frappe.get_all(
		"Downtime Reason", fields=["name", "code", "description", "is_active"], order_by="name"
	)


def script_enabled(name: str) -> int:
	return int(frappe.db.get_value("Client Script", name, "enabled") or 0)


def field_hidden(doctype: str, fieldname: str) -> int:
	field = frappe.get_meta(doctype, cached=False).get_field(fieldname)
	return int(getattr(field, "hidden", 0) or 0)


def script_state() -> dict[str, int]:
	rows = frappe.get_all("Client Script", fields=["name", "enabled"])
	return {row.name: int(row.enabled or 0) for row in rows}


def app_property_setter_state() -> dict[str, str]:
	rows = frappe.get_all(
		"Property Setter",
		filters={"module": "Production Entry App"},
		fields=["name", "value"],
		order_by="name",
	)
	return {row.name: row.value for row in rows}


def migration_state() -> dict:
	"""Bundle the migration-relevant state for before/after comparisons."""
	return {
		"reasons": reason_rows(),
		"doctype": host_parity.doctype_snapshot(),
		"property_setters": app_property_setter_state(),
		"scripts": script_state(),
	}


class CleanSiteTestCase(FrappeTestCase):
	"""A site without host drift (the clean-install shape)."""

	def setUp(self) -> None:
		super().setUp()
		self.neutralized_drift = host_parity.neutralize_module_pea_drift()
		self.addCleanup(host_parity.restore_module_pea_drift, self.neutralized_drift)
		host_parity.clear_adoption_export()
		self.addCleanup(host_parity.clear_adoption_export)
		self.addCleanup(host_parity.restore_app_downtime_reason)


class HostParityMigrationTestCase(CleanSiteTestCase):
	"""Host (production-like) state for the install/migrate seams: host DocType, legacy UI, links, scripts."""

	def setUp(self) -> None:
		super().setUp()
		self.property_setters_before = host_parity.snapshot_module_property_setters()
		self.addCleanup(host_parity.restore_module_property_setters, self.property_setters_before)
		host_parity.restore_app_downtime_reason()
		host_parity.delete_downtime_reason_doctype()
		host_parity.install_host_downtime_reason_doctype()
		host_parity.insert_host_downtime_reason("Setup Time", legacy_docstatus=1)
		host_parity.insert_host_downtime_reason("Inventory")
		host_parity.install_host_loss_time()
		self.addCleanup(host_parity.remove_host_loss_time)
		# All schema DDL before the sample entry: custom-field creation issues
		# implicit commits, and a commit after the insert would leak the entry
		# (and its Loss Time rows) across the class's transaction rollbacks.
		host_parity.install_legacy_time_fields()
		self.addCleanup(host_parity.remove_legacy_time_fields)
		self.stock_entry = host_parity.make_host_stock_entry_with_loss_times(["Setup Time", "Inventory"])
		self.addCleanup(host_parity.discard_stock_entry, self.stock_entry)
		host_parity.ensure_legacy_workstation()
		self.addCleanup(host_parity.remove_legacy_workstation)
		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS + host_parity.KEPT_CLIENT_SCRIPTS:
			host_parity.ensure_client_script(name)
			self.addCleanup(host_parity.remove_client_script, name)

	def assert_adopted_converted_and_cut_over(self) -> None:
		"""Standard codes present, legacy names merged/renamed, links rewritten, cutover applied."""
		names = {row["name"] for row in reason_rows()}
		self.assertTrue(names)
		for name in names:
			self.assertRegex(name, CODE_FORMAT.pattern)
		self.assertTrue(names >= set(STANDARD_DOWNTIME_REASONS))
		self.assertEqual(frappe.db.get_value("Downtime Reason", "01", "description"), "Setup")
		self.assertEqual(frappe.db.get_value("Downtime Reason", "23", "description"), "Inventory")
		self.assertEqual(sorted(host_parity.loss_time_reason_values(self.stock_entry)), ["01", "23"])
		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS:
			self.assertEqual(script_enabled(name), 0, name)
		for name in host_parity.KEPT_CLIENT_SCRIPTS:
			self.assertEqual(script_enabled(name), 1, name)
		for doctype, fieldname in (
			("Stock Entry", "custom_operation_details"),
			("Stock Entry", "custom_actual_time"),
			("Stock Entry", "custom_loss_time"),
			("Stock Entry", "custom_workstation"),
			("Stock Entry", "custom_actual_start_date"),
			("Workstation", "custom_standard_spm"),
			("Stock Entry", "custom_press_rate"),
			("Workstation", "custom_press_rate"),
		):
			self.assertIsNone(
				frappe.get_meta(doctype, cached=False).get_field(fieldname), f"{doctype}.{fieldname} removed"
			)
			self.assertFalse(frappe.db.exists("Custom Field", f"{doctype}-{fieldname}"))
