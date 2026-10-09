#!/bin/sh
# Configure an existing Codex installation from this checkout.
set -eu
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1

checkout=$(CDPATH='' cd -P "$(dirname "$0")" && pwd)
for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
        exec "$candidate" "$checkout/scripts/setup.py" "$@"
    fi
done
printf '%s\n' 'codex-workflows: Python 3.9+ with the venv module is required. Install Python, then rerun ./install.sh.' >&2
exit 1
