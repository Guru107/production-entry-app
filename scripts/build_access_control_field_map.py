#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from production_entry_app.production_entry_app.access_control_field_map import main

if __name__ == "__main__":
	raise SystemExit(main())
