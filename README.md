# codex-workflows

Personal Codex working conventions and reusable skills for macOS and Linux. A
committed source revision is validated, copied into a release directory, and
registered through symlinks. Updates are explicit and reversible.

The public repository is
[`belevtsev/codex-workflows`](https://github.com/belevtsev/codex-workflows).
Cloning over HTTPS does not require a GitHub account or personal credentials.
Git, Python 3.9 or newer, and Codex are prerequisites; Python's `venv` module
must be available.

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
For an existing installation, rerun `./install.sh` after updating to enroll `cw`.

Setup also adds a managed `cw` shell function to `.zshrc` or `.bashrc`, selected
from `SHELL`. It runs this checkout's `install.sh` from any directory. Keep the
checkout at its chosen location. Open a new terminal after setup; to load the
command in an existing terminal, run the matching command:

```sh
source ~/.zshrc   # zsh
source ~/.bashrc  # Bash
```

Run only the line for your shell. A Bash login shell may not load `.bashrc`
automatically; source it explicitly or use your local profile to load it.
Setup accepts `--shell bash`, `--shell zsh`, or `--shell none` to override
selection, for example `./install.sh setup --shell bash`. An unrecognized shell
or non-default zsh `ZDOTDIR` skips command registration and reports it; workflow
installation still proceeds. For a custom zsh startup directory, define the
function in your chosen startup file yourself, replacing the example path:

```sh
cw() { '/absolute/checkout/install.sh' "$@"; }
```

The canonical `./install.sh` entry point remains available.

Help is available offline, including before installation or environment setup:

```sh
./install.sh help
cw help
cw --help
cw help update
cw update --help
```

Use `./install.sh help` until the shell function is loaded. `cw` accepts the
same actions and options as `./install.sh`; running it without an action starts
setup.

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
block in the global Codex `AGENTS.md`, its managed `cw` block in the selected
shell startup file, and these two root settings in the machine's existing
`config.toml`:

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

## Set up Jev

Setup registers the bundled [TypeSafe skill](vendor/typesafe-ai/SKILL.md).
Jev is a hosted TypeSafe model; there is no separate `jev` executable to install.
A key is optional for installation and local status.

1. Open the official [TypeSafe Console API keys page](https://console.typesafe.ai/keys),
   sign in or create an account as offered, and obtain an API key. The official
   [quick start](https://docs.typesafe.ai/introduction/quickstart) links to this page.
   Account access and key availability are controlled by TypeSafe.
2. Store the key in a local secret manager. For a temporary terminal session,
   use the matching masked prompt below; the key itself is neither displayed
   nor typed into shell history. Keep shell tracing disabled.

Bash:

```bash
set +x
IFS= read -r -s -p 'TypeSafe API key: ' TYPESAFE_API_KEY
printf '\n'
export TYPESAFE_API_KEY
```

zsh:

```zsh
set +x
read -r -s 'TYPESAFE_API_KEY?TypeSafe API key: '
printf '\n'
export TYPESAFE_API_KEY
```

3. Check the local environment, then start Codex CLI from that terminal:

```sh
cw status
codex
```

Status reports only `jev_credential_present`; it sends no API request and does
not prove the key is valid. The CLI inherits the exported key. A desktop app
started independently, or already running, does not receive later terminal
exports. Use your local secret manager or launch environment to supply
`TYPESAFE_API_KEY` to the desktop process, fully quit and restart it, then start
a fresh chat. Verify presence from that Codex environment separately.

To request an optional live check, paste this into that fresh chat:

```text
Use the installed typesafe-ai skill and its development-consultation guide to
verify Jev access. Check TYPESAFE_API_KEY presence without displaying it. If
present, make one small Choice request using only synthetic public text, the
installed pinned model policy (jev-1.13.0), a 30-second deadline, and no automatic
retries. Validate the response contract and report success or a safe failure
category. Do not change the model policy or send repository or company content.
Never print the key or authorization headers.
```

The check sends a request to TypeSafe and can incur usage. A valid response
confirms access for that request; it does not establish judgment accuracy.
Follow the [development-consultation guide](vendor/typesafe-ai/references/development-consultations.md)
for later use. Never commit integration credentials or place their values in
prompts, logs, screenshots, or shared evidence. See
[workflow and local integrations](docs/workflow.md#typesafe-and-jev) for the
consultation policy and source links.

## Maintain the installation

Launcher actions apply by default. Use `--dry-run` to preview a mutation.

```sh
cw status
cw update --dry-run
cw update
cw rollback
cw recover
cw uninstall
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
It also removes the unchanged managed `cw` startup block while preserving
other shell configuration. Open a new terminal afterward to drop any function
already loaded in the current shell.

Direct `scripts/bootstrap.py` mutation commands continue to default to a dry
run and require `--apply`. This keeps existing automation compatible.

Read [installation operations](docs/operations.md) for migration, custom paths,
and recovery, and [development checks](docs/development.md) before changing the
suite. Jev credentials are optional and checked only for presence; setup makes
no consultation calls. Authenticate connected services separately on each
device. There is no startup hook, scheduled synchronization, or automatic update.
