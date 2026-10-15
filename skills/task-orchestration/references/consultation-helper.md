# Decision consultation helpers

Read this before using [consult_decisions.py](../scripts/consult_decisions.py).
It validates a prepared Choice-only request, sends the same shared input to Jev,
SubQ Snap, and optional OpenAI Decisions concurrently, and records each result independently. It does not dispatch
workers or decide which judgment is correct. Python and PyYAML are skill dependencies
separate from the native Go installation manager. Missing dependencies do not justify
automatic installation.

Select an interpreter that can import `yaml` before calling the helper. If the
user has provisioned `~/.venvs/codex-decisions/bin/python`, verify it with
`~/.venvs/codex-decisions/bin/python -B -c 'import yaml'` and use that full path.
Otherwise check `python3 -B -c 'import yaml'`. A virtual environment activated in
another terminal does not change Codex's interpreter. If neither works, report
the missing dependency and the isolated setup recipe in the repository README.
Keep dependencies outside immutable skill snapshots and pass `-B` on every call.

## Required task checkpoints

For every substantial task using task-orchestration, the coordinator runs this paired
helper before implementation (or substantive drafting/review) and again during final
review, following the [entrypoint](../SKILL.md). Prepare distinct requests and new
output paths for the two checkpoints. The first request assesses the proposed approach
and verification plan; the final request assesses the completed work and current checks
before completion or authorized publication. Include the checkpoint in request state
and retain its provider coverage and Codex disposition in the task record.

Reuse is limited to the same checkpoint with applicable evidence, decisions, question
meaning, and models. A pre-implementation record cannot satisfy final review. If calls
are unavailable or sharing is restricted, record that checkpoint's limitation and
follow the source-evidence fallback; do not bypass restrictions or add retries.
The helper validates individual requests and records; the coordinator owns checkpoint
timing. Installation, update, validation, and CI do not call hosted models.

## Prepare and run a shared request

The input is JSON with exactly `state` and `questions`. Include faithful text excerpts,
the active source revision and locations, relevant constraints, and distinguishable
assumptions in `state`. Each question must be a Choice with named options. Include
`insufficient_evidence` when a material missing fact could prevent an answer. Participating
providers receive the same state, instructions, and criteria; the helper supplies
their policy-selected model IDs. This common workflow has no images or other
primitives and must fit the participating providers' documented limits.

The coordinator verifies excerpts against their exact sources before sharing them.
The helper can validate structure and compare returned choices; it cannot establish
source truth or discover omitted evidence. Ask for a bounded judgment about the
prepared evidence rather than code, findings, or explanations.

From the editable checkout with the dependencies already available:

```sh
python3 -B skills/task-orchestration/scripts/consult_decisions.py --request /path/to/request.json --output /path/to/preview.json --dry-run
python3 -B skills/task-orchestration/scripts/consult_decisions.py --request /path/to/request.json --output /path/to/new-record.json
```

After managed installation, the helper is available through the registered skill
path. With the provisioned runtime, call it directly without shell activation:

```sh
~/.venvs/codex-decisions/bin/python -B ~/.agents/skills/task-orchestration/scripts/consult_decisions.py --request /path/to/request.json --output /path/to/new-record.json
```

`--policy /path/to/model-policy.yaml` selects a validated policy instead of the
helper's adjacent default. `--dry-run` validates the policy and input and writes a
task record without network access. A real call uses separate `TYPESAFE_API_KEY` and
`SUBQ_API_KEY` environment variables, plus `OPENAI_API_KEY` for enabled OpenAI
Decisions, and one attempt per provider. A 30-second batch
budget covers process startup, requests, and result transport; each worker is bounded
by the remaining budget, with bounded cleanup afterward. It neither retries nor
substitutes another model.
Missing credentials, malformed responses, timeouts, and safe service failure
categories are recorded independently, so one provider's failure preserves the
other's result. Responses are validated for IDs, types, options, finite values,
distributions, usage, and returned model.

The maintained model IDs are `jev-1.14.0` and `subq-snap-preview`. Snap's documented
public preview ID is not an immutable version pin; retain the requested and returned
model and consult the current contract when reusing a result. Reuse only within the
same checkpoint while the source revision, evidence, decisions, question meaning,
and models remain applicable.

## Optional OpenAI Decisions

The policy may add `consultation.optional_providers` with exactly
`openai_decisions: gpt-6-luna`, alongside the required Jev/Snap provider map.
An exported `OPENAI_API_KEY` opts into that adviser. With no key, it is recorded
as `disabled` and makes no network request; normal required-pair availability is
preserved. `--without-openai` explicitly excludes it even when a key is present.
`--with-openai` explicitly requests it; a missing key then records unavailable
coverage. These mutually exclusive switches apply only to `--request` and require
the policy to declare the optional provider. Adjudication follows the saved record
and uses no key or participation switch.

The fixed endpoint is `POST https://api.openai.com/v1/decisions`. The adapter maps
canonical shared state to deterministic JSON text in `input`, question IDs to
`name`, and each criterion key/description to a `choices` value/description. It
normalizes named answer arrays and probability arrays into the common record.
The request retains the shared evidence fingerprint; endpoint-specific encoding
does not let an adviser receive different facts or question meanings.

