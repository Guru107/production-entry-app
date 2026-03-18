"""Version compatibility layer for Frappe/ERPNext v15 and v16."""

from frappe import __version__ as frappe_version
from packaging.version import Version

FRAPPE_VERSION = Version(frappe_version.split("-")[0].split("~")[0])

#: True when running on Frappe/ERPNext v16 or higher
IS_V16_OR_GREATER: bool = FRAPPE_VERSION >= Version("16.0.0")

#: True when running on Frappe/ERPNext v15
IS_V15: bool = FRAPPE_VERSION.major == 15 and FRAPPE_VERSION.minor == 0
