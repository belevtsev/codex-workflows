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
26 unique skill registrations with 71 skill entrypoints, a managed global instruction block, and the two
coordinator defaults in the existing Codex configuration:

```toml
model = "gpt-6.1-sol"
model_reasoning_effort = "max"
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
| production-plan | Build context-grounded implementation plans with independent design challenges |
| code-review | Review correctness and compatibility risks |
| go-principal-engineer | Resolve production Go ownership and lifecycle decisions |
| software-architecture | Assess boundaries and interface evolution |
| test-strategy | Choose verification for changed behavior |
| security-threat-model | Build a repository-grounded threat model |
| backend-security-review | Scope backend security checks and verify findings against reachable paths |
| protobuf-contracts | Review binary, generated API, and ProtoJSON evolution and peer compatibility |
| go-pki-mtls | Review reusable certificate, trust, and service identity lifecycles |
| cc-skills-golang | Go specialist skills |
| db-postgres | Diagnose PostgreSQL against actual evidence |
| drawio-skill | Create editable diagrams and inspect rendered exports |
| archify | Render portable, inspectable architecture and workflow diagrams |
| typesafe-ai | Use TypeSafe and Jev for scoped judgments |
| docker-agent-config | Author Docker Agent configuration |
| docker-agent-deploy | Expose Docker Agents through the requested server interface |
| docker-agent-run | Run Docker Agents with the appropriate execution mode |
| docker-build-strategies | Create and improve Dockerfiles |
| docker-compose-patterns | Configure and diagnose Docker Compose |
| docker-destructive-guardrails | Check authorization and scope before destructive Docker actions |
| docker-project-foundations | Establish Docker project configuration |
| docker-sandboxes-env | Author declarative sandbox environments |
| docker-sandboxes-kits | Package and validate sandbox kits |
| docker-sandboxes-lifecycle | Manage sandbox creation, execution, and removal |
| docker-sandboxes-network-credentials | Configure sandbox networking and credential access |

See [third-party notices](THIRD_PARTY.md). Bundled skill helpers remain with their
skills, including Python tools; they are separate from the Go manager.

Automatic discovery remains enabled. The pack excludes `slack-pr-review`.
Archify uses Node.js 18+ and Chrome/Chromium for browser verification. Optional
generators also need their declared Node packages. Docker Agent and Sandbox
skills require the corresponding tools and platform support. Setup and status
report locally detected or missing executables in `skill_prerequisites`; versions,
daemon access, and subcommands are checked when the skill is used. No optional
tool is installed or executed by this detection.

Archify's update helpers return a managed-distribution result without network or
cache activity. Use `cw update` for pack updates. Example rendering and generator
write modes require an explicit output directory outside the skill package;
symlink aliases into the package are refused. Check-only generator modes remain
available. See [import provenance and adaptations](third_party/personal-skill-imports.json).

### Backend skills

These skills support backend work across repositories. PKI/mTLS guidance covers
general certificate and identity lifecycles; product endpoints, credentials,
deployment commands, and incident history belong in their owning repositories.
Go architecture guidance extends go-principal-engineer with optional service-boundary
and distributed-workflow references for retries, idempotency, commit ordering,
and crash recovery.

Use a natural request or invoke a skill explicitly:

```text
$backend-security-review Review changed authorization paths and verify existing scanner findings. Do not run tests or install tools.
$protobuf-contracts Review this schema change against supported consumers and the generation workflow.
$go-pki-mtls Review trust rotation and identity binding, separating source evidence from observed handshakes.
$go-principal-engineer Plan durable job execution with explicit retry ownership and crash recovery.
```

Security review uses available repository tools and existing CI evidence. Missing
scanners are reported as evidence gaps; setup does not install them. Optional
Trail of Bits specialists can help when already available. Findings default to
chat and require source verification before becoming confirmed security defects.
Skill selection does not authorize tests, tool installation, publication,
credential changes, or infrastructure operations.

### One-time migration from manager v3, v4, or v5

After a release with manager protocol `cw-manager-v6` is published, run these
commands from your clean checkout:

```sh
git pull --ff-only
./install.sh --adopt-personal-skills
cw status
```

Older managers cannot validate manifest v2: ordinary `cw update` rejects it
before acquiring its replacement. The new bootstrap requires a v6 manager and
preserves historical ownership and recovery records. Subsequent updates use
`cw update` without the adoption flag.

Older v6 managers also need a one-time bootstrap upgrade for paired consultations:
they reject the additional policy fields before acquiring a new manager. Once a
compatible release is available, run `git pull --ff-only`, `./install.sh --dry-run`,
`./install.sh`, and `cw status` from the clean checkout. Existing managed personal
skills do not need the adoption flag again. Bootstrap requires both
`cw-manager-v6` and the separate `cw-model-policy-v2-dual-choice` capability. A
stale cached v6 manager is replaced only after verifying a compatible release;
an incompatible latest release leaves the old binary and owned installation intact.

The flag permits exactly one verified standalone directory per added personal
skill. It compares the complete original inventory, including Archify resources
omitted or adapted in this distribution, before moving it to an owned backup and
creating a managed link. Modified copies, duplicate discoveries, dangling links,
occupied backups, and incompatible filesystems are conflicts. Ordinary setup and
updates never adopt unowned occupied paths. Preview with
`./install.sh --adopt-personal-skills --dry-run`.

Uninstall restores the adopted directories and original settings. Rollback to a
snapshot omitting an adopted skill is refused to protect its original copy;
additions whose destinations were originally absent can be rolled back normally.

While the latest release still serves v3, v4, or v5, bootstrap fails safely before
replacing the previous binary or changing the owned installation. Retry after
v6 publication. Manager capability and exact source revision are separate checks:
when the downloaded
compatible manager differs from local HEAD, Go acquires the exact revision.
An unavailable exact release can require the Go version in go.mod to build source;
a published exact revision allows compiler-free setup. Merging, release
publication, and laptop activation are separate outcomes. See
[migration and recovery](docs/operations.md#migration).

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

Status reports `jev_credential_present` as a boolean; it sends no API request and does
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
Follow the [development-consultation guide](third_party/typesafe-ai/references/development-consultations.md)
for later use. The existing [Jev-only helper](skills/task-orchestration/scripts/consult_jev.py)
remains supported unchanged; the paired workflow below adds a separate helper.

## Set up SubQ Snap

Obtain a separate key from the official [SubQ API Console](https://console.subq.ai/),
following its [authentication guide](https://docs.subq.ai/using-the-api/authentication/).
Store it in a local secret manager outside the source tree. Jev uses
`TYPESAFE_API_KEY`; Snap uses `SUBQ_API_KEY`. Neither is required for installation
or local validation. Do not paste key values into chat or commit them.

For a temporary terminal session, use the matching masked prompt:

Bash:

```bash
set +x
IFS= read -r -s -p 'SubQ API key: ' SUBQ_API_KEY
printf '\n'
export SUBQ_API_KEY
```

zsh:

```zsh
set +x
read -r -s 'SUBQ_API_KEY?SubQ API key: '
printf '\n'
export SUBQ_API_KEY
```

Check presence without displaying the key:

```sh
if [ -n "${SUBQ_API_KEY:-}" ]; then
  printf 'SUBQ_API_KEY present: true\n'
