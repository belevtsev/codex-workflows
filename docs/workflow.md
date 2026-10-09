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

Merge the desired main defaults into the machine's existing Codex `config.toml`:

```toml
model = "gpt-6.1-sol"
model_reasoning_effort = "ultra"
```

Keep the rest of that machine's configuration. Paths, trusted projects, plugins,
MCP settings, and authentication are local decisions. The bootstrap manages
only its global instruction block and skill registrations; it never replaces
the whole `AGENTS.md` or `config.toml`.

## TypeSafe and Jev

`typesafe-ai` is included as a self-contained vendored skill. If a task calls
for a Jev consultation, make `TYPESAFE_API_KEY` available through the local
environment or a local secret manager, then follow the installed skill and
current TypeSafe documentation. Never commit a key value, put it in a prompt,
or include it in logs or evidence shared with workers.

The task coordinator owns consultations, their scope, and reuse. Missing or
inconclusive consultation is reported while work continues using source
evidence and conservative routing. Installation, validation, CI, and the fresh
chat verification prompt make no consultation requests.

## Connected services

Authenticate Jira, Confluence, and GitHub independently on each machine using
the intended account for each service. Skill installation does not establish connector
access or copy authentication. Verify the identity and a permitted read for
each service separately before using it for a task. Repository cloning verifies
Git access to this repository, not the availability of those connectors.

Use a task's explicit authorization before writing to any service. After an
authorized write, read it back; if the result is uncertain, reconcile remotely
before retrying. Keep company content, project history, credentials, private
audits, and evaluation inputs outside this reusable source repository.
