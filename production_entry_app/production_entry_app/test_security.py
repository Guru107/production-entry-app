from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

PACKAGE_ROOT = Path(__file__).parent


class TestSecurityGuidelines(FrappeTestCase):
	def test_whitelisted_methods_are_fully_typed(self) -> None:
		violations = []
		for path, node, _decorator in self._whitelisted_functions():
			parameters = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
			missing = [arg.arg for arg in parameters if arg.arg != "self" and arg.annotation is None]
			if missing or node.returns is None:
				violations.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}")

		self.assertEqual(violations, [], "Untyped whitelisted methods: " + ", ".join(violations))

	def test_whitelisted_methods_declare_http_methods(self) -> None:
		violations = [
			f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}"
			for path, node, decorator in self._whitelisted_functions()
			if not any(keyword.arg == "methods" for keyword in getattr(decorator, "keywords", []))
		]

		self.assertEqual(violations, [], "Whitelisted methods without methods=: " + ", ".join(violations))

	def test_whitelist_detection_covers_bare_and_imported_decorators(self) -> None:
		tree = ast.parse(
			"@frappe.whitelist\ndef a(): pass\n"
			"@whitelist()\ndef b(): pass\n"
			"@frappe.whitelist(methods=['GET'])\ndef c(): pass\n"
			"@other.whitelist()\ndef d(): pass\n"
		)
		detected = [
			node.name
			for node in tree.body
			if any(self._is_whitelist_decorator(decorator) for decorator in node.decorator_list)
		]
		self.assertEqual(detected, ["a", "b", "c"])

	def test_write_endpoints_are_post_only(self) -> None:
		from production_entry_app.production_entry_app.api import reset_die_tool_counter
		from production_entry_app.production_entry_app.doctype.shift.shift import Shift

		for method in (reset_die_tool_counter, Shift.start_shift, Shift.end_shift, Shift.cancel_shift):
			self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[method], ["POST"], method)

	def test_production_code_avoids_raw_sql_code_execution_and_direct_file_open(self) -> None:
		violations = []
		for path, tree in self._production_trees():
			for node in ast.walk(tree):
				if not isinstance(node, ast.Call):
					continue
				if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "open"}:
					violations.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}:{node.func.id}")
				if (
					isinstance(node.func, ast.Attribute)
					and node.func.attr == "sql"
					and isinstance(node.func.value, ast.Attribute)
					and node.func.value.attr == "db"
				):
					violations.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}:db.sql")

		self.assertEqual(violations, [], "Dangerous primitives: " + ", ".join(violations))

	def test_values_passed_to_frappe_bold_are_html_escaped(self) -> None:
		violations = []
		for path, tree in self._production_trees():
			for node in ast.walk(tree):
				if not self._is_frappe_call(node, "bold") or not node.args:
					continue
				if not self._is_frappe_utils_call(node.args[0], "escape_html"):
					violations.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}")

		self.assertEqual(violations, [], "Unescaped frappe.bold values: " + ", ".join(violations))

	@staticmethod
	def _production_trees() -> list[tuple[Path, ast.Module]]:
		cached = getattr(TestSecurityGuidelines, "_cached_trees", None)
		if cached is not None:
			return cached
		result: list[tuple[Path, ast.Module]] = []
		for path in PACKAGE_ROOT.rglob("*.py"):
			if path.name.startswith("test_"):
				continue
			result.append((path, ast.parse(path.read_text(), filename=str(path))))
		TestSecurityGuidelines._cached_trees = result
		return result

	@classmethod
	def _whitelisted_functions(
		cls,
	) -> Iterator[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef, ast.expr]]:
		for path, tree in cls._production_trees():
			for node in ast.walk(tree):
				if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
					continue
				for decorator in node.decorator_list:
					if cls._is_whitelist_decorator(decorator):
						yield path, node, decorator

	@staticmethod
	def _is_whitelist_decorator(node: ast.AST) -> bool:
		# Matches @frappe.whitelist, @frappe.whitelist(...), @whitelist and @whitelist(...).
		target = node.func if isinstance(node, ast.Call) else node
		if isinstance(target, ast.Name):
			return target.id == "whitelist"
		return (
			isinstance(target, ast.Attribute)
			and target.attr == "whitelist"
			and isinstance(target.value, ast.Name)
			and target.value.id == "frappe"
		)

	@staticmethod
	def _is_frappe_call(node: ast.AST, method: str) -> bool:
		return (
			isinstance(node, ast.Call)
			and isinstance(node.func, ast.Attribute)
			and node.func.attr == method
			and isinstance(node.func.value, ast.Name)
			and node.func.value.id == "frappe"
		)

	@staticmethod
	def _is_frappe_utils_call(node: ast.AST, method: str) -> bool:
		return (
			isinstance(node, ast.Call)
			and isinstance(node.func, ast.Attribute)
			and node.func.attr == method
			and isinstance(node.func.value, ast.Attribute)
			and node.func.value.attr == "utils"
			and isinstance(node.func.value.value, ast.Name)
			and node.func.value.value.id == "frappe"
		)
