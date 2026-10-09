# Skill discovery and bounded evaluation

The suite has 26 registrations and 71 entrypoints. Discovery metadata
is concise; entrypoints retain scope and essential safeguards, with detailed
references loaded only for the current question. Model/effort defaults are
validated policy, not claims of improved quality, token savings, or elapsed time.
Measure those outcomes on equivalent work.

## Credential-free fixture gates

The historical fifteen scenarios under
`internal/devcheck/testdata/backend-skills` remain unchanged. They exercise supplied
skills and synthetic decision evidence. Fresh discovery is a separate ten-case
corpus under `internal/devcheck/testdata/skill-routing`: raw case inputs are in
`inputs/`; evaluator-only rubrics and canned observations are outside that tree.

| Raw case ID | Discovery condition |
| --- | --- |
| `backend-explicit` | Explicit backend security skill invocation |
| `backend-implicit` | Authorization review without a skill name |
| `backend-adjacent` | Ordinary error mapping review |
| `protobuf-explicit` | Explicit protobuf skill invocation |
| `protobuf-implicit` | Schema and mixed-consumer review without a skill name |
| `protobuf-adjacent` | RPC timeout review with unchanged schemas |
| `pki-explicit` | Explicit Go PKI skill invocation |
| `pki-implicit` | Trust reload evidence assessment without a skill name |
| `pki-adjacent` | HTTPS response status review with unchanged transport |
| `go-fuzz-implicit` | Fuzz design with a weak oracle and an invalid input exclusion |

Existing `go test`/`cwdev check` gates validate raw/oracle separation, local paths,
required references, discovery modes, and deterministic canned scoring. Canned
records include accepted decisions and rejection examples for missing reads,
misrouting, invented execution, effects, weak oracles, missing depth, and oracle
access. This checks the fixture/scorer contract; it neither calls a hosted model
nor demonstrates that discovery or reasoning passed. CI receives no service
credentials. There is no separate `cwdev eval` command.

The personal expansion adds three implicit cases under
`internal/devcheck/testdata/personal-skill-routing/inputs`: production planning,
Dockerfile review, and preparation of an explorable diagram. Their evaluator-only
oracles live outside the input tree. CI validates source/reference availability
and input separation without calling a model. Apply the same fresh invocation
procedure below, record actual initial catalog availability and file reads, and
report unavailable model/authentication or contamination as incomplete evidence.
The diagram case prepares a design only; rendering is verified separately by
Archify's portable and real-browser gates.

Adjacent negatives exclude the inapplicable target skill while requiring correct
source claims and action limits. They permit another relevant Go skill or direct
reasoning without loading a specialist; `code-review` is not mandatory.

## One fresh manual invocation per raw case

Use this procedure only for an authorized, bounded hosted-model evaluation. Keep
metrics, traces, errors, and run records in the agreed task artifact outside source.
The evaluated tasks are synthetic and read-only: no tests, scanners, builds,
linters, helpers, installs, Jev calls, services, credentials operations, or external
writes. The harness may invoke the selected model; the task may not launch further
network work. Set a fixed timeout and one attempt per case. Do not automatically
retry failures or continue a contaminated session.

1. Pin and validate the exact committed suite SHA and installed snapshot identity.
   Record the CLI version and applicable help. Use an isolated disposable task home
   for skill discovery; preserve the existing `CODEX_HOME` for authentication and
   use `--ignore-user-config`. Never copy, display, or log auth files/tokens. Do not
   change the user's real skill registrations or installation.
2. Build a sanitized catalog containing only the pinned snapshot's `skills/` and
   `third_party/` resources. Link the 26 registrations in the disposable
   task home to that catalog. Do not expose the complete snapshot or checkout:
   those also contain evaluator files. Record catalog identity and registrations.
   This copy is an evaluation fixture, not a suite upgrade or live activation.
3. Copy exactly one raw case's prompt and artifacts into an opaque isolated input
   directory. Supply only that directory and the sanitized discoverable catalog.
   Keep the oracle and canned records out of both. Do not add desired selections,
   suspected findings, prior conclusions, skill paths, or rubric text to the prompt.
   Preserve implicit and adjacent prompts without skill names. No other case or
   conversation history belongs in this invocation.
4. Launch one fresh `codex exec` process for this case. The checked CLI supports the
   following shape; verify flags for the recorded version before a later run:

   ```sh
   codex exec --ignore-user-config --skip-git-repo-check --ephemeral \
     --model gpt-6.1-sol -c 'model_reasoning_effort="max"' \
     -c 'approval_policy="never"' --sandbox read-only \
     --cd "$case_input_dir" --json - \
     < "$case_input_dir/prompt.md" > "$case_record_dir/events.jsonl"
   ```

   Configure the isolated discovery home in the launcher's process environment;
   keep existing authentication available without relocating its files. The model
   and `max` effort are explicit for comparison, and `ultra` is not selected by
   escalation. Do not resume sessions, enable hooks/plugins that perform effects,
   or provide a hidden answer through an output schema. Enforce the timeout in the
   launcher and record a timeout as an incomplete attempt.
5. Retain actual tool/file-read traces, the final answer, exit/error status, elapsed
   time, and reported token usage. Normalize actual skill paths to suite-relative
   locations. An assertion that a skill was used is insufficient: count only
   evidenced reads of its `SKILL.md` and relevant references. If the CLI lacks a
   needed trace or usage field, record it as unavailable rather than infer it.
6. After the process stops, the independent evaluator reads the withheld rubric.
   Judge semantic claims from the answer and raw evidence, then compare actual
   reads and effects. The fuzz case accepts either relevant testing entrypoint but
   requires the deeper first-party fuzzing reference and decisions about independent
   oracles, the full byte domain, seeds, isolation/budgets, exact minimized
   regression, and no-tests/corpus/cache limits. Keep semantic judgment separate
   from the deterministic scorer; do not grade by keywords alone.

Any oracle/canned access, leaked intended answer, cross-case history, or prohibited
side effect invalidates the evaluation. Read-only sandboxing controls writes but
does not by itself prove that withheld files were unread; inspect the trace. Keep
invalid/failed attempts in the record without converting them into passes.

For each attempt record: case ID; source SHA and snapshot/catalog identity; raw
input and prompt SHA256; CLI version; configured and observed model/effort;
actual skill/reference reads; semantic claim judgments with evidence; effects;
exit status and errors; timeout/budget; elapsed time; input/output/total tokens
when supplied; result and validity limits. Record whether user configuration was
ignored and authentication was reused, without recording credential contents.

A fresh discovery pass supports only these synthetic inputs and this exact
catalog/runtime. It is distinct from structural CI, source review, executed
application tests, integration, deployment, and production qualification. Compare
quality, context/tokens, and elapsed time only across matched inputs and conditions;
report missing measurements and failures alongside successful cases.
