---
name: task-orchestration
description: Coordinate substantial cross-project tasks with Jev consultation, explicit worker models, revisable assumptions, and Jira, Confluence, or GitHub evidence and requested updates. Use for independent workstreams, cross-component changes, or consequential uncertainty; small edits and direct factual answers stay lightweight.
---

# Task orchestration

The main worker owns the outcome, dispatch, consultation, integration, and final
verification. Use this workflow alongside the relevant specialist skills. It adds
coordination; it does not replace their evidence requirements or grant authority
for external actions.

## Start with the policy and current evidence

Read [model-policy.yaml](model-policy.yaml) for the current task. It is the
canonical configurable policy, interpreted by the coordinator rather than native
Codex configuration. Preserve explicit user choices and higher-priority runtime
instructions, including the current main `gpt-6.1-sol` at `ultra`. Authorized YAML
edits guide later dispatch; the saved main configuration applies to new sessions.
This skill cannot change the model of an active session. Disclose a material
mismatch. A compatible coordinator has the role's required model and effort, established by
session/runtime metadata rather than this file. Without an explicit user override,
substantive coordination and final verification require a compatible main worker.
If the active main model cannot meet that requirement, preserve the task brief and
evidence and report the exact model/effort needed in a fresh session; a compatible
subworker alone does not resolve the main mismatch. Bounded evidence gathering may
continue. Honor a later explicit user model choice; do not claim an automatic
session switch occurred.

For a substantial task, establish the requested outcome, acceptance evidence,
scope, carried authorization, repository instructions, relevant revisions, and
available tools/models. Choose the applicable checklist in
[use cases](references/use-cases.md). For connected sources or documentation,
read [connected sources](references/connected-sources.md). Fetch relevant linked
evidence before judging it. Do not require unrelated services for a local task.

Keep requirements and user decisions separate from observations and provisional
assumptions. In the task's agreed artifact or chat record, retain a compact ledger:
`claim | basis/source revision | status | impact | next check`. Use `unverified`,
`verified`, `contradicted`, or `obsolete`; a preset never verifies its own claims.
Retain worker assignments, consultation disposition, completed checks, and blockers
with the ledger. Saving outside an agreed task location needs its own scope.

## Consult Jev centrally

Resolve `typesafe-ai` from the available skill catalog and read its development
consultation guide, current selected-model limitations, and applicable primitive
documentation. If unavailable, record the limitation and continue the work.

Attempt a useful bounded consultation during substantial task setup after evidence
gathering. Have workers contribute evidence and questions to the coordinator;
avoid duplicate calls across skills. If existing applicable consultation already
answers the question, reuse it. If no meaningful judgment remains, record that
reason rather than manufacture a question about an explicit rule. For example,
whether an excerpt supports a proposed compatibility claim can merit consultation;
whether to honor the user's explicit Sol setting or publication boundary does not.

Use [question patterns](references/jev-questions.json) for worker eligibility and
claim support. Construct the request from the actual task's permitted evidence,
constraints, and viable alternatives; Jev has no implicit repository/history
access. Apply known scope, model, and authorization rules before offering options.
Jev must not generate code, findings, explanations, or new assumptions. It cannot
override the user's Sol effort requirement or authorize publication.

Pin the policy's model. Batch independent questions sharing evidence, using one
attempt and a 30-second deadline with automatic retries disabled. Validate response
IDs, types, options, finite probabilities, distributions, and resolved model.
Treat invalid, unavailable, conflicting, or insufficient answers as investigation
leads; continue conservatively and independently verify material conclusions.
Do not convert confidence to permission or invent an acceptance threshold.

The skill's [consultation helper](scripts/consult_jev.py) validates and
sends a prepared Choice-only request using the maintained policy. It uses Python
and PyYAML independently of the Go installation manager. Its record excludes the authorization header,
raw errors, and unknown response fields, but stores the prepared request verbatim.
Sanitize request inputs before sharing or recording them; the helper cannot remove
credentials or sensitive evidence embedded in those inputs. It writes only to the
supplied task output path. `--dry-run` validates without network access. Other
primitives remain available through the TypeSafe guide; this helper does not
implement them. Follow task sharing restrictions before using it.

## Select effort, then dispatch and integrate

