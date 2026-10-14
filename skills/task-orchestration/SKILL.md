---
name: task-orchestration
description: Coordinate substantial cross-component work with bounded workers, grounded assumptions, paired Jev and SubQ Snap advice, and revision-aware verification.
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

## Consult Jev and SubQ Snap centrally

Resolve installed `typesafe-ai`; read its entrypoint, development consultation
guide, selected-model limitations, and relevant primitive documentation. Read the
current SubQ [Decisions API](https://docs.subq.ai/endpoints/decisions-api/),
[models](https://docs.subq.ai/using-the-api/models/), and
[retention policy](https://docs.subq.ai/using-the-api/data-retention/) before sharing
evidence with Snap.

For every substantial task that activates this skill, paired consultation is
mandatory at both checkpoints:

1. **Before implementation:** gather enough source evidence to assess the proposed
   approach, alternatives, risks, and verification plan, then consult both providers
   before implementation edits or dispatching implementation workers. For a task
   without implementation, consult before substantive drafting or review.
2. **During final review:** consult both providers again after integration and the
   relevant checks, before claiming completion or making an authorized publication.
   Use the exact completed work, current revision or diff, check results, and
   remaining limitations to assess acceptance, regressions, and evidence gaps.

These checkpoints are separate evidence batches. Always prepare a fresh final-review
request; pre-implementation advice cannot satisfy it. Reuse advice only within the
same checkpoint while its evidence, decisions, question meaning, and models remain
applicable. Routine turns do not require additional calls, but material changes
refresh affected consultations. Settled scope, model, and publication rules remain
constraints; ask about the approach or evidence rather than reconsidering those rules.
The coordinator must not skip a checkpoint because an approach seems obvious or
earlier advice was favorable. Workers return evidence and questions rather than
duplicate calls.

Each checkpoint requires bounded attempts to both providers within permitted
sharing. If a provider, credential, dependency, service, or permitted sharing is
unavailable, record the checkpoint, reason, and coverage; never bypass restrictions
or invent a response. Continue source investigation and independent review under
the existing fallback, disclose the limitation, and keep material unresolved facts
open. Provider unavailability alone does not block completion or justify retries.
Record both checkpoint dispositions in the task record.

Use [question patterns](references/jev-questions.json) with exact evidence,
constraints, and viable alternatives. Both providers receive the same permitted
minimal text evidence, questions, and options; only the model and endpoint differ.
Record the source revision and confirm excerpts match that revision before sending.
Neither provider has implicit repository or history access. They supply typed advice,
not code, findings, explanations, assumptions, proof, or permission. The common
workflow is Choice-only and must fit both providers' limits; Snap's larger context
and image support do not expand this shared request contract.

Use the policy's `jev-1.13.0` and `subq-snap-preview` model IDs. Snap's ID is a public
preview alias, not an invented immutable version; record the returned model and
recheck its contract when it changes. Batch independent questions sharing evidence
and send one request to each provider concurrently within a 30-second batch budget
covering startup, requests, and result transport. Each worker is bounded by the
remaining budget; cleanup is bounded afterward, and automatic retries are disabled.
Validate response IDs, types, allowed options,
finite probabilities, distributions, and resolved model independently. Separate
`TYPESAFE_API_KEY` and `SUBQ_API_KEY` credentials remain outside inputs and records.
For the helper's request, output, and privacy contract, read
[consultation helper](references/consultation-helper.md) before using it.

Codex owns the final decision. Compare both judgments against the exact source and
relevant tests or observations, even when they agree. Do not select a winner by
confidence, probability, majority vote, or provider identity. Disagreement identifies
what to investigate; invalid or insufficient advice remains an investigation lead.
In the agreed task record retain the conclusion, supporting evidence references and
verification, reasons for rejecting a judgment, unresolved facts, and provider coverage.
The helper initializes `final_decision` as `pending`; it never chooses an answer.
After verification, use its no-network `--adjudicate` mode to validate Codex's
disposition and write a new final record, preserving the original provider record.
If one provider is unavailable, continue source work and disclose partial coverage.
If a material fact is missing or conflicting, leave the final decision unresolved.
Advice and confidence never grant authorization.

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
structural fixtures, fresh discovery, model advice, tests, CI, and deployment remain
distinct. Mention materially used Jev/Snap advice and triggered providers that were
unavailable; identify Codex's independently supported decision.
