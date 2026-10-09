---
name: code-review
description: Review pull requests or local diffs for concrete correctness, lifecycle, security, compatibility, and test gaps, with evidence tied to changed code.
---

# Evidence-based code review

Establish the requested scope and exact base/head or local diff. Inspect status and relevant untracked files so they are neither overlooked nor mistaken for part of the change. Read repository conventions, neighboring code, callers, and tests needed to verify the changed behavior. A review remains read-only unless implementation or an external review action is authorized.

Prioritize defects with a concrete trigger and observable consequence. Trace inputs through changed code into consumers and persisted state when relevant. Check ownership, cancellation and shutdown, partial failures, retries and duplicates, bounds, authorization, secret handling, and API/configuration compatibility where the change touches them. Repository rules and supported environments take precedence over generic style preferences.

Review tests as evidence: a test should fail for the defect it claims to prevent and assert externally relevant behavior. Look for missed negative paths, unreliable timing, over-mocking of the boundary at risk, and checks that merely repeat implementation logic. Run appropriate verification only within the user's scope and repository environment; do not rerun valid evidence solely because it came from an earlier turn. Inspect current code, input, and environment changes to decide whether that evidence still applies.

For consequential suspected findings, or an explicit user request, consult Jev through the installed `typesafe-ai` skill. Resolve it from the available skill catalog and read its `SKILL.md` and `references/development-consultations.md` from that skill's root. Supply a candidate finding and exact evidence for a bounded support judgment. Routine work does not otherwise require consultation. The task coordinator owns requests, batching, and reuse across skills; reviewers contribute evidence and bounded questions. Jev returns typed advice, not generated findings, proof, or authority to post. Independently prove or discard each finding even at high confidence. If consultation is missing, unavailable, or inconclusive, state the limitation and continue with source evidence.

Prove or discard each suspected finding with the smallest useful read or check. Read existing review threads before preparing external comments and avoid duplicates. Do not invent findings to fill a quota. Separate a definite defect from an unresolved question; style-only preferences are not blocking unless they violate an actual project requirement.

For each actionable finding, provide severity, exact file/line, trigger, impact, and a concrete fix direction. Keep line ranges tight and identify whether the issue is introduced or made reachable by the change. Lead with findings. If none survive verification, say so and state the material validation limits. Do not approve, post, resolve, commit, or push unless that action is authorized.
