# codex-workflows

Personal Codex working conventions and reusable skills for macOS and Linux. A
committed source revision is validated, copied into a release directory, and
registered through symlinks. Updates are explicit and reversible.

The private repository is
[`belevtsev/codex-workflows`](https://github.com/belevtsev/codex-workflows).
Configure personal Git authentication before cloning. Git, Python 3.9 or newer,
and Codex are prerequisites; Python's `venv` module must be available.

## Install on a new machine

```sh
git clone https://github.com/belevtsev/codex-workflows.git ~/.agents/sources/codex-workflows
cd ~/.agents/sources/codex-workflows
export PYTHONDONTWRITEBYTECODE=1
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/validate_suite.py
.venv/bin/python scripts/bootstrap.py install
```

Review the dry run, then activate that validated commit:

```sh
.venv/bin/python scripts/bootstrap.py install --apply
.venv/bin/python scripts/bootstrap.py status
```

Use a clean, committed checkout. The local `.venv` is ignored by Git. The
installer manages the ten registrations listed in `skills-manifest.json` and a
marked block in the global Codex `AGENTS.md`; unrelated content is preserved.
It does not copy an entire Codex configuration, credentials, or project rules.

For Linux, manually merge these two settings into the existing Codex
`config.toml` under `CODEX_HOME` (normally `~/.codex`):

```toml
model = "gpt-6.1-sol"
model_reasoning_effort = "ultra"
```

The bootstrap leaves configuration settings untouched. The coordinator's model
policy also defaults substantive work to `gpt-6.1-sol` with `ultra`; Codex must
offer that model and effort in the active environment. See
[workflow and local integrations](docs/workflow.md) for the policy and optional
service setup.

Start a fresh Codex chat after activation and use this verification prompt:

```text
Verify this installation using read-only local evidence. Report the global
working-conventions block, all ten managed skill registrations, active release
and source SHA, and the coordinator and worker defaults in the installed model
policy. Confirm task-orchestration and typesafe-ai were automatically available
in your initial skills catalog. Compare the main Codex defaults with
gpt-6.1-sol / ultra. Identify any mismatch. Do not run tests, consult Jev, or
write to external services.
```

Expected results are ten unique managed registrations, 55 included skill
entrypoints, an intact global managed block, and matching source/active SHAs
immediately after installation. The coordinator uses Sol 6.1 `ultra`, bounded
lookup uses Luna `high`, and bounded execution uses Luna `max`. Both named
skills should be automatically available. Verify connector identities and a
permitted read separately on the new machine.

## Included registrations

| Registration | Purpose |
| --- | --- |
| `task-orchestration` | Coordinate substantial work, model routing, and evidence |
| `code-review` | Review concrete correctness and compatibility risks |
| `go-principal-engineer` | Resolve production Go ownership and lifecycle decisions |
| `software-architecture` | Assess component boundaries and interface evolution |
| `test-strategy` | Choose verification for changed behavior |
| `security-threat-model` | Build a threat model grounded in repository evidence |
| `cc-skills-golang` | Collection of Go specialist skills |
| `db-postgres` | Diagnose PostgreSQL behavior against actual evidence |
| `drawio-skill` | Create editable diagrams and inspect rendered exports |
| `typesafe-ai` | Use TypeSafe and Jev for scoped semantic judgments |

See [third-party provenance and notices](THIRD_PARTY.md) for vendored material.
Skill registration does not install each skill's optional tools or services.

## Maintain the installation

Every mutating command defaults to a dry run. Add `--apply` only after reviewing
the plan.

```sh
.venv/bin/python scripts/bootstrap.py update
.venv/bin/python scripts/bootstrap.py update --apply
.venv/bin/python scripts/bootstrap.py rollback
.venv/bin/python scripts/bootstrap.py recover
.venv/bin/python scripts/bootstrap.py uninstall
```

`update --apply` fetches and validates `origin/main`, then activates its exact
commit. `rollback` selects the previous validated active release recorded in
history. `recover` repairs an interrupted activation. Local changes and
unrelated registrations are protected by ownership checks.

Read [installation operations](docs/operations.md) for migration, custom paths,
and recovery, and [development checks](docs/development.md) before changing the
suite. There is no startup hook, scheduled synchronization, or automatic update.
