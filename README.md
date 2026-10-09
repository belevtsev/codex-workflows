# codex-workflows

A Go skill manager for personal Codex workflows on macOS and Linux. Skills,
templates, and model policy remain editable files in this public
[repository](https://github.com/belevtsev/codex-workflows). The manager validates
committed revisions and installs immutable device-local snapshots. Updates are
manual and reversible.

## Install on a new machine

```sh
git clone https://github.com/belevtsev/codex-workflows.git
cd codex-workflows
./install.sh
```

You need Git, an existing Codex installation, and the standard bootstrap tools:
`curl`, `tar`, and `sha256sum` or macOS `shasum`. Released binaries support
macOS/Linux on ARM64 and AMD64. The manager needs no Python, virtual environment,
or Go installation. Building an unreleased revision requires the Go version in
[go.mod](go.mod). Individual skills retain their optional tool requirements.

The shell bootstrap only obtains a verified executable and executes it. All
installation, validation, updates, status, and recovery run in Go. Setup installs
ten unique skill registrations, a managed global instruction block, and the two
coordinator defaults in the existing Codex configuration:

```toml
model = "gpt-6.1-sol"
model_reasoning_effort = "ultra"
```

Unrelated settings, comments, credentials, project rules, and file permissions
are preserved. The original owned settings are retained for uninstall.

Setup creates `~/.local/bin/cw` as a direct link to the installed Go binary. It
adds a managed PATH entry to your Bash/zsh startup file only when needed. It does
not create a command wrapper. Open a new terminal, or load the matching file:

```sh
source ~/.zshrc   # zsh
source ~/.bashrc  # Bash
```

Run only the line for your shell. During migration, an already running shell can
retain the old cw function; open a new terminal or use `unfunction cw` in zsh /
`unset -f cw` in Bash before reloading. Bash login shells may need their profile
to load .bashrc. Use `--shell bash`, `--shell zsh`, or `--shell none` to override
automatic selection. Unsupported/custom startup locations require adding the
reported command directory to PATH manually. An existing unowned cw command is
a conflict, never silently replaced.

The installation records its source and custom home/Codex/state paths. cw works
from any directory. Keep the checkout for installation and updates; status,
rollback, recovery, and uninstall use installed records and snapshots even if
the checkout is unavailable. Manager version and active skill revision are
reported separately. Skills are not embedded in the executable.

```sh
./install.sh --dry-run
cw help
cw help update
cw version
```

Dry runs do not download, fetch, build, or change persistent state. Before the
bootstrap has a binary, it reports that validation is deferred. Running cw
without a command installs or verifies local HEAD; `cw install` is explicit and
`cw setup` is a compatibility alias. Mutations apply by default.

## Included registrations

| Registration | Purpose |
| --- | --- |
| task-orchestration | Coordinate substantial work, models, assumptions, and evidence |
| code-review | Review correctness and compatibility risks |
| go-principal-engineer | Resolve production Go ownership and lifecycle decisions |
| software-architecture | Assess boundaries and interface evolution |
| test-strategy | Choose verification for changed behavior |
| security-threat-model | Build a repository-grounded threat model |
| cc-skills-golang | Go specialist skills |
| db-postgres | Diagnose PostgreSQL against actual evidence |
| drawio-skill | Create editable diagrams and inspect rendered exports |
| typesafe-ai | Use TypeSafe and Jev for scoped judgments |

See [third-party notices](THIRD_PARTY.md). Bundled skill helpers remain with their
skills, including Python tools; they are separate from the Go manager.

## Set up Jev

Setup registers the bundled [TypeSafe skill](third_party/typesafe-ai/SKILL.md).
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

Prepared Choice requests belong to the task-orchestration skill, not the
installation manager. Its optional [consultation helper](skills/task-orchestration/scripts/consult_jev.py)
uses Python and PyYAML; other integrations can follow the TypeSafe HTTP/SDK guide.
These are skill-specific dependencies and are not installed by cw. For example,
from the checkout with the helper's dependencies available:

```sh
python3 skills/task-orchestration/scripts/consult_jev.py --request /path/to/request.json --output /path/to/new-record.json --dry-run
python3 skills/task-orchestration/scripts/consult_jev.py --request /path/to/request.json --output /path/to/new-record.json
```

The dry run validates without network or output writes. The live helper makes
one pinned-model request and writes a private task record. Sanitize request
content before sharing the record. Never display the key.

The check sends a request to TypeSafe and can incur usage. A valid response
confirms access for that request; it does not establish judgment accuracy.
Follow the [development-consultation guide](third_party/typesafe-ai/references/development-consultations.md)
for later use. Never commit integration credentials or place their values in
prompts, logs, screenshots, or shared evidence. See
[workflow and local integrations](docs/workflow.md#typesafe-and-jev) for the
consultation policy and source links.

## Maintain the installation

These commands are alternatives, not a sequence to execute together. Installation
and update require a clean committed checkout. Other maintenance commands use
installed ownership records. Their JSON results go to stdout; errors go to stderr.

### Inspect: cw status

```sh
cw status
```

Verifies the active snapshot, registrations, global instructions, owned model
settings, and direct command registration. Reports active/previous revisions and
manager identity. It is offline: it does not check for a remote update, validate
a Jev key, or test connectors. Pending recovery is reported instead of accepting
an incomplete installation.

### Preview: cw update --dry-run

```sh
cw update --dry-run
```

Checks local source cleanliness, ancestry, validation, and ownership, and explains
the intended update. It does not fetch, download, build, or activate. Because the
preview does not contact GitHub, it cannot verify the current remote candidate or
guarantee a later applied update will succeed.

### Apply: cw update

```sh
cw update
```

Fetches origin/main, validates that exact commit, prepares its verified manager
binary, fast-forwards the clean non-divergent checkout, and activates the skills
and owned settings with recovery protection. Binary refresh is handled in Go.
Use `--no-checkout` to leave source HEAD unchanged while activating the fetched
snapshot. Failed preparation leaves the active installation unchanged.

### Return to the previous skills: cw rollback

```sh
cw rollback
```

Restores the previous validated skill snapshot and its owned instructions/model
defaults. It follows activation history; it does not rewind Git, change GitHub,
or downgrade the compatible manager. Registration targets follow the rollback
snapshot, including older vendor paths. It preserves the original configuration
values reserved for uninstall. Add `--dry-run` to preview.

### Repair an interrupted change: cw recover

```sh
cw recover
```

Reverses owned changes recorded in an unfinished transaction, including runtime
and command registration changes. With no journal it is a no-op. It preserves
unrelated edits and refuses modified owned content. Recovery does not rewind a
Git fast-forward or delete caches. Do not manually edit the journal; inspect
`cw recover --dry-run` first. If a crash happened before the command link exists,
use the verified cached executable or rerun the bootstrap with `recover`.

### Remove managed installation: cw uninstall

```sh
cw uninstall
```

Removes owned skill registrations, instruction/PATH blocks and the cw command
link, restores adopted registrations and original model values, and preserves
unrelated content. Changed owned values cause a conflict. The checkout, immutable
caches, credentials, and connectors remain. Add `--dry-run` to inspect first.
After removal, use `./install.sh` from the checkout to reinstall.

## Verify installation and integrations

Start a fresh Codex chat after install, update, or rollback. Existing chats can
retain old instructions or model settings. Use this read-only verification prompt:

```text
Verify this installation using read-only local evidence. Report the global
working-conventions block, all ten managed skill registrations, active release
and source SHA, installed manager identity, the direct cw executable, and the two
owned root config settings. Confirm task-orchestration and typesafe-ai were
automatically available in your initial skills catalog. Compare the main Codex
defaults with gpt-6.1-sol / ultra. Do not run tests, consult Jev, or write to services.
```

Expected results are ten registrations, 55 included skill entrypoints, matching
active/source SHAs immediately after installation, and a direct cw executable.
Coordinator/substantive work uses Sol 6.1 ultra, bounded evidence Luna high, and
bounded execution Luna max. Authenticate GitHub, Jira, and Confluence separately
on each device and verify the intended identity and a permitted read.

See [operations](docs/operations.md) for migration, custom paths, and recovery;
[workflow and integrations](docs/workflow.md) for model policy and authentication;
and [development](docs/development.md) for native checks and releases.
