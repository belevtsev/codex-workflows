---
name: go-principal-engineer
description: Resolve ownership, lifecycle, durability, or rollout decisions in production Go services, with explicit failure behavior and proportionate verification.
---

# Production Go decisions

Establish the observable outcome and invariant at risk. Use the existing repository ownership model; load a focused technical reference only when it resolves a real uncertainty. A routine local change does not need a separate architecture exercise.

For a consequential change, identify who owns mutable state, work, cancellation, and external effects. Trace relevant timeout, duplicate, partial-success, restart, and rollback paths. Name compatibility boundaries that actually change: API, protobuf, storage, configuration, metrics, or operator behavior.

For consequential ownership, lifecycle, or recovery decisions, or an explicit user request, consult Jev through the installed `typesafe-ai` skill. Resolve it from the available skill catalog and read its `SKILL.md` and `references/development-consultations.md` from that skill's root. Supply grounded candidate choices and focused claims about constraints and failure behavior. Routine work does not otherwise require consultation. The task coordinator owns requests, batching, and reuse across skills; reviewers contribute evidence and bounded questions. Jev returns typed advisory judgments, not proofs or authority to act. Independently verify the chosen behavior even at high confidence. If consultation is missing, unavailable, or inconclusive, state the limitation and continue with source evidence.

Prefer the smallest design that gives each invariant one authority. A new layer, interface, goroutine, queue, retry loop, cache, dependency, or persisted field should solve a concrete problem with a named owner. Keep irreversible effects behind the appropriate admission/durability boundary. Fence work when persisted state can no longer describe an externally visible effect. Bound concurrency, queues, retries, memory, and shutdown waits; keep slow work off liveness-critical paths unless ordering requires it.

For agents and daemons, examine crash consistency, offline recovery, disk failure, clock changes, and usable readiness when relevant. Trusted-host assumptions do not remove crash recovery or sensitive-data handling. A diagram or boundedness argument may clarify a design; throughput and latency claims require measurements under stated conditions.

Verify the dangerous boundary through the repository's appropriate checks. Prefer deterministic event gates over sleeps. Complete required gates once for the final relevant state; do not require a full test campaign for every design question or minor edit. Respect review-only and no-tests scope. Report concrete findings, the chosen owner and failure behavior, evidence, and residual risk; stop when the requested change is complete rather than extending it into unrelated cleanup.
