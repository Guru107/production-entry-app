from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import lifecycle
from production_entry_app.production_entry_app.tests.support import host_parity
from production_entry_app.production_entry_app.utils import legacy_time_cutover
from production_entry_app.production_entry_app.utils.legacy_time_cutover import (
	execute_legacy_time_cutover,
)


def _enabled(name: str) -> int:
	return int(frappe.db.get_value("Client Script", name, "enabled") or 0)


def _field_exists(doctype: str, fieldname: str) -> bool:
	return frappe.get_meta(doctype, cached=False).get_field(fieldname) is not None


def _script_state() -> dict[str, int]:
	rows = frappe.get_all("Client Script", fields=["name", "enabled"])
	return {row.name: int(row.enabled or 0) for row in rows}


def _property_setter_state() -> dict[str, str]:
	rows = frappe.get_all(
		"Property Setter",
		filters={"module": "Production Entry App"},
		fields=["name", "value"],
		order_by="name",
	)
	return {row.name: row.value for row in rows}


class DriftNeutralTestCase(FrappeTestCase):
	"""Base: make the shared dev site's real staging-style drift invisible.

	The engine hides any module-PEA custom field outside current fixtures, so
	tests that do not build drift must neutralize the site's own first —
	otherwise the engine's decisions (and the state snapshots) depend on which
	fields happen to have drifted on this site.
	"""

	def setUp(self) -> None:
		super().setUp()
		self.neutralized_drift = host_parity.neutralize_module_pea_drift()
		self.addCleanup(host_parity.restore_module_pea_drift, self.neutralized_drift)


class TestCutoverOnCleanSite(DriftNeutralTestCase):
	"""No host drift at all: the cutover must be a clean no-op."""

	def setUp(self) -> None:
		super().setUp()
		self.property_setters_before = host_parity.snapshot_module_property_setters()
		self.addCleanup(host_parity.restore_module_property_setters, self.property_setters_before)
		self.scripts_before = _script_state()
		# A host-parity clone carries the real legacy fields; a clean site has
		# none. Remove them so the noop expectation holds on any site.
		host_parity.remove_legacy_time_fields()
		self.addCleanup(host_parity.install_legacy_time_fields)

	def test_cutover_is_noop_on_clean_site(self) -> None:
		execute_legacy_time_cutover()

		self.assertEqual(
			_property_setter_state(),
			{name: row["value"] for name, row in self.property_setters_before.items()},
		)
		self.assertEqual(_script_state(), self.scripts_before)


class TestCutoverClientScripts(DriftNeutralTestCase):
	def setUp(self) -> None:
		super().setUp()
		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS + host_parity.KEPT_CLIENT_SCRIPTS:
			host_parity.ensure_client_script(name)
			self.addCleanup(host_parity.remove_client_script, name)

	def test_cutover_disables_exactly_the_two_legacy_time_scripts(self) -> None:
		execute_legacy_time_cutover()

		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS:
			self.assertEqual(_enabled(name), 0, name)
		for name in host_parity.KEPT_CLIENT_SCRIPTS:
			self.assertEqual(_enabled(name), 1, name)

	def test_cutover_skips_cleanly_when_scripts_absent(self) -> None:
		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS:
			host_parity.remove_client_script(name)

		execute_legacy_time_cutover()

		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS:
			self.assertFalse(frappe.db.exists("Client Script", name))

	def test_cutover_skips_already_disabled_scripts(self) -> None:
		host_parity.ensure_client_script("Actual & Loss Time Calculation", enabled=False)

		execute_legacy_time_cutover()

		self.assertEqual(_enabled("Actual & Loss Time Calculation"), 0)
		self.assertEqual(_enabled("Stock Auto Time"), 0)

	def test_cutover_disables_scripts_before_removing_fields(self) -> None:
		manager = MagicMock()
		with (
			patch.object(legacy_time_cutover, "_disable_legacy_client_scripts", manager.disable),
			patch.object(legacy_time_cutover, "_remove_legacy_time_custom_fields", manager.remove_fields),
			patch.object(legacy_time_cutover, "_hide_obsolete_pea_custom_fields", manager.hide_obsolete),
		):
			execute_legacy_time_cutover()

		self.assertEqual(
			[call[0] for call in manager.mock_calls],
			["disable", "remove_fields", "hide_obsolete"],
		)


