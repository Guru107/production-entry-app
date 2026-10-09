from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.doctype.downtime_reason.downtime_reason import (
	CODE_FORMAT,
)
from production_entry_app.production_entry_app.tests.support import host_parity
from production_entry_app.production_entry_app.utils.downtime_reason_adoption import (
	APP_MODULE,
	adopt_host_downtime_reason,
	adopt_host_downtime_reason_schema,
	adoption_export_path,
)
from production_entry_app.production_entry_app.utils.downtime_reason_seed import (
	STANDARD_DOWNTIME_REASONS,
)


@contextmanager
def missing_app_module_def() -> Iterator[None]:
	"""Simulate the fresh-install site state: the app Module Def row does not exist."""
	real_get_value = frappe.db.get_value

	def get_value_without_app_module_def(doctype: str, *args: object, **kwargs: object) -> object:
		filters = args[0] if args else kwargs.get("filters")
		if doctype == "Module Def" and filters == APP_MODULE:
			return None
		return real_get_value(doctype, *args, **kwargs)

	with patch.object(frappe.db, "get_value", side_effect=get_value_without_app_module_def):
		yield


def _reason_rows() -> list[dict]:
	return frappe.get_all(
		"Downtime Reason", fields=["name", "code", "description", "is_active"], order_by="name"
	)


class TestSchemaAdoptionNoop(FrappeTestCase):
	def setUp(self) -> None:
		host_parity.clear_adoption_export()
		self.addCleanup(host_parity.clear_adoption_export)
		self.addCleanup(host_parity.restore_app_downtime_reason)

	def test_schema_adoption_is_noop_when_doctype_is_app_owned(self) -> None:
		host_parity.restore_app_downtime_reason()
		before = host_parity.doctype_snapshot()

		adopt_host_downtime_reason_schema()

		self.assertEqual(host_parity.doctype_snapshot(), before)
		self.assertFalse(Path(adoption_export_path()).exists())

	def test_schema_adoption_is_noop_when_doctype_is_absent(self) -> None:
		host_parity.delete_downtime_reason_doctype()

		adopt_host_downtime_reason_schema()

		self.assertFalse(frappe.db.exists("DocType", "Downtime Reason"))

	def test_full_adoption_is_noop_on_staging_pattern_site(self) -> None:
		"""Adopted schema, no host rows, no export on disk: full sequence changes nothing."""
		host_parity.restore_app_downtime_reason()
		before = _reason_rows()
		meta_before = host_parity.doctype_snapshot()

		adopt_host_downtime_reason()

		self.assertEqual(_reason_rows(), before)
		self.assertEqual(host_parity.doctype_snapshot(), meta_before)


class HostParityTestCase(FrappeTestCase):
	"""Base: swap the app DocType for the production host shape with legacy rows."""

	def setUp(self) -> None:
		super().setUp()
		host_parity.clear_adoption_export()
		self.addCleanup(host_parity.clear_adoption_export)
		self.addCleanup(host_parity.restore_app_downtime_reason)
		host_parity.restore_app_downtime_reason()
		host_parity.delete_downtime_reason_doctype()
		host_parity.install_host_downtime_reason_doctype()
		host_parity.insert_host_downtime_reason("Setup Time", legacy_docstatus=1)
		host_parity.insert_host_downtime_reason("Inventory")


class HostParityWithLinksTestCase(HostParityTestCase):
	"""Host shape plus the Loss Time child table linked from a Stock Entry."""

	def setUp(self) -> None:
		super().setUp()
		host_parity.install_host_loss_time()
		self.addCleanup(host_parity.remove_host_loss_time)
		self.stock_entry = host_parity.make_host_stock_entry_with_loss_times(["Setup Time", "Inventory"])
		self.addCleanup(host_parity.discard_stock_entry, self.stock_entry)


