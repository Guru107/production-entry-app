"""Version compatibility layer for Frappe/ERPNext v15 and v16."""

from frappe import __version__ as frappe_version


def parse_frappe_major(version: str) -> int:
	"""Return the major version from a Frappe version string."""
	version_core = version.split("-")[0].split("~")[0]
	return int(version_core.split(".")[0])


FRAPPE_MAJOR: int = parse_frappe_major(frappe_version)

#: True when running on Frappe/ERPNext v16 or higher
IS_V16_OR_GREATER: bool = FRAPPE_MAJOR >= 16

#: True when running on Frappe/ERPNext v15
IS_V15: bool = FRAPPE_MAJOR == 15
