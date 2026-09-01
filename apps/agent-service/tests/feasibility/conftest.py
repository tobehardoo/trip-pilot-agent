"""Test support for the tests/feasibility package.

Makes the shared factories in tests/plan_evaluation_support.py importable
from sub-package tests, mirroring how pytest resolves root-level test
modules.  No production code is touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))