class TestSchemaAdoptionReshape(HostParityTestCase):
	def test_schema_adoption_reshapes_the_host_doctype_in_place(self) -> None:
		adopt_host_downtime_reason_schema()

		snapshot = host_parity.doctype_snapshot()
		self.assertEqual(snapshot["module"], "Production Entry App")
		self.assertEqual(snapshot["custom"], 0)
		self.assertEqual(snapshot["autoname"], "field:code")
		self.assertEqual(snapshot["is_submittable"], 0)
		self.assertEqual(snapshot["fieldnames"], ("code", "description", "is_active"))
		self.assertEqual(frappe.get_value("DocType", "Downtime Reason", "naming_rule"), "By fieldname")

	def test_schema_adoption_reshapes_before_module_defs_exist(self) -> None:
		"""Fresh-install shape: ``before_install`` runs before the installer creates Module Defs.

		The record keeps ``custom=1`` with the host module (a standard DocType
		needs its app's Module Def and controller path); the doctype sync right
		after re-imports the record from the app JSON (module included). The
		export and row normalization are still ours and must run.
		"""
		with missing_app_module_def():
			adopt_host_downtime_reason_schema()

		snapshot = host_parity.doctype_snapshot()
		self.assertEqual(snapshot["module"], "Manufacturing")
		self.assertEqual(snapshot["custom"], 1)
		self.assertEqual(snapshot["autoname"], "field:code")
		self.assertEqual(snapshot["fieldnames"], ("code", "description", "is_active"))
		row = frappe.db.get_value(
			"Downtime Reason", "Setup Time", ["description", "is_active", "docstatus"], as_dict=True
		)
		self.assertEqual(row.description, "Setup Time")
		self.assertEqual(row.is_active, 1)
		self.assertEqual(row.docstatus, 0)

	def test_schema_adoption_retry_after_fresh_install_reshape_converges(self) -> None:
		"""A rerun after the fresh-install reshape (pre-sync) is a guarded no-op."""
		with missing_app_module_def():
			adopt_host_downtime_reason_schema()
		snapshot_after_first = host_parity.doctype_snapshot()
		export_after_first = Path(adoption_export_path()).read_text()

		adopt_host_downtime_reason_schema()

		self.assertEqual(host_parity.doctype_snapshot(), snapshot_after_first)
		self.assertEqual(Path(adoption_export_path()).read_text(), export_after_first)

	def test_schema_adoption_preserves_rows_and_normalizes_them(self) -> None:
		adopt_host_downtime_reason_schema()

		rows = {
			row.name: row
			for row in frappe.get_all(
				"Downtime Reason", fields=["name", "description", "is_active", "docstatus"]
			)
		}
		self.assertEqual(set(rows), {"Setup Time", "Inventory"})
		for name, row in rows.items():
			self.assertEqual(row.description, name)
			self.assertEqual(row.docstatus, 0)
			self.assertEqual(row.is_active, 1)

	def test_schema_adoption_writes_recovery_export_before_mutating(self) -> None:
		adopt_host_downtime_reason_schema()

		path = Path(adoption_export_path())
		export = json.loads(path.read_text())
		self.assertEqual(
			[reason["name"] for reason in export["reasons"]],
			["Setup Time", "Inventory"],
		)
		self.assertEqual(export["reasons"][0]["docstatus"], 1)


class TestFullAdoption(HostParityWithLinksTestCase):
	def test_full_adoption_converts_all_masters_to_codes(self) -> None:
		adopt_host_downtime_reason()

		names = {row["name"] for row in _reason_rows()}
		self.assertTrue(names)
		for name in names:
			self.assertRegex(name, CODE_FORMAT.pattern)
		self.assertIn("01", names)
		self.assertEqual(frappe.db.get_value("Downtime Reason", "01", "description"), "Setup")
		self.assertEqual(frappe.db.get_value("Downtime Reason", "23", "description"), "Inventory")
		self.assertTrue(names >= set(STANDARD_DOWNTIME_REASONS))

	def test_full_adoption_rewrites_loss_time_links(self) -> None:
		self.assertEqual(
			sorted(host_parity.loss_time_reason_values(self.stock_entry)), ["Inventory", "Setup Time"]
		)

		adopt_host_downtime_reason()

		self.assertEqual(sorted(host_parity.loss_time_reason_values(self.stock_entry)), ["01", "23"])

	def test_full_adoption_rewrites_loss_time_links_on_submitted_entries(self) -> None:
		submitted = host_parity.make_host_stock_entry_with_loss_times(
			["Setup Time", "Inventory"], submit=True
		)
		self.addCleanup(host_parity.discard_stock_entry, submitted)

		adopt_host_downtime_reason()

		self.assertEqual(sorted(host_parity.loss_time_reason_values(submitted)), ["01", "23"])

	def test_full_adoption_is_idempotent(self) -> None:
		adopt_host_downtime_reason()
		after_first = _reason_rows()
		meta_after_first = host_parity.doctype_snapshot()

		adopt_host_downtime_reason()

		self.assertEqual(_reason_rows(), after_first)
		self.assertEqual(host_parity.doctype_snapshot(), meta_after_first)
		self.assertEqual(sorted(host_parity.loss_time_reason_values(self.stock_entry)), ["01", "23"])

	def test_full_adoption_leaves_host_owned_stock_entry_metadata_untouched(self) -> None:
		branch_reqd = frappe.db.get_value(
			"Property Setter",
			{"doc_type": "Stock Entry", "field_name": "branch", "property": "reqd"},
			"value",
		)
		purpose_field = frappe.get_meta("Stock Entry").get_field("custom_stock_entry_purpose")
		purpose_before = (purpose_field.fieldtype, purpose_field.read_only) if purpose_field else None
		se_fields_before = tuple(f.fieldname for f in frappe.get_meta("Stock Entry").fields)
		bom_has_operation = frappe.get_meta("BOM").get_field("custom_operation") is not None

		adopt_host_downtime_reason()

		self.assertEqual(
			frappe.db.get_value(
				"Property Setter",
				{"doc_type": "Stock Entry", "field_name": "branch", "property": "reqd"},
				"value",
			),
			branch_reqd,
		)
		purpose_after = frappe.get_meta("Stock Entry").get_field("custom_stock_entry_purpose")
		self.assertEqual(
			(purpose_after.fieldtype, purpose_after.read_only) if purpose_after else None,
			purpose_before,
		)
		self.assertEqual(tuple(f.fieldname for f in frappe.get_meta("Stock Entry").fields), se_fields_before)
		self.assertEqual(frappe.get_meta("BOM").get_field("custom_operation") is not None, bom_has_operation)


