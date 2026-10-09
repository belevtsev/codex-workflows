---
name: "security-threat-model"
description: "Build a repository-grounded threat model with trust boundaries, realistic abuse paths, and prioritized mitigations when threat modeling is requested."
---

# Threat Model Source Code Repo

Deliver an actionable AppSec-grade threat model that is specific to the repository or a project path, not a generic checklist. Anchor every architectural claim to evidence in the repo and keep assumptions explicit. Prioritizing realistic attacker goals and concrete impacts over generic checklists.

## Quick start

1) Collect (or infer) inputs:
- Repo root path and any in-scope paths.
- Intended usage, deployment model, internet exposure, and auth expectations (if known).
- Any existing repository summary or architecture spec.
- Use prompts in `references/prompt-template.md` to generate a repository summary.
- Use the output structure in `references/prompt-template.md` when it fits the request; omit sections that do not apply.

## Workflow

### 1) Scope and extract the system model
- Identify primary components, data stores, and external integrations from the repo summary.
- Identify how the system runs (server, CLI, library, worker) and its entrypoints.
- Separate runtime behavior from CI/build/dev tooling and from tests/examples.
- Map the in-scope locations to those components and exclude out-of-scope items explicitly.
- Do not claim components, flows, or controls without evidence.

### 2) Derive boundaries, assets, and entry points
- Enumerate trust boundaries as concrete edges between components, noting protocol, auth, encryption, validation, and rate limiting.
- List assets that drive risk (data, credentials, models, config, compute resources, audit logs).
- Identify entry points (endpoints, upload surfaces, parsers/decoders, job triggers, admin tooling, logging/error sinks).

### 3) Calibrate assets and attacker capabilities
- List the assets that drive risk (credentials, PII, integrity-critical state, availability-critical components, build artifacts).
- Describe realistic attacker capabilities based on exposure and intended usage.
- Explicitly note non-capabilities to avoid inflated severity.


### 4) Enumerate threats as abuse paths
- Prefer attacker goals that map to assets and boundaries (exfiltration, privilege escalation, integrity compromise, denial of service).
- Classify each threat and tie it to impacted assets.
- Keep the number of threats small but high quality.

Before consequential threat prioritization, or on an explicit user request, consult Jev through the installed `typesafe-ai` skill. Resolve it from the available skill catalog and read its `SKILL.md` and `references/development-consultations.md` from that skill's root. Supply candidate abuse paths and risk judgments grounded in actual exposure, controls, and attacker capabilities. Routine work does not otherwise require consultation. The task coordinator owns requests, batching, and reuse across skills; reviewers contribute evidence and bounded questions. Treat typed judgments as advice, not generated threats, proof of exploitability, validated controls, or authorization. Independently verify conclusions even at high confidence. If consultation is missing, unavailable, or inconclusive, state the limitation and continue with source evidence.

### 5) Prioritize with explicit likelihood and impact reasoning
- Use qualitative likelihood and impact (low/medium/high) with short justifications.
- Set overall priority (critical/high/medium/low) using likelihood x impact, adjusted for existing controls.
- State which assumptions most influence the ranking.

### 6) Resolve material uncertainty
- Establish deployment, exposure, ownership, and authorization context from available evidence. Reuse answers already given.
- Ask a focused question only when missing context materially changes scope or ranking and cannot be established from the repository. Continue independent analysis while waiting.
- Do not require a confirmation round for every threat model. State reasonable unresolved assumptions and their effect on priority; deliver conditional recommendations when useful within the requested scope.

### 7) Recommend mitigations and focus paths
- Distinguish existing mitigations (with evidence) from recommended mitigations.
- Tie mitigations to concrete locations (component, boundary, or entry point) and control types (authZ checks, input validation, schema enforcement, sandboxing, rate limits, secrets isolation, audit logging).
- Prefer specific implementation hints over generic advice (e.g., "enforce schema at gateway for upload payloads" vs "validate inputs").
- Base recommendations on validated user context; if assumptions remain unresolved, mark recommendations as conditional.

### 8) Run a quality check before finalizing
- Confirm all discovered entrypoints are covered.
- Confirm each trust boundary is represented in threats.
- Confirm runtime vs CI/dev separation.
- Confirm user clarifications and unresolved assumptions are reflected; elapsed time is not an answer.
- Confirm assumptions and open questions are explicit.
- When Jev consultation influences the model, retain request/evidence provenance, resolved model, advisory answer/probabilities and confidence when supplied, the agent's disposition, and independent verification. Record consultation limits and fallback, separating advice from validated controls and executed checks.
- Match the requested output; use `references/prompt-template.md` as a reporting aid when needed.
- Deliver in chat or the artifact location requested by the user. For an agreed Markdown artifact, `<repo-or-dir-name>-threat-model.md` is a useful name; do not introduce reports into a live checkout during a read-only review without authorization.


## Risk prioritization guidance (illustrative, not exhaustive)
- High: pre-auth RCE, auth bypass, cross-tenant access, sensitive data exfiltration, key or token theft, model or config integrity compromise, sandbox escape.
- Medium: targeted DoS of critical components, partial data exposure, rate-limit bypass with measurable impact, log/metrics poisoning that affects detection.
- Low: low-sensitivity info leaks, noisy DoS with easy mitigation, issues requiring unlikely preconditions.

## References

- Output contract and full prompt template: `references/prompt-template.md`
- Optional controls/asset list: `references/security-controls-and-assets.md`

Only load the reference files you need. Keep the final result concise, grounded, and reviewable.