else
  printf 'SUBQ_API_KEY present: false\n'
fi
cw status
codex
```

With this manager revision active, `cw status` reports `subq_credential_present`
alongside `jev_credential_present`. Both are offline booleans for the cw process;
they do not establish key validity or availability in a different Codex process.
Older installed managers may omit the Snap field; the shell presence check works
before activation. Starting Codex CLI from this terminal inherits the exported keys.

A desktop app launched independently does not inherit later terminal exports.
Supply the keys through its launch environment or local secret manager, fully quit
Codex, relaunch it, and open a fresh chat. On macOS, one session-only option is to
run this yourself in the terminal where the masked prompt set `SUBQ_API_KEY`:

```sh
set +x
launchctl setenv SUBQ_API_KEY "$SUBQ_API_KEY"
```

This supplies the value to subsequently launched GUI processes in the current
login session; it is not persistent secret storage. Use the same approach for
`TYPESAFE_API_KEY` when needed. Existing Codex or integration-server processes
keep their startup environment and metadata, so restart those processes and check
presence from the fresh Codex environment. Never print values or authentication
headers to verify access.

SubQ's documented Decisions model is [`subq-snap-preview`](https://docs.subq.ai/using-the-api/models/).
It is a public preview alias, so the workflow records the requested and returned
model rather than claiming an immutable version. SubQ
[retains request data indefinitely by default](https://docs.subq.ai/using-the-api/data-retention/);
organization-level zero data retention is available and applies to Decisions.
Confirm the task's sharing scope and retention policy before sending source evidence.

## Consult both models and let Codex decide

The [paired helper](skills/task-orchestration/scripts/consult_decisions.py) uses
the task-orchestration policy to send the same prepared Choice request to Jev and
SubQ Snap concurrently. It uses one attempt per provider and a 30-second batch
budget covering process startup, requests, and result transport, with bounded
worker cleanup afterward and no automatic retries. Python and PyYAML are optional skill
dependencies separate from the native Go manager; cw does not install them.

If your Python interpreter lacks PyYAML, create an isolated environment outside the
immutable skill snapshots and activate it before running the helper:

```sh
python3 -m venv ~/.venvs/codex-decisions
~/.venvs/codex-decisions/bin/python -m pip install 'PyYAML>=6,<7'
source ~/.venvs/codex-decisions/bin/activate
```

Codex commands can select that interpreter directly; activating it in another
terminal does not change the app's Python. After managed installation, use:

```sh
~/.venvs/codex-decisions/bin/python -B ~/.agents/skills/task-orchestration/scripts/consult_decisions.py --request /path/to/request.json --output /path/to/new-record.json
```

Prepare `{state, questions}` with exact permitted text evidence, source revision,
and neutral Choice options. From this editable checkout with the dependencies
available:

```sh
python3 -B skills/task-orchestration/scripts/consult_decisions.py --request /path/to/request.json --output /path/to/new-record.json --dry-run
python3 -B skills/task-orchestration/scripts/consult_decisions.py --request /path/to/request.json --output /path/to/new-record.json
```

The dry run validates and writes a record without network access. A live call can
incur usage with each provider and records independent success or safe failure
categories. Per-question agreement, disagreement, partial coverage, or unavailable
coverage describes the returned choices; `final_decision` initially stays `pending`.
One unavailable provider preserves the other's result while Codex continues source
work and reports the coverage limit.

Codex compares both judgments against exact sources and relevant tests or observations,
including when the models agree. Confidence and voting never choose the final answer.
After that verification, Codex writes its decision JSON and finalizes a new record
without making network requests:

```sh
python3 -B skills/task-orchestration/scripts/consult_decisions.py --adjudicate /path/to/new-record.json --decision /path/to/codex-decision.json --output /path/to/final-record.json
```

The [helper contract](skills/task-orchestration/references/consultation-helper.md)
describes the decision fields. Resolved decisions require source evidence,
verification, and a reason for rejecting each successful provider's differing choice.
Missing material facts leave the decision unresolved. A successful API response alone
does not establish judgment accuracy or implementation correctness.

Use the checkout helper to review this change before activation. The manager installs
immutable snapshots from a clean committed source; activate through the normal cw
installation/update flow only after the change is committed and that action is
authorized. Do not edit an installed release in place. Never place credentials in
prompts, logs, screenshots, or shared evidence, and sanitize request content before
sharing a record. See [workflow and local integrations](docs/workflow.md#typesafe-jev-and-subq-snap)
for the paired policy and source links.

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
Jev or SubQ keys, or test connectors. Pending recovery is reported instead of accepting
an incomplete installation.

`model_profiles` reports each named profile's configured `model`,
`reasoning_effort`, and `scope` from the active snapshot. These values describe
policy; they do not prove the model or effort used by an existing chat, or runtime
availability for the account. A rollback reports the restored snapshot's policy.

### Preview: cw update --dry-run

```sh
cw update --dry-run
```

Checks local source cleanliness, ancestry, validation, and ownership, and explains
the intended update. It does not fetch, download, build, or activate. Because the
preview does not contact GitHub, it cannot verify the current remote candidate or
guarantee a later applied update will succeed. Results include local
`registration_changes` with `add`, `move`, or `remove` actions; an offline preview
does not describe an unfetched remote manifest.
When `--no-checkout` previously left source behind the active snapshot, preview
reports `source_behind_active` and no known registration changes; the older local
manifest is not a removal request.

### Apply: cw update

```sh
cw update
```

Fetches origin/main, validates that exact commit, prepares its verified manager
binary, fast-forwards the clean non-divergent checkout, and activates the skills
and owned settings with recovery protection. Binary refresh is handled in Go.
Use `--no-checkout` to leave source HEAD unchanged while activating the fetched
snapshot. Failed preparation leaves the active installation unchanged.
New registration conflicts are checked before fast-forwarding source. Existing
names and roots are retained except supported legacy moves.

### Return to the previous skills: cw rollback

```sh
cw rollback
```

Restores the previous validated skill snapshot and its owned instructions/model
defaults. It follows activation history; it does not rewind Git, change GitHub,
or downgrade the compatible manager. Registration targets follow the rollback
snapshot, including older vendor paths. It preserves the original configuration
values reserved for uninstall. Add `--dry-run` to preview.
Skills absent from the rollback snapshot are removed only when their paths were
originally absent and still match the owned links. Adopted content cannot be dropped.
A rollback to a previous `ultra` policy snapshot restores those historical
defaults and keeps the compatible v6 manager.

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
For recovery without the checkout, invoke the verified v6 executable beneath
`STATE/runtime/releases/REVISION/cw`; its immutable locator retains the
installation roots.

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
working-conventions block, all 26 managed skill registrations, active release
and source SHA, installed manager identity, the direct cw executable, and the two
owned root config settings. Confirm task-orchestration and typesafe-ai were
automatically available in your initial skills catalog, along with
backend-security-review, protobuf-contracts, go-pki-mtls, production-plan, archify,
and the eleven Docker skills. Compare the main Codex
defaults with gpt-6.1-sol / max. Compare model_profiles with the configured
profiles: substantive work Sol 6.1 max, bounded execution Luna xhigh, and bounded
evidence Luna high. Do not run tests, consult Jev, or write to services.
```

Expected results are 26 registrations, 71 included skill entrypoints, matching
active/source SHAs immediately after installation, and a direct cw executable.
Coordinator/substantive work uses Sol 6.1 max, bounded evidence Luna high, and
bounded execution Luna xhigh. Authenticate GitHub, Jira, and Confluence separately
on each device and verify the intended identity and a permitted read.

See [operations](docs/operations.md) for migration, custom paths, and recovery;
[workflow and integrations](docs/workflow.md) for model policy and authentication;
and [development](docs/development.md) for native checks and releases.
