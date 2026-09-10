from __future__ import annotations

from frappe.tests.utils import FrappeTestCase


class TestNativeReportAccess(FrappeTestCase):
	def test_frappe_hooks_do_not_override_native_report_permissions(self) -> None:
		from production_entry_app import hooks

		permission_query_conditions = getattr(hooks, "permission_query_conditions", {})
		override_whitelisted_methods = getattr(hooks, "override_whitelisted_methods", {})
		self.assertNotIn("Report", permission_query_conditions)
		self.assertNotIn("frappe.desk.query_report.get_script", override_whitelisted_methods)
		self.assertNotIn("frappe.desk.query_report.run", override_whitelisted_methods)
