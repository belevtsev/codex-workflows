# codex-workflows

Personal Codex working conventions and reusable skills for macOS and Linux. A
committed source revision is validated, copied into a release directory, and
registered through symlinks. Updates are explicit and reversible.

The public repository is
[`belevtsev/codex-workflows`](https://github.com/belevtsev/codex-workflows).
Cloning over HTTPS does not require a GitHub account or personal credentials.
Git and an existing Codex installation are prerequisites. Released native
`cw` binaries support macOS and Linux on ARM64 and AMD64. Python and a virtual
environment are not required by the installer. First setup needs `curl`, `tar`,
and `sha256sum` or macOS `shasum` to obtain and verify its binary. Building an
unreleased checkout locally requires the Go version pinned in `go.mod`.

## Install on a new machine

```sh
git clone https://github.com/belevtsev/codex-workflows.git
cd codex-workflows
./install.sh
```

Choose any checkout location. `./install.sh` obtains a native binary for the
exact checked-out release, verifies its checksum and embedded revision, then
validates the committed workflow snapshot, activates it, and reads back status.
The recognized binary is cached under the checkout's ignored `.bin` directory.
An unreleased checkout can build locally with Go; setup never substitutes a
binary from a different source revision.
When `cw update` advances this checkout, it also refreshes the cached installer
to the new source revision without repeating workflow activation.
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

The dry run makes no binary-cache, download, or installation-state writes. If
no recognized native binary is available, it reports that full validation is
deferred. `status` is read-only and never downloads or builds a binary; run
setup first when the local binary cache is missing.

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

Status reports only a boolean credential-presence field; it sends no API request and does
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

For a prepared Choice request file, the native CLI also supports:

```sh
cw consult-jev --request /path/to/request.json --output /path/to/new-record.json --dry-run
cw consult-jev --request /path/to/request.json --output /path/to/new-record.json
```

The dry run validates without network or output writes. The live command makes
one request, enforces the pinned policy and deadline, and writes a new private
record. Its parent directory must already exist; existing output files are
refused. The request is retained verbatim in that record, so sanitize its content
before sharing. The CLI prints a short status summary and never prints the key.

The check sends a request to TypeSafe and can incur usage. A valid response
confirms access for that request; it does not establish judgment accuracy.
Follow the [development-consultation guide](vendor/typesafe-ai/references/development-consultations.md)
for later use. Never commit integration credentials or place their values in
prompts, logs, screenshots, or shared evidence. See
[workflow and local integrations](docs/workflow.md#typesafe-and-jev) for the
consultation policy and source links.

## Maintain the installation

Choose the command for the task you want to perform. These are alternative
maintenance actions, not a sequence to run from top to bottom. Launcher
mutations apply by default; add `--dry-run` to preview one. Setup and update can
prepare a matching native binary first. Status and dry runs never download or
build one.

### `cw status`: inspect the local installation

```sh
cw status
```

Use status after setup or a maintenance action, or to diagnose a local ownership
conflict. It checks the active release snapshot and receipt, skill registrations,
managed global instructions, any enrolled model settings, and the managed `cw`
shell block. Its JSON report includes whether the suite is installed, the active
and previous release SHAs, registration names, coordinator model defaults,
config and command enrollment, and whether `TYPESAFE_API_KEY` is present.

Status is read-only and makes no network request. It does not check for a newer
GitHub release, validate the Jev key, or test connectors. A missing
recognized native binary causes a preparation error rather than a download.
If an unfinished mutation journal exists, status refuses and directs you to
recovery.

### `cw update --dry-run`: preview the local update checks

```sh
cw update --dry-run
```

Use this before updating to check whether the local installation and source
checkout are ready. With a prepared native binary, it validates clean, committed
local HEAD, checks installation ownership and compatible registration names and
roots, checks local ancestry, and reports the planned `origin/main` fetch.

The preview does not contact GitHub, download or build a binary, fast-forward the
checkout, or change installed workflows or Git state. Validation may use
temporary exports outside the checkout. If the native binary is missing,
it reports a preparation plan with validation deferred. Because it does not
fetch, it cannot validate the current remote commit or guarantee that a later
applied update will succeed.

### `cw update`: fetch and activate the latest `origin/main`

```sh
cw update
```

Use update when you want to install the remote `main` revision. It checks clean
local source and ownership, fetches `origin/main`, validates and caches that
exact commit as a release, fast-forwards the clean source checkout, and activates
the release. For a different release, activation changes the release pointer,
managed global instructions, any enrolled coordinator model defaults, and
history; skill registrations resolve through the new pointer. The launcher then
reads back status. Git uses the machine's existing authentication configuration.

Both local HEAD and the active release must be ancestors of the fetched commit.
Dirty source, diverged or rewound history, ownership conflicts, and changes to
registration names or source roots are refused. Review a manifest change before
explicitly uninstalling and setting up a new installation. Use
`cw update --no-checkout` to activate the fetched release while leaving the
source checkout at its current commit. Open a fresh Codex chat to load the new
instructions, skills, and model settings.

### `cw rollback`: return to the previous active release

```sh
cw rollback
```

Use rollback when a completed activation should be undone. It verifies the
current owned installation and the previous cached, validated release in
activation history, then restores that release's pointer, global instructions,
and any enrolled coordinator model defaults. The latest history entry is removed,
and the launcher reads back status. Original pre-install config values stay
reserved for uninstall.

Rollback requires a previous history entry; it does not select an arbitrary SHA
or fetch a release. It leaves the source checkout's Git revision unchanged and
keeps the enrolled `cw` command available through that checkout. Modified release
snapshots or owned content cause a refusal. Open a fresh Codex chat afterward.

### `cw recover`: undo an interrupted owned change

```sh
cw recover
```

Use recovery when a failed or interrupted setup, update, rollback, or uninstall
leaves a pending mutation journal. `cw recover --dry-run` checks that journal
and reports the number of planned reversals. Applied recovery verifies the
expected before/after ownership, reverses the journaled installation changes,
and clears the journal; the launcher then reads back status. Depending on the
interrupted action, this can restore registrations, adopted backups, global
instructions, model settings, the shell block, and activation state.

With no pending journal, recovery reports `pending: false` and leaves installed
workflows unchanged. Recovery refuses to overwrite conflicting local edits and
does not generally rebuild a damaged installation. It also does not undo an
update's source-checkout fast-forward or remove the cached binary and workflow
releases. Preserve and review a conflicting path before retrying recovery.

### `cw uninstall`: remove the managed installation

```sh
cw uninstall
```

Use uninstall to stop using the suite, or before deliberately adopting a changed
registration manifest. It verifies ownership, removes managed skill
registrations and global instructions, restores adopted legacy registrations
where applicable, restores the original owned config values or their absence,
and removes the managed `cw` startup block, active pointer, and ownership state.
The launcher then reads back an uninstalled status.

Unrelated later config edits and comments, shell configuration, skills, global
instructions, and credentials are preserved. Changed owned values, malformed
TOML, symlinked config paths, or other ownership conflicts cause a refusal that
needs local review. Uninstall retains the source checkout, its `.bin` cache, and
cached release snapshots, and reports the release-cache location. Open a new
terminal afterward to drop the function already loaded in the current shell;
use `./install.sh` for later setup or status once `cw` is no longer loaded.

### Local setup and further operations

Repeating setup at the same SHA leaves the release unchanged while enrolling
configuration if needed. Setup may activate a clean local fast-forward of the
active release when its registration manifest is unchanged; it does not fetch.
Only setup and update require clean current source. Setup validates local HEAD;
an applied update validates the fetched candidate before activation.
Status, rollback, recovery, and uninstall use owned installation state even if
current source is dirty or its suite content is invalid. They still require a
usable launcher and a recognized native binary.

Ownership checks protect local edits and unrelated registrations. Do not edit
cached releases or the active pointer manually.

The native compatibility interface, `.bin/cw --bootstrap`, defaults mutations
to a dry run and requires `--apply`. The previous Python implementation remains
in source as a regression reference; the installed launcher executes Go.

Read [installation operations](docs/operations.md) for migration, custom paths,
and recovery, and [development checks](docs/development.md) before changing the
suite. Jev credentials are optional and checked only for presence; setup makes
no consultation calls. Authenticate connected services separately on each
device. There is no startup hook, scheduled synchronization, or automatic update.

## Native releases

Every push to `main`, including a merged pull request, runs native tests on
Linux and macOS. Once both pass, the workflow publishes `v1.0.<run number>` for
that exact commit. Re-running a workflow keeps the same version and reconciles
existing assets rather than overwriting them. Pull requests validate without
publishing releases.

Each [GitHub release](https://github.com/belevtsev/codex-workflows/releases)
contains `cw_darwin_arm64.tar.gz`, `cw_darwin_amd64.tar.gz`,
`cw_linux_arm64.tar.gz`, `cw_linux_amd64.tar.gz`, and `SHA256SUMS`.
`./install.sh` selects the platform automatically. `cw version` reports its
version, source revision, and build platform. Updates remain manual with
`cw update`; a released binary does not install Codex or authenticate services.
