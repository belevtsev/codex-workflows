# Installation operations

Run the bootstrap from the source checkout with its virtual-environment Python:

```sh
export PYTHONDONTWRITEBYTECODE=1
.venv/bin/python scripts/bootstrap.py status
```

`install`, `update`, `rollback`, `recover`, and `uninstall` show their plan unless
`--apply` is present. `status` reports the local installation. Validation and
dry runs do not require an API key.

## Paths and ownership

`--source` defaults to the repository containing `scripts/bootstrap.py`.
`--home` selects the user home, and `--codex-home` selects the Codex directory
(otherwise `CODEX_HOME`, then the selected home's `.codex` directory).
`--state-dir` overrides the state location. Otherwise state is stored under
`$XDG_STATE_HOME/codex-workflows`, or `~/.local/state/codex-workflows` when
`XDG_STATE_HOME` is unset.

The state directory contains a `releases/<SHA>` snapshot for each installed
commit, a `current` link, and the installer's ownership and activation records.
Skill registrations under `~/.agents/skills` point through the managed release.
The global Codex `AGENTS.md` has a managed block delimited by
`codex-workflows-start` and `codex-workflows-end`; bytes outside the block are
preserved. Repository-specific `AGENTS.md` files remain in their repositories.

Pass the same path overrides on subsequent commands for a custom installation:

```sh
.venv/bin/python scripts/bootstrap.py install \
  --home /path/to/user-home \
  --codex-home /path/to/codex-home \
  --state-dir /path/to/workflow-state
```

Do not edit release snapshots or the `current` link manually. Make maintained
changes in the source checkout, validate and commit them, then activate through
the bootstrap. It rejects conflicting paths and modified managed content so
that another installation or a local edit is not overwritten.

## Migrate an existing installation

Review existing registrations and keep the previous source until migration is
verified. Identify it explicitly rather than treating every existing skill as
owned by this repository:

```sh
.venv/bin/python scripts/bootstrap.py install \
  --migrate-from /path/to/previous-source
.venv/bin/python scripts/bootstrap.py install \
  --migrate-from /path/to/previous-source --apply
```

For the separately installed TypeSafe skill at `~/.codex/skills/typesafe-ai`, add
`--typesafe-legacy` to opt in. An explicit path must identify that same location
under the selected `--home`, for example
`--typesafe-legacy /path/to/user-home/.codex/skills/typesafe-ai`. Adoption requires
exactly the three matching vendored files and their modes. The installer keeps
an ownership-checked backup for restoration. Review the plan before applying it.
Credentials stay local and are not migration inputs.

## Update and rollback

```sh
.venv/bin/python scripts/bootstrap.py update
.venv/bin/python scripts/bootstrap.py update --apply
.venv/bin/python scripts/bootstrap.py status
```

A dry run validates the local source HEAD and reports the planned remote fetch;
it does not contact GitHub. An applied update fetches `origin/main`, validates
the selected commit, stages its exact SHA as a release, fast-forwards the clean
source checkout, and activates that release. Add `--no-checkout` to keep the
source checkout at its current commit while activating the fetched release.
Updates refuse diverged or rewound history and never activate uncommitted
source changes. Git authentication uses the machine's existing personal
configuration; the bootstrap does not install credentials.

Version 1 refuses an update that changes registration names or source roots.
Review such a manifest change, then use explicit uninstall and install commands
so the new ownership is established deliberately.

To return to the previous validated active release:

```sh
.venv/bin/python scripts/bootstrap.py rollback
.venv/bin/python scripts/bootstrap.py rollback --apply
.venv/bin/python scripts/bootstrap.py status
```

Rollback follows activation history and does not reset the source checkout's
Git revision. Open a fresh Codex chat after an update or rollback. An existing
chat can retain already loaded instructions, skill content, and model settings.

## Interrupted activation and removal

If activation was interrupted, inspect status and the recovery plan:

```sh
.venv/bin/python scripts/bootstrap.py status
.venv/bin/python scripts/bootstrap.py recover
.venv/bin/python scripts/bootstrap.py recover --apply
```

Recovery undoes the interrupted activation only when the expected ownership
still matches. A conflict requires reviewing and preserving the changed file
or registration before another attempt. A successful command or a new shell
does not by itself prove that recovery completed; check `status` afterward.

To remove managed registrations and the managed global block, restoring adopted
legacy registrations where applicable:

```sh
.venv/bin/python scripts/bootstrap.py uninstall
.venv/bin/python scripts/bootstrap.py uninstall --apply
.venv/bin/python scripts/bootstrap.py status
```

Uninstall checks ownership and protects local edits. It preserves unrelated
skills, global instructions, Codex configuration, and credentials. Release
snapshots remain cached in the state directory; uninstall reports that location.
