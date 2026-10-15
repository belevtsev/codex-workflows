# codex-workflows

A Go skill manager for personal Codex workflows on macOS and Linux. Install
editable skills, templates, model policy, and shared Codex defaults as verified,
immutable snapshots. Updates are manual and reversible.

This guide covers the [current release](https://github.com/belevtsev/codex-workflows/releases/latest).

## Install

```sh
git clone https://github.com/belevtsev/codex-workflows.git
cd codex-workflows
./install.sh
```

You need Codex, Git, `curl`, `tar`, and `sha256sum` or macOS `shasum`, plus
Python 3.7+ with `venv` and `ensurepip` support. Release binaries support
macOS/Linux on ARM64 and AMD64 and need no Go installation. Building an unreleased
revision requires the Go version in [go.mod](go.mod).

Installation registers 26 skills with 71 entrypoints, adds the managed global
working instructions, and sets these coordinator defaults in your existing
Codex configuration:

```toml
model = "gpt-6.1-sol"
model_reasoning_effort = "max"
```

It also applies the five shared memory settings from
[global/codex-defaults.toml](global/codex-defaults.toml):

```toml
[features]
memories = true

[memories]
generate_memories = true
use_memories = true
extract_model = "gpt-6.1-sol"
consolidation_model = "gpt-6.1-sol"
```

Local paths, MCP servers, project trust, credentials, unrelated settings, comments,
and permissions are preserved. Each device keeps its own configuration. Use
ordinary TOML tables or dotted keys for these shared settings; inline `features`
or `memories` tables must be converted before installation.

The manager prepares `~/.venvs/codex-decisions` with `PyYAML>=6,<7` for the
consultation helper. It reuses a healthy environment and repairs dependencies
inside it. It installs no system packages. A custom `--home` places the environment
under that home. Installation results report `consultation_runtime`.

Setup links `~/.local/bin/cw` directly to the installed binary and adds a managed
PATH entry to your Bash/zsh startup file when needed. Open a new terminal, then:

```sh
cw version
cw status
cw validate
```

Keep the checkout for installation and updates. The installed command works from
any directory; status, rollback, recovery, and uninstall use installed records
and snapshots. Manager version and active skill revision are reported separately.
Use `./install.sh --dry-run` to preview installation without downloading, building,
or changing persistent state. See [operations](docs/operations.md) for custom
paths, shell selection, and recovery.

## Current model policy

| Role | Model | Reasoning effort |
| --- | --- | --- |
| Coordination, substantive work, review, and final verification | `gpt-6.1-sol` | `max` |
| Bounded routine execution | `gpt-6-luna` | `xhigh` |
| Bounded evidence gathering | `gpt-6-luna` | `high` |
| Independent TypeSafe advice | `jev-1.14.0` | Provider managed |
| Independent SubQ advice | `subq-snap-preview` | Provider managed |
| Independent OpenAI Decisions advice | `gpt-6-luna` | Decisions API managed |

The editable [model policy](skills/task-orchestration/model-policy.yaml) defines
dispatch roles. Codex checks actual runtime model metadata; a saved policy does
not switch an existing chat or prove account availability. Codex makes the final
decision from source evidence and verification after considering all three required
advisers at equal standing.

## Included skills

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


See [third-party notices](THIRD_PARTY.md). Skill helpers keep their own optional
dependencies. Archify requires Node.js 18+ and Chrome/Chromium for browser checks;
Docker skills require the corresponding Docker tools and platform support.
`cw status` reports detected executables in `skill_prerequisites`; each skill
checks versions, access, and subcommands when used. The manager does not install
optional tools.

Use a natural request or invoke a skill explicitly:

```text
$production-plan Plan this change against the current repository contracts.
$code-review Review this diff for concrete correctness and compatibility defects.
$task-orchestration Implement this workflow, consult Jev, Snap and OpenAI Decisions at both checkpoints, and verify the result.
```

Repository commands, product details, and operational constraints belong in the
owning repository's instructions and docs. Skill selection does not grant
permission for publication, credential changes, or infrastructure operations.

## Set up Jev

Jev is hosted by TypeSafe. Obtain a key from the official
[TypeSafe Console](https://console.typesafe.ai/keys) and store it in your local
secret manager. Installation and offline validation work without service keys.
Never paste a key into chat or commit it.

For a temporary terminal session, enter the key using the masked prompt for
your shell. Keep tracing disabled.

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

The installed [TypeSafe skill](third_party/typesafe-ai/SKILL.md) and its
[development consultation guide](third_party/typesafe-ai/references/development-consultations.md)
describe the API contract. The workflow uses the pinned `jev-1.14.0` model.

## Set up SubQ Snap

Obtain a separate key from the official [SubQ API Console](https://console.subq.ai/)
using its [authentication guide](https://docs.subq.ai/using-the-api/authentication/).
Store it outside the source tree in your local secret manager. Snap uses
`SUBQ_API_KEY`; Jev uses `TYPESAFE_API_KEY`.

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

Run `cw status` to check `jev_credential_present` and `subq_credential_present`.
These are offline booleans for that process; they do not validate keys or prove
availability in another process. Start Codex CLI from the same terminal to inherit
the exported keys:

```sh
codex
```

For Codex Desktop, supply both variables through your local secret manager or its
launch environment. On macOS, after setting both variables in the terminal, a
session-only option is:

```sh
set +x
launchctl setenv TYPESAFE_API_KEY "$TYPESAFE_API_KEY"
launchctl setenv SUBQ_API_KEY "$SUBQ_API_KEY"
```

Fully quit and relaunch Codex, then open a fresh chat and verify key presence
without displaying values. This launch environment applies to subsequently
started GUI processes in the current login session; it is not persistent secret
storage. Existing processes retain their startup environment.

Snap's documented model is [`subq-snap-preview`](https://docs.subq.ai/using-the-api/models/),
a public preview alias. Records retain the requested and returned model IDs.
SubQ [retains request data indefinitely by default](https://docs.subq.ai/using-the-api/data-retention/);
organization-level zero data retention is available for Decisions. Confirm
permitted sharing and retention before sending source evidence to a provider.

## Set up OpenAI Decisions

Obtain an API key from the [OpenAI Platform](https://platform.openai.com/api-keys)
and store it in your local secret manager. The required adviser uses
[`gpt-6-luna` through the Decisions API](https://developers.openai.com/api/docs/guides/decisions).
This API call is separate from dispatching a Luna worker with a reasoning profile.

Enter the key with the masked prompt for your shell:

Bash:

```bash
set +x
IFS= read -r -s -p 'OpenAI API key: ' OPENAI_API_KEY
printf '\n'
export OPENAI_API_KEY
```

zsh:

```zsh
set +x
read -r -s 'OPENAI_API_KEY?OpenAI API key: '
printf '\n'
export OPENAI_API_KEY
```

Supply `OPENAI_API_KEY` alongside `TYPESAFE_API_KEY` and `SUBQ_API_KEY`.
The installed workflow requires all three advisers on every consultation request.
A missing key records unavailable coverage and preserves the other advisers'
results. The helper rejects attempts to exclude required OpenAI advice.

`cw status` reports `openai_credential_present` as an offline boolean for its own
process. For macOS Desktop, set the launch environment from the configured terminal:

```sh
set +x
launchctl setenv OPENAI_API_KEY "$OPENAI_API_KEY"
```

Use a fresh Codex process and chat to inherit that environment and updated skill
instructions. Keep request content within the task's permitted sharing and the
account's [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).

## Consult advisers and let Codex decide

For substantial work, the coordinator consults Jev, Snap and OpenAI Decisions before implementation,
and again after integration and current checks, before completion or authorized
publication, within the task's permitted sharing. Tasks without implementation use the first checkpoint before
substantive drafting or review. Small edits and direct factual answers remain
lightweight.

Participating advisers receive the same permitted evidence, questions, and neutral
Choice options. The [consultation helper](skills/task-orchestration/scripts/consult_decisions.py)
uses one attempt per provider, a 30-second batch budget, and no automatic retries.
It validates each response independently and records unavailable coverage. The
coordinator records sharing restrictions. Codex checks advice against exact sources
and tests, records reasons for rejecting differing advice, and leaves missing
material facts unresolved.
Confidence and voting do not choose the result.

See the [decision diagrams](docs/decision-flow.md) for the task checkpoints,
the three adviser branches, disagreement and missing coverage, and Codex's
resolved/unresolved decisions.

Use the managed interpreter directly. Prepare a request containing `{state,
questions}` as described in the [helper contract](skills/task-orchestration/references/consultation-helper.md).
Keep credentials outside requests, records, and shared evidence. The following
commands use different output paths because the helper refuses overwrites:

```sh
~/.venvs/codex-decisions/bin/python -B ~/.agents/skills/task-orchestration/scripts/consult_decisions.py --request /path/to/request.json --output /path/to/preview.json --dry-run
~/.venvs/codex-decisions/bin/python -B ~/.agents/skills/task-orchestration/scripts/consult_decisions.py --request /path/to/request.json --output /path/to/advice.json
```

The dry run validates and writes a record without network access. A live call can
incur usage with participating providers. It records their independent results and leaves
`final_decision` pending. After checking the evidence, Codex writes a decision and
finalizes a separate record offline:

```sh
~/.venvs/codex-decisions/bin/python -B ~/.agents/skills/task-orchestration/scripts/consult_decisions.py --adjudicate /path/to/advice.json --decision /path/to/codex-decision.json --output /path/to/final.json
```

An unavailable or refusing provider preserves the other results while Codex continues
source verification and reports the coverage limit. A successful API response
proves access for that request; it does not prove judgment accuracy or
implementation correctness.

Every request uses the three required models. OpenAI refusals are recorded per
question, preserving other valid answers and identifying missing
coverage. They do not become choices against a claim.

To verify all three integrations from a fresh Codex chat, use:

```text
Use the installed task-orchestration workflow to check TYPESAFE_API_KEY and
SUBQ_API_KEY and OPENAI_API_KEY presence without showing values. Make one Choice
request using only synthetic public text, jev-1.14.0,
subq-snap-preview and OpenAI Decisions gpt-6-luna, with the
30-second batch budget and no retries. Validate requested and returned models
and report each provider's result or safe failure category. Compare the results
with the supplied evidence and record Codex's final decision. Never print keys
or authorization headers.
```

See [workflow and integrations](docs/workflow.md#typesafe-jev-and-subq-snap) for
policy details and source links.

## Maintain the installation

Installation and update require a clean committed checkout. Maintenance commands
return JSON on stdout and errors on stderr. Choose the command for your task:

| Command | Purpose |
| --- | --- |
| `cw status` | Inspect active/previous revisions, manager identity, registrations, owned settings, model profiles, and local credential presence |
| `cw validate` | Validate the source skill suite without activating it |
| `cw update --dry-run` | Preview local validation, ancestry, ownership, and registration changes without fetching or activating |
| `cw update` | Fetch and validate exact `origin/main`, prepare its verified binary, fast-forward the checkout, and activate the snapshot |
| `cw rollback --dry-run` | Preview restoration of the previous validated snapshot |
| `cw rollback` | Restore the previous snapshot and its owned settings using activation history |
| `cw recover --dry-run` | Inspect recovery of an interrupted managed transaction |
| `cw recover` | Reverse unfinished owned changes using the recovery journal |
| `cw uninstall --dry-run` | Preview removal of owned registrations and settings |
| `cw uninstall` | Remove managed links/blocks and restore original owned settings and adopted registrations |

The update preview is offline and cannot establish the current remote candidate.
Failed update preparation leaves the active installation unchanged. Rollback
restores skills and owned settings without rewinding Git or changing GitHub.
Recovery preserves unrelated edits and refuses modified owned content. Uninstall
preserves the checkout, caches, credentials, connectors, and consultation environment.
Use [operations](docs/operations.md) for detailed command and recovery contracts.

Start a fresh Codex chat after install, update, or rollback to load the active
instructions. Check `cw status` and `cw validate`, confirm the configured profiles
against the model table above, and inspect actual chat runtime metadata separately.
Authenticate GitHub, Jira, and Confluence on each device and verify the intended
identity with a permitted read.

See [development](docs/development.md) for native checks and releases.
