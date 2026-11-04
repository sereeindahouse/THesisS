"""Make root-level unittest discovery include the complete test package.

Older tests share fixtures through bare ``test_*`` imports. Keep those imports
working when discovery imports a module as ``tests.test_*``; do not rewrite or
filter the suite and do not start any services from package import.
"""
from pathlib import Path
import sys

_FIXTURE_MODULES = str(Path(__file__).resolve().parent)
if _FIXTURE_MODULES not in sys.path:
    sys.path.insert(0, _FIXTURE_MODULES)