class TestAdoptionFailurePaths(HostParityTestCase):
	def test_schema_adoption_throws_on_unexpected_shape(self) -> None:
		"""A code field beside the host identity marks an unknown, unadoptable shape."""
		host_parity.delete_downtime_reason_doctype()
		host_parity.install_host_downtime_reason_doctype(
			extra_fields=({"fieldname": "code", "fieldtype": "Data"},)
		)
		host_parity.insert_host_downtime_reason("Setup Time")
		before = host_parity.doctype_snapshot()

		with self.assertRaises(frappe.ValidationError):
			adopt_host_downtime_reason_schema()

		self.assertEqual(host_parity.doctype_snapshot(), before)
		self.assertFalse(Path(adoption_export_path()).exists())
		self.assertTrue(frappe.db.exists("Downtime Reason", "Setup Time"))

	def test_schema_adoption_throws_on_code_named_custom_shape_without_export(self) -> None:
		"""A code-named custom DocType we did not reshape is unexpected, not pending-sync.

		Only our own partial reshape leaves the recovery export on disk; without
		that evidence the shape is an unknown host state and must fail fast.
		"""
		host_parity.delete_downtime_reason_doctype()
		host_parity.install_host_downtime_reason_doctype(
			extra_fields=({"fieldname": "code", "fieldtype": "Data"},),
			autoname="field:code",
		)
		host_parity.insert_host_downtime_reason("Setup Time", code="01")
		before = host_parity.doctype_snapshot()

		with self.assertRaises(frappe.ValidationError):
			adopt_host_downtime_reason_schema()

		self.assertEqual(host_parity.doctype_snapshot(), before)
		self.assertFalse(Path(adoption_export_path()).exists())

	def test_schema_adoption_rejects_submittable_host_doctype(self) -> None:
		"""The host DocType is non-submittable (staging-aligned); submittable is unexpected."""
		host_parity.delete_downtime_reason_doctype()
		host_parity.install_host_downtime_reason_doctype(is_submittable=True)
		host_parity.insert_host_downtime_reason("Setup Time")
		before = host_parity.doctype_snapshot()

		with self.assertRaises(frappe.ValidationError):
			adopt_host_downtime_reason_schema()

		self.assertEqual(host_parity.doctype_snapshot(), before)
		self.assertFalse(Path(adoption_export_path()).exists())


class TestAdoptionRecovery(HostParityWithLinksTestCase):
	def test_verification_failure_throws_with_details(self) -> None:
		adopt_host_downtime_reason()
		frappe.db.set_value(
			"Loss Time",
			{"parent": self.stock_entry, "loss_type": "01"},
			"loss_type",
			"Setup Time",
			update_modified=False,
		)

		with self.assertRaises(frappe.ValidationError) as raised:
			adopt_host_downtime_reason()

		self.assertIn("verification failed", str(raised.exception))
		self.assertIn("Setup Time", str(raised.exception))

	def test_verification_flags_dropped_link_rows(self) -> None:
		adopt_host_downtime_reason()
		frappe.db.delete("Loss Time", {"parent": self.stock_entry, "loss_type": "23"})

		with self.assertRaises(frappe.ValidationError) as raised:
			adopt_host_downtime_reason()

		self.assertIn("row count changed", str(raised.exception))

	def test_partial_adoption_converges_on_full_sequence_rerun(self) -> None:
		adopt_host_downtime_reason_schema()

		adopt_host_downtime_reason()

		names = sorted(row["name"] for row in _reason_rows())
		self.assertTrue(all(CODE_FORMAT.fullmatch(name) for name in names))
		self.assertEqual(sorted(host_parity.loss_time_reason_values(self.stock_entry)), ["01", "23"])
