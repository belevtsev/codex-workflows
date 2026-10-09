# Workflow and local integrations

The global conventions keep user scope, authorization, source evidence, and
verification consistent. Use the relevant skill when its workflow helps the
request. A plan or review remains a plan or review until implementation is
authorized. Publishing, messaging, committing, pushing, and infrastructure
changes need authorization for that action.

For substantial work, the coordinator reads
[`model-policy.yaml`](../skills/task-orchestration/model-policy.yaml). This is
an editable routing policy interpreted by the skill; Codex does not load the
YAML as native settings or change a running chat's model automatically.

| Work | Default model | Effort |
| --- | --- | --- |
| Coordination and substantive implementation, review, planning, or diagnosis | `gpt-6.1-sol` | `ultra` |
| Bounded routine execution | `gpt-6-luna` | `max` |
| Bounded read-only lookup or summarization | `gpt-6-luna` | `high` |

The policy preserves fixed specialist settings and describes availability
fallbacks. A request to use Sol `max` must come explicitly from the user. A
worker's evidence does not authorize an external action, and consultation
results do not prove correctness or grant permission.

## Local configuration

`./install.sh` enrolls two root settings in the machine's existing Codex
`config.toml`, using the validated coordinator policy:

```toml
model = "gpt-6.1-sol"
model_reasoning_effort = "ultra"
```

Paths, trusted projects, plugins, MCP settings, permissions, and authentication
remain local decisions. The Go manager preserves unrelated configuration, comments,
and permissions. It owns the two root model keys, global instruction block, thirteen
skill registrations, and enrolled direct command/PATH registration. It records
original values once and restores them on uninstall.

cw is a direct executable link on PATH. It uses recorded installation roots from
any directory; no shell command wrapper is involved. Install selects Bash/zsh for
optional PATH enrollment; --shell none leaves enrollment to the user. Help/version
are offline. Updates and rollbacks apply the selected skill snapshot's model
defaults, while a running Codex chat keeps its existing session settings.

A later edit to an owned value is a conflict. Malformed TOML and symlinked
configuration are refused. Legacy installation records and original settings are
preserved during migration; status/recovery/removal rely on installed snapshots.

## TypeSafe and Jev

`skills-manifest.json` registers `typesafe-ai` from
[`third_party/typesafe-ai`](../third_party/typesafe-ai/SKILL.md). Resolve the installed
skill through Codex's skill catalog and read its
[development-consultation guide](../third_party/typesafe-ai/references/development-consultations.md)
relative to that skill's root. Jev is TypeSafe's hosted System One model; no
separate `jev` executable or SDK is required by the bundled consultation helper.

Use the official [quick start](https://docs.typesafe.ai/introduction/quickstart)
and [Console API keys page](https://console.typesafe.ai/keys) to obtain a key.
The [README setup steps](../README.md#set-up-jev) show masked terminal input and
the distinction between CLI environment inheritance and desktop launch
environments. Supply `TYPESAFE_API_KEY` through the process environment or a
local secret manager; an export in another terminal does not update an already
running Codex process. Restart from the configured environment and open a fresh
chat. Never commit a key value, put it in a prompt, or include it in logs or
evidence shared with workers.

`cw status` reports only whether its own process has a nonempty Jev credential,
never its value. A credential is optional for installation, validation, and
local status. Status is offline and does not establish key validity, service
availability, or access from a different Codex process.

The task coordinator owns consultations, their scope, and reuse. The installed
policy pins `jev-1.13.0`, one attempt per evidence batch, a 30-second deadline,
and disabled automatic retries. Read the current
[API contract](https://docs.typesafe.ai/api),
[model reference](https://docs.typesafe.ai/models), and
[Jev 1.13 limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13) before
consulting. A newer alias or upstream example does not change the installed pin.
Policy upgrades require their own authorized change.

An optional live availability check requires an explicit request, uses only
synthetic public text, and validates the pinned model, expected question IDs,
answer types, allowed options, finite probabilities, and distributions. Follow
the installed helper and guide rather than adding retries or sending private
source material for a setup check. A successful response is availability
evidence for that request, not evidence of calibrated accuracy or implementation
correctness.

Missing or inconclusive consultation is reported while work continues using
source evidence and conservative routing. Installation, validation, CI, status,
and the installation verification prompt make no consultation requests. The
separate optional live-check prompt in the README requests one explicitly.

## Connected services

Authenticate Jira, Confluence, and GitHub independently in Codex on each device
using the intended account for each service. Skill installation does not
establish connector access or copy authentication. Verify the identity and a
permitted read for each service separately before using it for a task.
The public repository can be cloned without GitHub authentication. Cloning does
not verify a connector's identity, private-repository access, or write access.

Use a task's explicit authorization before writing to any service. After an
authorized write, read it back; if the result is uncertain, reconcile remotely
before retrying. Keep company content, project history, credentials, private
audits, and evaluation inputs outside this reusable source repository.
