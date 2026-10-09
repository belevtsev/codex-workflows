# Development checks

Maintain generic working practices in this repository. Project capabilities,
test commands, product protocols, incident records, and operational recipes
belong in the owning project's instructions or documentation. Keep credentials,
private audits, evaluations, historical baselines, and machine activation
records outside the source tree.

Python 3.9 or newer is supported. Use the pinned development dependency:

```sh
export PYTHONDONTWRITEBYTECODE=1
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

Before committing a change, run:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/python skills/task-orchestration/scripts/validate_policy.py
.venv/bin/python scripts/validate_suite.py
```

Run these commands in the environment authorized for the task. Tests use
isolated temporary homes and state directories; they must not alter the real
user installation or contact an external service. Validate representative
activation, ownership conflicts, rollback, recovery, migration, and uninstall
behavior rather than replacing the symlink operations with mocks everywhere.

The GitHub workflow runs all unit tests, policy validation, and suite validation
on `ubuntu-latest` and `macos-latest`, with Python 3.9 and 3.12. It needs no
service API keys. A local result covers its actual interpreter and operating
system; the CI matrix supplies separate portability evidence when it completes.

Keep `skills-manifest.json` authoritative for the ten registrations. Preserve
upstream notices in vendored files and update `THIRD_PARTY.md` when provenance
changes. Validate before staging a source commit for installation. The bootstrap
activates committed snapshots, so testing modified source is separate from
proving which SHA is installed.
