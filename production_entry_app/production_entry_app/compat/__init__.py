"""Version compatibility layer for Frappe/ERPNext v15 and v16."""

from frappe import __version__ as frappe_version

_frappe_version_str = frappe_version.split("-")[0].split("~")[0]
_FRAPPE_MAJOR = int(_frappe_version_str.split(".")[0])

#: True when running on Frappe/ERPNext v16 or higher
IS_V16_OR_GREATER: bool = _FRAPPE_MAJOR >= 16

#: True when running on Frappe/ERPNext v15
IS_V15: bool = _FRAPPE_MAJOR == 15