Read the current [guide](https://developers.openai.com/api/docs/guides/decisions),
[create contract](https://developers.openai.com/api/reference/resources/decisions/methods/create),
and applicable [data controls](https://developers.openai.com/api/docs/guides/your-data).
The common integration remains text and Choice only. OpenAI currently accepts at
most 200 questions; an unsupported OpenAI request is recorded without breaking
the required pair. OpenAI's predicate, score, image and other input features do
not expand this shared contract. No extra SDK is required.

OpenAI can refuse an individual question while returning valid answers to others.
The record keeps those choices and marks the refused question as missing coverage.
It does not turn a refusal into a negative choice. A mixed response is `partial`;
an all-refused response is `refusal`. Malformed responses, missing credentials,
timeouts and safe service failures are recorded separately. The 30-second batch
budget and one-attempt policy cover all enabled providers concurrently.

Pair-only policies retain version-one records. Policies declaring the optional
adviser use version-two records with explicit disabled/unavailable/refusal coverage
and a per-question `missing` map. Offline adjudication accepts both versions and
validates each version's provider and field contract; existing records are not
rewritten. A disabled adviser does not reduce required-pair availability. An enabled
adviser that cannot provide a choice leaves partial or unavailable coverage for
that question. These coverage states do not decide the claim.

## Compare and retain evidence

The record contains the shared prepared input, per-provider status and validated
answers, and per-question `agreement`, `disagreement`, `partial`, or `unavailable`.
These categories describe provider coverage and choice equality. They do not establish
truth. `final_decision` starts as `pending`; no confidence comparison, vote, or
automatic winner completes it.

Codex investigates any disputed evidence and independently verifies the conclusion
against exact sources and relevant tests or observations, including when the providers
agree. In the agreed task record retain the final conclusion, evidence references and
source revision, verification and its limits, rejected judgment and reason, unresolved
facts, and partial or unavailable provider coverage. If a material fact remains missing
or conflicting, retain an unresolved decision. An unavailable consultation alone does
not prevent useful source work.

## Finalize Codex's decision without network access

Once Codex has done that investigation, write a decision JSON and validate it against
the original consultation record:

```sh
python3 -B skills/task-orchestration/scripts/consult_decisions.py --adjudicate /path/to/consultation.json --decision /path/to/codex-decision.json --output /path/to/final.json
```

`--adjudicate` and `--request` are mutually exclusive. Adjudication makes no provider
requests and uses no credentials. It writes a new record, preserving the consultation
input and provider results. The decision must contain every question ID exactly once:

```json
{
  "questions": {
    "claim_support": {
      "status": "resolved",
      "choice": "supported",
      "reason": "The source establishes the claim for the stated conditions.",
      "evidence": ["src/example.go:42 at <source revision>"],
      "verification": ["Source inspection at <source revision>; focused test <result reference>"],
      "rejected_judgments": {
        "subq_snap": "The contrasting choice overlooked the stated condition at src/example.go:42."
      }
    }
  }
}
```

This example is a shape to adapt, not evidence for a real decision. Each item has
`status`, `choice`, `reason`, `evidence`, `verification`, and `rejected_judgments`.
For `resolved`, the choice must be an allowed option; evidence and verification must
be nonempty source/revision and check references. Give a rejection reason for every
successful provider choosing a different option, using the provider IDs `jev`, `subq_snap`, and enabled `openai_decisions`.
A valid differing choice in a partially refused response still needs a rejection
reason for that question; missing or refused judgments do not. Agreement still needs independent evidence and verification.

For `unresolved`, use `choice: null`, an empty rejection mapping, and a nonblank reason
describing the material unknown; evidence and verification references may be empty. The final
record is resolved only when every question is resolved. This structural validation
checks that Codex recorded its decision obligations; it cannot prove the cited
evidence or reasoning correct and never chooses a winning confidence score.

## Sharing and recording

The helper writes only to the supplied new output path. Its record excludes credentials,
authorization headers, raw errors, and unknown response fields, but retains the prepared
request verbatim. Sanitize inputs before sharing or recording them; the helper cannot
remove credentials or sensitive material embedded in evidence. Keep sensitive records
in the task's permitted storage. Saving outside the agreed task location requires its
own scope.

SubQ [retains data indefinitely by default](https://docs.subq.ai/using-the-api/data-retention/).
Organization-level zero data retention is available and applies to Decisions. Its
documented per-request `store: false` setting covers Chat Completions and Responses;
the helper does not claim that setting for Decisions. Confirm that sharing and the
organization's retention policy fit the authorized task before sending source evidence.
Credentials and authentication are documented in the
[SubQ authentication guide](https://docs.subq.ai/using-the-api/authentication/).

## Legacy Jev-only helper

[consult_jev.py](../scripts/consult_jev.py) remains supported unchanged for existing
Jev-only integrations. It accepts its existing request contract and uses the legacy
`consultation.model` policy field. The paired helper uses `consultation.providers`
and `consultation.comparison: codex_evidence_and_verification` while preserving policy
version 2. Follow the installed TypeSafe guide for other primitives. A Jev-only result
does not provide dual-provider coverage.
