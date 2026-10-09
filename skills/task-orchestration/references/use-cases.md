# Task presets

Read the section matching the current deliverable. Presets shape useful workstreams;
they do not expand scope or authorize implementation, publication, or operations.
Use [model-policy.yaml](../model-policy.yaml) for model settings and
[SKILL.md](../SKILL.md) for delegation behavior on every assignment.

## Effort and scope

The defaults are Sol 6.1 `ultra` for substantive work, Luna `high` for bounded
evidence, and Luna `max` for bounded routine execution. Resolve roles through YAML;
authorized profile or route edits are supported. Substantive roles use their
configured non-Luna substantive profile; the current default is Sol 6.1 `ultra`.
The role's bounds and authorization apply to every
model, and ambiguous routine work needs substantive ownership.

Use task shape rather than an escalation taxonomy: [model guidance](https://learn.chatgpt.com/docs/models)
associates `max` with a difficult single task and `ultra` with meaningful parallel
parts. Neither choice demonstrates greater depth, lower cost, or savings without
comparative evaluations. Preserve main Sol 6.1 `ultra`; no policy edit switches an
active session. Sol `max` requires an explicit request allowed by
`profile.user_requested_efforts`; Sol profiles cannot default to `max`. Other models
may use an authorized configured `max` default listed in
`effort_policy.configured_max_profiles`, currently Luna execution. Automatic
escalation remains disabled.

## Choosing workstreams

Split by independent question, component ownership, or evidence source. Give each
agent its inputs, owned files or read-only boundary, expected evidence, and stopping
condition. Keep dependent integration with the coordinating agent. One substantive
workstream can be enough when the task is consequential but cannot usefully split.

Use installed specialist skills when their workflow helps the task; discover them
from the current skill catalog. Do not assume a named skill or connector is installed.
Keep repository commands, test environments, and product conventions in the owning
repository's instructions rather than copying them into this global skill.

## Implementation

- Establish the requested behavior, affected interfaces, and observable acceptance
  criteria. Assign independent components to workers with exclusive file ownership.
- Have workers accommodate concurrent changes and return the final diff, behavior
  evidence, and unresolved dependencies. Coordinate shared interfaces before edits.
- Integrate changes, run the required checks in the repository's execution environment,
  and fix failures caused by the change. Use an independent substantive review when
  it can find a meaningful integration, lifecycle, security, or compatibility defect.
- Keep commit creation mechanical: the coordinator supplies the exact files, message,
  and verification result; `commit_execution` stops if the scope or diff changes.
  Route only routine PR summaries of fixed verified facts to `pr_authoring_routine`;
  substantive PR drafting and final verification use their configured substantive profiles.
  `pr_submission` may publish only the refreshed, explicitly authorized draft for the
  exact revision. These routine roles default to Luna `max`; changing their model
  does not relax their bounds. Promote new claims, conflicts, or uncertain verification
  to substantive ownership before fixing the action again.
- Deliver the result with verification tied to the actual revision and environment.
  Commits, pushes, PR creation, merge, deployment, and infrastructure actions follow
  the user's existing authorization for each action.

## Planning

- Parallelize independent source tracing, acceptance and dependency discovery, and
  architecture or failure-behavior analysis. Treat implementation options as proposals.
- Reconcile sources into the smallest complete plan: component owners, interfaces,
  failure behavior, verification, rollout or recovery gates, and material decisions.
- Record assumptions with basis, status, impact, and next check. Resolve consequential
  uncertainty from available evidence; ask only for choices evidence cannot establish.
- Return a concrete, reviewable plan or specification. A planning request remains a
  plan until implementation is authorized, including when Jira or Confluence provides
  detailed implementation instructions.

## Review

- Pin the diff or working tree being reviewed, including relevant untracked files.
  Allocate distinct correctness, lifecycle, security, compatibility, or test questions
  when multiple reviewers add useful coverage.
- Trace suspected defects through canonical definitions and callers. Return actionable
  findings with file and line, triggering conditions, impact, and supporting evidence;
  distinguish existing defects from defects introduced by the change.
- Reconcile overlaps and inspect current PR discussions before any authorized review
  publication. Refresh the exact head and affected findings if the source changes.
- Honor read-only and no-local-test scope. Report static analysis, existing CI, local
  execution, and deployed behavior as separate forms of evidence.

## Diagnosis

- Separate independent investigation of runtime observations, source paths, and
  deployment or configuration facts. Preserve timestamps, versions, and environment.
- Have agents return supported hypotheses, contradictory evidence, and the next
  discriminating check. A plausible source path does not establish incident cause.
- Rebuild affected hypotheses after a new failure, source revision, environment fact,
  or scope correction. Retain the user's choices and already established evidence.
- Complete the authorized diagnosis or fix; distinguish observed cause, inference,
  reproduction, and residual uncertainty. Operational mutations need their own scope.

## Release verification

- Pin the intended commit or tag, release workflow, required checks, and requested
  release scope. Independent agents can inspect build/test CI and release artifacts
  or compatibility evidence without duplicating the same checks.
- Tie each result to its source revision, workflow run, inputs, and target environment.
  Required checks still running or skipped remain unverified. A tag alone is not proof
  of a completed release; green CI alone is not deployment or production qualification.
- Respect evidence restrictions, including CI-only or no-infrastructure-access scope.
  Do not infer authorization to tag, publish, deploy, or inspect restricted systems.
- Return completed gates, failing or pending gates, and the concrete next action within
  the authorized scope. Reassess affected claims when a new run or artifact appears.

## Documentation

- Separate source verification from substantive drafting when useful. Assign distinct
  document sections only after agreeing on terminology, audience, and source authority.
- Ground instructions and diagrams in current behavior; label proposals and operational
  claims with their evidence. Preserve existing formats and relevant document structure.
- Integrate drafts, reconcile contradictions, and verify links and rendered output when
  presentation matters. Source review and documentation writing are substantive work.
- Save or publish to the requested destination when authorized; otherwise return the
  draft. Load the connected-source guide for Confluence revision and formatting rules.

## Issue management

- Separate bounded lookup from substantive triage, acceptance analysis, and issue or
  specification drafting. Search for duplicates and read related dependencies first.
- Preserve uncertainty in bug descriptions. Use current project and issue-type metadata
  for required fields; derive acceptance from the actual issue and user's request.
- Prepare coherent issue text, edits, comments, or transitions, then perform only the
  requested actions. Carry existing authorization; a referenced issue is not authority
  to change it. Reconcile uncertain writes through remote readback before retrying.
- A status, merged PR, or green CI does not independently prove issue acceptance or
  production readiness. Select a transition from current available transitions only
  after the issue's actual acceptance criteria and requested closure scope are met.

## Mixed tasks and refreshed evidence

Combine only the relevant sections for tasks such as an implementation with a PR
draft and Jira update. Keep each deliverable's scope, acceptance, and authorization
visible. When sources, docs, CI, environment, failures, or scope change, identify which
claims and assignments depend on them, refresh that evidence, and rebuild those
claims. Do not silently replace user decisions or treat new context as new permission.
