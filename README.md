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
git clone https://github.com/belevtsev/codex-workflows.git
cd codex-workflows
./install.sh
```

Choose any checkout location. `./install.sh` is the setup command: it creates or
reuses the ignored `.venv`, installs pinned PyYAML and tomlkit dependencies,
validates the committed source snapshot, activates it, and reads back status.
Use a clean, committed checkout. Setup uses local HEAD and does not fetch.

To preview setup before applying it:

```sh
./install.sh --dry-run
./install.sh status
```

The dry run makes no environment, download, or installation-state writes. If
the prepared environment is absent, it reports that full validation is deferred.
`status` is read-only and never prepares an environment; it requires the pinned
dependencies and reports a deferred status when they are missing.

Setup owns the ten registrations listed in `skills-manifest.json`, a marked
block in the global Codex `AGENTS.md`, and these two root settings in the
machine's existing `config.toml`:

```toml
model = "gpt-6.1-sol"
model_reasoning_effort = "ultra"
```

The settings come from the validated coordinator model policy. Unrelated
configuration, permissions, trusted projects, credentials, and project rules
are preserved. The original values or absence of the two owned settings are
retained until uninstall. Existing bootstrap `install` commands retain their
original behavior and do not enroll configuration; `setup` adds that enrollment,
including for an existing version 1 installation.

Codex must offer the selected model and effort in the active environment. See
[workflow and local integrations](docs/workflow.md) for the policy and optional
service setup.

Start a fresh Codex chat after activation and use this verification prompt:

```text
Verify this installation using read-only local evidence. Report the global
working-conventions block, all ten managed skill registrations, active release
and source SHA, the two owned root config settings, and the coordinator and
worker defaults in the installed model policy. Confirm task-orchestration and
typesafe-ai were automatically available in your initial skills catalog.
Compare the main Codex defaults with gpt-6.1-sol / ultra. Identify any mismatch.
Do not run tests, consult Jev, or write to external services.
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
Setup does not install Codex or each skill's optional tools and services.

## Maintain the installation

Launcher actions apply by default. Use `--dry-run` to preview a mutation.

```sh
./install.sh status
./install.sh update --dry-run
./install.sh update
./install.sh rollback
./install.sh recover
./install.sh uninstall
```

`update` explicitly fetches and validates `origin/main`, then activates its
exact commit. `rollback` selects the previous validated active release and its
coordinator defaults. `recover` repairs an interrupted activation. Repeating
setup at the same SHA leaves the release unchanged while enrolling configuration
if needed. Setup may activate a clean local fast-forward of the active release
when its registration manifest is unchanged.

Ownership checks protect local edits and unrelated registrations. Uninstall
restores the original owned config values or absence while preserving unrelated
later edits and comments. Changing an owned value, malformed TOML, or a
symlinked config causes a refusal that needs local review.

Direct `scripts/bootstrap.py` mutation commands continue to default to a dry
run and require `--apply`. This keeps existing automation compatible.

Read [installation operations](docs/operations.md) for migration, custom paths,
and recovery, and [development checks](docs/development.md) before changing the
suite. Jev credentials are optional and checked only for presence; setup makes
no consultation calls. Authenticate connected services separately on each
device. There is no startup hook, scheduled synchronization, or automatic update.