class CutoverHostParityTestCase(DriftNeutralTestCase):
	"""Base: legacy time fields, the five host client scripts, and drift in place."""

	def setUp(self) -> None:
		super().setUp()
		self.property_setters_before = host_parity.snapshot_module_property_setters()
		self.addCleanup(host_parity.restore_module_property_setters, self.property_setters_before)
		self.addCleanup(host_parity.remove_legacy_time_fields)
		host_parity.install_legacy_time_fields()
		self.addCleanup(host_parity.remove_legacy_workstation)
		host_parity.ensure_legacy_workstation()
		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS + host_parity.KEPT_CLIENT_SCRIPTS:
			host_parity.ensure_client_script(name)
			self.addCleanup(host_parity.remove_client_script, name)

	def run_cutover(self) -> None:
		execute_legacy_time_cutover()


class TestCutoverFieldRemoval(CutoverHostParityTestCase):
	def test_cutover_removes_every_legacy_time_field(self) -> None:
		self.run_cutover()

		for doctype, fieldname in legacy_time_cutover.LEGACY_TIME_FIELDS:
			self.assertFalse(_field_exists(doctype, fieldname), f"{doctype}.{fieldname} still in meta")
			self.assertFalse(frappe.db.exists("Custom Field", f"{doctype}-{fieldname}"))

	def test_cutover_drops_legacy_values_on_submitted_entries(self) -> None:
		entry = host_parity.make_legacy_stock_entry()
		self.addCleanup(host_parity.discard_stock_entry, entry)
		self.assertTrue(frappe.db.get_value("Stock Entry", entry, "custom_workstation"))

		self.run_cutover()

		# Hard cutover: the column and its historical value are gone; the entry itself survives.
		self.assertEqual(frappe.db.get_value("Stock Entry", entry, "docstatus"), 1)
		self.assertFalse(_field_exists("Stock Entry", "custom_workstation"))
		self.assertFalse(_field_exists("Stock Entry", "custom_actual_start_date"))

	def test_cutover_removes_stale_property_setters_on_removed_fields(self) -> None:
		host_parity.ensure_host_property_setter("Stock Entry", "custom_workstation", value="1")
		frappe.get_doc(
			{
				"doctype": "Property Setter",
				"doctype_or_field": "DocField",
				"doc_type": "Stock Entry",
				"field_name": "custom_actual_start_date",
				"property": "read_only",
				"property_type": "Check",
				"value": "1",
				"module": "Production Entry App",
			}
		).insert(ignore_permissions=True)

		self.run_cutover()

		self.assertEqual(
			frappe.get_all(
				"Property Setter",
				filters={"doc_type": "Stock Entry", "field_name": ("in", ["custom_workstation", "custom_actual_start_date"])},
			),
			[],
		)

	def test_cutover_never_removes_native_fields_with_legacy_names(self) -> None:
		"""A target that exists as a native field is reported and left alone."""
		native_fieldname = "posting_date"
		with patch.object(
			legacy_time_cutover,
			"LEGACY_TIME_FIELDS",
			(("Stock Entry", native_fieldname),),
		):
			self.run_cutover()

		self.assertTrue(_field_exists("Stock Entry", native_fieldname))

	def test_cutover_hides_obsolete_pea_custom_fields(self) -> None:
		host_parity.ensure_obsolete_pea_custom_field()
		self.addCleanup(host_parity.remove_obsolete_pea_custom_field)

		self.run_cutover()

		self.assertEqual(
			int(
				getattr(
					frappe.get_meta("Stock Entry", cached=False).get_field("custom_pea_abandoned_metric"),
					"hidden",
					0,
				)
				or 0
			),
			1,
		)
		self.assertTrue(frappe.db.exists("Custom Field", "Stock Entry-custom_pea_abandoned_metric"))

	def test_cutover_skips_obsolete_hiding_when_no_drift_exists(self) -> None:
		self.run_cutover()

		# Every fixture-shipped PEA custom field on Stock Entry keeps its visibility:
		# the cutover must not create hidden property setters for fields it still ships.
		fixture_fieldnames = {
			row.fieldname
			for row in frappe.get_all(
				"Custom Field",
				filters={"module": "Production Entry App", "dt": "Stock Entry"},
				fields=["fieldname"],
			)
		}
		self.assertTrue(fixture_fieldnames)
		for fieldname in fixture_fieldnames:
			self.assertNotIn(f"Stock Entry-{fieldname}-hidden", _property_setter_state())

	def test_cutover_leaves_host_and_production_owned_metadata_untouched(self) -> None:
		host_parity.ensure_host_custom_field(
			"Stock Entry",
			{
				"fieldname": "custom_stock_entry_purpose",
				"label": "Stock Entry Purpose",
				"fieldtype": "Data",
				"read_only": 1,
			},
		)
		self.addCleanup(host_parity.remove_host_custom_field, "Stock Entry", "custom_stock_entry_purpose")
		host_parity.ensure_host_custom_field(
			"Workstation",
			{"fieldname": "custom_press_rate", "label": "Press Rate", "fieldtype": "Float"},
		)
		self.addCleanup(host_parity.remove_host_custom_field, "Workstation", "custom_press_rate")
		host_parity.ensure_host_custom_field(
			"BOM", {"fieldname": "custom_operation", "label": "Operation", "fieldtype": "Data"}
		)
		self.addCleanup(host_parity.remove_host_custom_field, "BOM", "custom_operation")

		self.run_cutover()

		self.assertTrue(_field_exists("Stock Entry", "custom_stock_entry_purpose"))
		self.assertTrue(_field_exists("Workstation", "custom_press_rate"))
		self.assertTrue(_field_exists("BOM", "custom_operation"))
		self.assertFalse(_field_exists("Workstation", "custom_standard_spm"))

	def test_cutover_is_idempotent(self) -> None:
		host_parity.ensure_obsolete_pea_custom_field()
		self.addCleanup(host_parity.remove_obsolete_pea_custom_field)

		self.run_cutover()
		property_setters_after_first = _property_setter_state()
		scripts_after_first = _script_state()
		fields_after_first = {
			(doctype, fieldname): _field_exists(doctype, fieldname)
			for doctype, fieldname in legacy_time_cutover.LEGACY_TIME_FIELDS
		}

		self.run_cutover()

		self.assertEqual(_property_setter_state(), property_setters_after_first)
		self.assertEqual(_script_state(), scripts_after_first)
		self.assertEqual(
			{
				(doctype, fieldname): _field_exists(doctype, fieldname)
				for doctype, fieldname in legacy_time_cutover.LEGACY_TIME_FIELDS
			},
			fields_after_first,
		)


class TestCutoverDriftUninstall(CutoverHostParityTestCase):
	def test_before_uninstall_customization_cleanup_unhides_drift_fields(self) -> None:
		"""The drift hide is the cutover's only Property Setter footprint left
		after field removal; uninstall cleanup reverses it."""
		host_parity.ensure_obsolete_pea_custom_field()
		self.addCleanup(host_parity.remove_obsolete_pea_custom_field)

		self.run_cutover()
		self.assertEqual(
			int(
				getattr(
					frappe.get_meta("Stock Entry", cached=False).get_field("custom_pea_abandoned_metric"),
					"hidden",
					0,
				)
				or 0
			),
			1,
		)

		lifecycle._delete_customizations("Property Setter")

		self.assertEqual(
			int(
				getattr(
					frappe.get_meta("Stock Entry", cached=False).get_field("custom_pea_abandoned_metric"),
					"hidden",
					0,
				)
				or 0
			),
			0,
		)
