# Go development and releases

The manager and its development automation use the Go version pinned in go.mod.
Skills are separate resources under skills/ and third_party/; their helper scripts
retain their own dependencies. No Go module vendor tree is present.
The resource-only third_party module boundary keeps bundled example Go files
out of the manager's build and test package discovery.

The application has a thin command entrypoint, injectable CLI I/O, focused internal
installation/runtime/validation packages, and typed ownership/recovery boundaries.
Preserve exact historical JSON sealing, immutable receipts, and the distinction
between manager identity and the active skill snapshot.

## Verification

```sh
GOWORK=off go run ./cmd/cwdev check --race --source "$PWD"
```

The developer check verifies formatting and first-party script policy, runs native
tests/vet/source validation, builds the manager once, and runs isolated installation
smoke scenarios. Fixtures use temporary homes, synthetic Git repositories, and
mock HTTP services. They never change the user's installation, consult Jev, or
require service credentials. Real Bash/zsh execution verifies PATH enrollment.
Use `go test` with a focused package or test filter while developing; the complete
developer check runs the release verification gates once.

First-party automation must use Go. Only install.sh is allowed as a bootstrap;
script resources supplied by skills are explicitly exempt. Do not add Python
installer tests, environment preparation, or functional release shell scripts.

Frozen historical state/journal fixtures must remain readable after refactors.
Exercise interruption at every transaction boundary, changed owned content,
concurrent commands, custom paths, direct invocation outside source, resource-root
migration in both directions, and uncertain publication outcomes.

Additive registration scenarios must preserve historical ten-registration snapshots
and v1 checksums. Verify additions, pre-merge conflicts, rollback removal of only
absent-origin records, and source-independent recovery while the enrolled manager
still points at its older runtime. Bootstrap fixtures cover v3 refusal/v4 reuse and
exact-revision acquisition failures. Backend decision fixtures live in
internal/devcheck/testdata/backend-skills; give evaluators raw inputs without their
expected decisions. Model evaluations and fresh discovery are separate from native
test assertions; CI does not call hosted models or receive service credentials.

## Distribution

The separate cwdev tool owns release automation, not the user manager:

```sh
GOWORK=off go run ./cmd/cwdev release build --source "$PWD" --version v1.0.100 --revision COMMIT_SHA --dist "$PWD/dist"
GOWORK=off go run ./cmd/cwdev release publish --source "$PWD" --version v1.0.100 --revision COMMIT_SHA --dist "$PWD/dist"
```

Replace COMMIT_SHA and the example version with the intended exact committed
revision and unique version. Publication requires explicitly authorized GitHub
credentials; builds/checks do not. Binaries support macOS/Linux ARM64/AMD64, with
CGO disabled, trimmed paths, fixed archive metadata, dependency notices, and
SHA256SUMS. The publisher validates local assets before remote writes, verifies
exact tags/assets, reconciles uncertain outcomes, and refuses conflicting assets.
Readback allows bounded visibility delays after a write; mutations are attempted
once, and an unresolved outcome must be inspected before resuming publication.
Publishing an already exact public release performs no writes.

CI retains cached Linux/macOS tests and race checks. Release artifacts are prepared
alongside Linux validation, then reused by publication after both platform checks
pass. Every successful main push produces v1.0.<workflow run number> for its exact
SHA; main runs are not superseded by later commits. Only obsolete PR runs cancel.
Publication credentials exist only in the final job, and CI contains no shell
business logic. Publication uses GitHub's legacy latest-release policy so semantic
version/creation ordering governs overlapping releases.

Keep credentials, machine state, backups, evaluations, and audit outputs outside
source. Preserve all licenses/notices and maintain THIRD_PARTY.md. The manifest
defines thirteen registrations and 58 entrypoints; model defaults come from its
validated policy. The v4 bootstrap capability permits additive activation; older
managers require the one-time bootstrap migration documented in the README.
