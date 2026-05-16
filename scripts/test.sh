#!/usr/bin/env bash
# Pytest wrapper that pre-imports pymupdf before pytest collection.
# Required on macOS + Python 3.12 + current pymupdf wheel due to a
# load-order segfault in the SWIG C extension under pytest.
# See README "Known issues" section.

set -euo pipefail

exec .venv/bin/python -c "
import faulthandler; faulthandler.enable()
import pymupdf  # pre-load to dodge segfault
import sys, pytest
sys.exit(pytest.main(sys.argv[1:] or ['tests/']))
" "$@"