Resolve each role through YAML `roles` and `profiles`, including its declared scope.
The defaults are Sol 6.1 `ultra` for `substantive` work, Luna `high` for
`bounded_evidence`, and `luna_execution` at Luna `max` for `bounded_execution`.
Substantive coding, testing, planning, architecture, review, diagnosis, documentation,
issue specifications, PR content, and final verification use the role's configured
non-Luna substantive profile; the current default is Sol 6.1 `ultra`. Bounded evidence
covers read-only extraction or summarization.
Routine PR authoring, commits, and PR submission require the coordinator to fix
the files, revision, message or draft, and authorization boundary. A routine draft
only summarizes already verified facts; new behavior, risk, compatibility,
qualification, or acceptance claims need substantive ownership. Promote ambiguous
scope, content, conflicts, or verification to a substantive profile. The role's
action bounds and authorization still apply regardless of the selected model.

Use `effort_guidance` to consider task shape: [model guidance](https://learn.chatgpt.com/docs/models)
associates `max` with a difficult single task and `ultra` with meaningful parallel
parts. The current model catalog
describes both as maximum reasoning, with automatic delegation added for `ultra`.
This does not establish extra depth, cost, or savings without comparative evaluations.
Preserve the current Sol `ultra` default and never escalate automatically. Sol `max`
requires an explicit user request allowed by the selected profile's
`user_requested_efforts`; Sol profiles must not default to `max`. Other models may
use an authorized configured `max` default listed in
`effort_policy.configured_max_profiles`; the current such profile is Luna execution.
`effort_policy.default_substantive` must match the coordinator profile's default
effort; it does not override role-specific efforts. Edit YAML for supported profiles,
efforts, and routes; retain the fixed
explicit-request, consultation, and publication safeguards.

The native `cw validate` command checks suite and policy consistency and known
model capabilities. The [Python policy validator](scripts/validate_policy.py)
remains an optional development helper. When
useful, call its `resolve_worker(policy, role, requested_effort=None)` helper for
the selected model and reasoning effort. Read the role's profile and scope in YAML
and retain the boundary rules above.
It neither verifies runtime availability nor dispatches workers automatically.
Check the runtime's actual model and effort capabilities before spawning. Supply
both model and reasoning effort explicitly when the tool supports overrides. In this harness, use
`fork_turns="none"` or a bounded positive history count for overrides; a full-history
fork inherits the parent and rejects overrides. Pass a self-contained task brief.
Respect fixed specialist models and restrict those specialists to evidence gathering.
If explicit overrides are unsupported, use a compatible inherited configuration or
report the limitation; never claim a requested setting was applied without evidence.

Use the policy's configured fallback for unavailable bounded workers. If the
selected substantive model is unavailable, use an already compatible coordinator
or report the blocker; do not silently lower effort or change family.
For a small or dependent task, keep work with the main worker. For useful independent
workstreams, assign a bounded question or file ownership, constraints, and an output
contract. Tell editing workers they share the codebase and must preserve others'
changes. Coordinate overlapping edits and respect the runtime concurrency limit.

Workers return exact sources, observations, changes, checks, and remaining uncertainty.
The coordinator reconciles those results and verifies conclusions against evidence.
Agent agreement and Jev confidence do not prove behavior. Preserve required
independent design challenges and repository-specific execution environments.

## Revisit affected assumptions and finish

When requirements, source revisions, Jira acceptance text, Confluence versions,
PR heads/checks, environment, worker findings, or verification results materially
change, identify the affected ledger entries. Preserve user decisions, scope, and
authorization. Mark stale assumptions/conclusions obsolete or contradicted, collect
new evidence, revise dependent work, and invalidate only affected consultations.
A new turn alone is not invalidation and does not justify repeating matching checks.

For source discrepancies and requested external actions, use the connected-source
reference. Proceed within existing authorization without asking again; prepare a
concrete draft before asking for a missing publication decision. Verify remote writes
and reconcile uncertain outcomes before retrying.

Finish with the completed outcome, evidence at its actual scope, and material limits.
Mention Jev only when its advice affected a decision or a triggered consultation was
unavailable. A structural audit, static scenario, live Jev answer, CLI-discovery probe,
and deployed behavior are distinct forms of evidence.
