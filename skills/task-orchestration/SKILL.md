---
name: task-orchestration
description: Coordinate substantial cross-component work with bounded workers, grounded assumptions, central Jev advice, and revision-aware verification.
---

# Task orchestration

The coordinator owns the outcome, consultation, dispatch, integration, and final
verification. Use this skill for independent workstreams or consequential
uncertainty; keep small or dependent work with the main worker. Specialist evidence
requirements, repository instructions, and the user's authorization still govern.

## Establish policy, scope, and evidence

Read [model-policy.yaml](model-policy.yaml) and the relevant section of
[use cases](references/use-cases.md). Read [connected sources](references/connected-sources.md)
only when Jira, Confluence, GitHub, or documentation supplies evidence or requested
writes. Fetch linked evidence needed for the decision; unrelated services are not
prerequisites for local work.

The YAML is configurable dispatch policy, not native Codex configuration. Defaults
are Sol 6.1 `max` for substantive work, Luna `high` for bounded evidence, and Luna
`xhigh` for bounded routine execution. Resolve each role's profile and scope from
the current policy, preserving explicit user choices. Sol `max` may be configured
or explicitly requested; Sol `ultra` needs an explicit user request allowed by the
profile. Never escalate automatically. A saved policy cannot switch an active
session. Verify model and effort from runtime metadata; disclose a mismatch. Without
an explicit user override, substantive coordination and final verification require
a compatible main worker. If unavailable, retain the brief and evidence, name the
required fresh-session configuration, and continue only bounded evidence gathering.
A compatible subworker does not repair the main worker's mismatch.

Establish the outcome, acceptance evidence, scope, carried authorization, revisions,
and available tools. Keep requirements and user decisions separate from observations
and assumptions. In the agreed artifact or chat record retain a compact ledger:
`claim | basis/source revision | status | impact | next check`, using `unverified`,
`verified`, `contradicted`, or `obsolete`. Retain assignments, completed checks,
consultation disposition, and blockers; a preset never verifies its own claims.

## Consult Jev centrally

Resolve installed `typesafe-ai`; read its entrypoint, development consultation
guide, selected-model limitations, and relevant primitive documentation. After
gathering evidence, attempt a useful bounded setup consultation; reuse applicable
advice. Record unavailable consultation or why no meaningful judgment remains.
Workers return evidence and questions to the coordinator rather than duplicate
calls. Explicit scope, model, and publication rules need no model judgment.

Use [question patterns](references/jev-questions.json) with exact evidence,
constraints, and viable alternatives. Jev has no implicit repository or history
access. It supplies typed advice, not code, findings, explanations, assumptions,
proof, or permission. Independently verify material conclusions.

Pin the policy model, batch independent questions sharing evidence, and use one
attempt with a 30-second deadline and no automatic retries. Validate response IDs,
types, allowed options, finite probabilities, distributions, and resolved model.
Invalid, unavailable, conflicting, or insufficient advice leaves an investigation
lead; do not invent a confidence threshold or convert confidence into authorization.
For the optional helper's request, output, and privacy contract, read
[consultation helper](references/consultation-helper.md) only before using it.

## Dispatch bounded briefs and integrate

Substantive coding, testing, planning, review, diagnosis, documentation, new
acceptance claims, and final verification use the configured non-Luna substantive
profile. Routine execution requires fixed files, revision, content, and action
authorization from the coordinator. New claims, ambiguous scope, conflicts, or
uncertain verification return to substantive ownership. Model selection never
relaxes a role's action bounds.

Check actual runtime capabilities before spawning. When overrides are supported,
supply model and effort explicitly and use `fork_turns="none"`: a full-history
fork inherits the parent and rejects overrides. Respect fixed specialist models
and use them only within their evidence role. If overrides are unsupported, use a
compatible inherited configuration or report the limit. Follow the policy's
bounded-worker fallback; never silently lower a substantive effort or model family.
Native `cw validate` and the optional Python policy validator check consistency,
not runtime availability or automatic dispatch.
The validator's `resolve_worker(policy, role, requested_effort=None)` returns the
configured model and effort, applying permitted explicit overrides; inspect the
role's scope before using that result for dispatch.

Split useful independent questions or owned components. Give each worker a
self-contained brief with exact source revision and inputs, question or owned
files, relevant decisions, constraints, permitted actions, output evidence, and
stopping condition. Include only context needed for that assignment; avoid full
history dumps and duplicate investigation. Editing workers share the codebase and
must preserve others' changes. Coordinate shared interfaces and respect concurrency
limits; dependent integration stays with the coordinator.

Workers return exact sources, observations, changes, checks, and uncertainty.
Reconcile overlaps and independently verify conclusions; agreement and confidence
do not establish behavior. Preserve required design challenges and execution
environments.

## Refresh affected claims and complete

When scope, revisions, acceptance text, environment, findings, or checks materially
change, update only dependent ledger entries, assignments, and consultations. Keep
user decisions and authorization. A new turn alone does not invalidate evidence.

Prepare requested external drafts from verified evidence, carry existing
authorization, and verify writes through readback. Reconcile uncertain outcomes
before retrying. Finish with the completed result and evidence at its actual scope:
structural fixtures, fresh discovery, Jev advice, tests, CI, and deployment remain
distinct. Mention Jev when it affected a decision or a triggered consultation was
unavailable.
