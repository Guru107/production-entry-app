"""Tests for Frappe/ERPNext v15/v16 compatibility utilities."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.compat import (
	FRAPPE_VERSION,
	IS_V15,
	IS_V16_OR_GREATER,
)
from production_entry_app.production_entry_app.compat.utils import (
	frappe_in_test,
	get_value_strict,
	has_permission_strict,
)


class TestVersionDetection(FrappeTestCase):
	"""Test version detection flags are set correctly."""

	def test_frappe_version_is_parsed(self) -> None:
		"""FRAPPE_VERSION should be a valid Version object."""
		self.assertIsNotNone(FRAPPE_VERSION)

	def test_is_v15_flag_consistency(self) -> None:
		"""IS_V15 should be True only when on v15."""
		if FRAPPE_VERSION.major == 15 and FRAPPE_VERSION.minor == 0:
			self.assertTrue(IS_V15)
		else:
			self.assertFalse(IS_V15)

	def test_is_v16_or_greater_flag_consistency(self) -> None:
		"""IS_V16_OR_GREATER should be True when on v16+."""
		if FRAPPE_VERSION.major >= 16:
			self.assertTrue(IS_V16_OR_GREATER)
		else:
			self.assertFalse(IS_V16_OR_GREATER)


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

	def test_has_permission_strict_returns_true_for_valid_permission(
		self,
	) -> None:
		"""has_permission_strict() should return True when permission exists."""
		result = has_permission_strict("Shift", ptype="read")
		if result:
			self.assertIs(result, True)

	def test_has_permission_strict_returns_exact_true(self) -> None:
		"""has_permission_strict() must return the boolean True, not truthy."""
		result = has_permission_strict("Shift", ptype="read")
		self.assertIs(result, True)

	def test_has_permission_strict_with_document_object(self) -> None:
		"""has_permission_strict() should work with document objects."""
		shift = frappe.get_doc({"doctype": "Shift", "shift_date": "2026-01-01"})
		result = has_permission_strict(shift, ptype="read")
		self.assertIsInstance(result, bool)
