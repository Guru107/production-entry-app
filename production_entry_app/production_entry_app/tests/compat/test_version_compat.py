"""Tests for Frappe/ERPNext v15/v16 compatibility utilities."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.compat import (
	FRAPPE_MAJOR,
	IS_V15,
	IS_V16_OR_GREATER,
	parse_frappe_major,
)
from production_entry_app.production_entry_app.compat.utils import (
	frappe_in_test,
	has_permission_strict,
)


class TestVersionDetection(FrappeTestCase):
	"""Test version detection flags are set correctly."""

	def test_is_v15_flag_consistency(self) -> None:
		"""IS_V15 should be True only when on Frappe v15."""
		self.assertEqual(IS_V15, FRAPPE_MAJOR == 15)

	def test_is_v16_or_greater_flag_consistency(self) -> None:
		"""IS_V16_OR_GREATER should be True when on Frappe v16+."""
		self.assertEqual(IS_V16_OR_GREATER, FRAPPE_MAJOR >= 16)

	def test_parse_frappe_major_matches_runtime_version(self) -> None:
		"""Runtime major version parsing should use the shared helper."""
		self.assertEqual(FRAPPE_MAJOR, parse_frappe_major(frappe.__version__))


class TestFrappeInTest(FrappeTestCase):
	"""Test frappe_in_test() compatibility wrapper."""

	def test_frappe_in_test_returns_bool(self) -> None:
		"""frappe_in_test() should return a boolean."""
		result = frappe_in_test()
		self.assertIsInstance(result, bool)

	def test_frappe_in_test_matches_native_flag(self) -> None:
		"""frappe_in_test() should return same value as native flag."""
		if IS_V16_OR_GREATER:
			self.assertEqual(frappe_in_test(), frappe.in_test)
		else:
			self.assertEqual(frappe_in_test(), bool(frappe.flags.in_test))


class TestHasPermissionStrict(FrappeTestCase):
	"""Test has_permission_strict() for v16-compatible permission checks."""

	def test_has_permission_strict_returns_bool(self) -> None:
		"""has_permission_strict() should return a boolean."""
		result = has_permission_strict("Shift", ptype="read")
		self.assertIsInstance(result, bool)

	def test_has_permission_strict_returns_exact_true(self) -> None:
		"""has_permission_strict() must return the boolean True, not truthy."""
		result = has_permission_strict("Shift", ptype="read")
		self.assertIs(result, True)

	def test_has_permission_strict_with_document_object(self) -> None:
		"""has_permission_strict() should work with document objects."""
		shift = frappe.get_doc({"doctype": "Shift", "shift_date": "2026-01-01"})
		result = has_permission_strict(shift, ptype="read")
		self.assertIsInstance(result, bool)
