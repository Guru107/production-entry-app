from __future__ import annotations

import ast
from pathlib import Path

from frappe.tests.utils import FrappeTestCase


PACKAGE_ROOT = Path(__file__).parent


class TestSecurityGuidelines(FrappeTestCase):
	def test_whitelisted_methods_are_fully_typed(self) -> None:
		violations = []
		for path, tree in self._production_trees():
			for node in ast.walk(tree):
				if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
					continue
				if not any(self._is_whitelist_decorator(item) for item in node.decorator_list):
					continue
				parameters = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
				missing = [arg.arg for arg in parameters if arg.arg != "self" and arg.annotation is None]
				if missing or node.returns is None:
					violations.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}")

		self.assertEqual(violations, [], "Untyped whitelisted methods: " + ", ".join(violations))

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
		result = []
		for path in PACKAGE_ROOT.rglob("*.py"):
			if path.name.startswith("test_") or path.name == "test_bootstrap.py":
				continue
			result.append((path, ast.parse(path.read_text(), filename=str(path))))
		return result

	@staticmethod
	def _is_whitelist_decorator(node: ast.AST) -> bool:
		return (
			isinstance(node, ast.Call)
			and isinstance(node.func, ast.Attribute)
			and node.func.attr == "whitelist"
			and isinstance(node.func.value, ast.Name)
			and node.func.value.id == "frappe"
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
