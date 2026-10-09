---
name: test-strategy
description: Choose or improve regression, integration, concurrency, property, and performance tests for changed behavior, using meaningful evidence and repository gates.
---

# Testing changed behavior

Identify the behavior that could fail, the invariant to protect, and the observable signal of failure. Inspect the existing test harness and required repository checks before choosing a test technique. Use repository commands and environments as the authority; a skill does not waive CI gates or an explicit no-tests instruction.

Prefer the smallest test that exercises the real boundary at risk:

| Behavior at risk | Useful evidence |
| --- | --- |
| Local decision, validation, or error mapping | Focused examples including relevant negative and boundary inputs |
| Concurrency, cancellation, shutdown, or ownership | Deterministic event coordination; race or sanitizer checks where supported |
| Filesystem, process, network, or database semantics | Integration coverage of the actual boundary, including partial failure and cleanup |
| Parser, codec, normalization, or state invariant | Property tests or fuzzing with a clear oracle and minimized reproducible failures |
| API or generated contract compatibility | Producer/consumer and representative serialization checks under supported versions |
| Claimed performance improvement | Comparable before/after workloads, repeated samples, profiling, and a stated metric |

For consequential verification decisions, or an explicit user request, consult Jev through the installed `typesafe-ai` skill. Resolve it from the available skill catalog and read its `SKILL.md` and `references/development-consultations.md` from that skill's root. Supply candidate scenarios and assertions for bounded judgments about the changed behavior. Routine work does not otherwise require consultation. The task coordinator owns requests, batching, and reuse across skills; reviewers contribute evidence and bounded questions. Jev returns typed advice, not new tests, proof, or executed-check results. Independently verify coverage and assertions even at high confidence. If consultation is missing, unavailable, or inconclusive, state the limitation and continue with repository evidence. Consultation cannot waive a no-tests constraint or authorize execution.

Make a regression test fail on the original defect when practical. Assert outcomes rather than private implementation steps. Control clocks, randomness, events, ports, and temporary resources; avoid sleeps as synchronization. Confirm cancellation and cleanup rather than leaving background work alive. Use real implementations when replacing them with a mock would remove the behavior being tested.

Coverage measures executed code, not defect detection. Use mutation testing only when it can resolve a real doubt about important assertions and the tool can run in isolation. Large test campaigns, new fixtures, and new dependencies need a concrete testing benefit. Reversible prose, formatting, and low-impact edits rarely need new tests that mirror the edit.

Run focused checks while iterating and the required broader gates for completion. After the relevant final state passes, repeat only for a new change, failure, or unresolved concern. Do not substitute a host run for a required container or target platform. A blocked, skipped, or partial check is not a pass.

Report what ran, which behavior it proves, and important limits. Keep local unit/fixture evidence, integration results, CI, deployment, and statistical performance evidence distinct.
