# Development checks

The installer and suite/policy validation run in Go, using the version pinned in
`go.mod`. Workflow skills and optional tool integrations keep their own language
requirements. Source contains vendored skills under `vendor/`; this is not a Go
module vendor tree. Always use `-mod=mod` and never run `go mod vendor`.

```sh
GOWORK=off go test -mod=mod -race -count=1 ./...
GOWORK=off go vet -mod=mod ./...
GOWORK=off go run -mod=mod ./cmd/cw validate --source "$PWD"
scripts/native-smoke.sh
```

Run tests in the environment authorized for the task. Fixtures use temporary
homes, state, Git repositories and synthetic HTTP responses. They never change
the user's installation or contact connected services. Preserve version-one
state/checksum compatibility, immutable snapshots, selective configuration edits,
adoption restoration, and recovery at every transaction boundary. Real Bash and
Zsh tests verify the installed shell block. Native macOS tests supply separate
filesystem evidence; Linux results do not prove Mac behavior.

CI has two native jobs, Linux and macOS, with cached Go dependencies. Each runs
all Go tests with the race detector, vet, source validation and a fresh launcher
smoke. Full Python matrices and repeated Python environment preparation are no
longer in the normal pipeline. Superseded PR runs are cancelled. Main commit runs
are retained because every successful main push must publish its own release.

The release job waits for both checks, cross-builds four CGO-disabled binaries,
and publishes SHA256SUMS. Version is `v1.0.<workflow run number>`; target is the
exact validated SHA. An uncertain create/upload is read back before continuing.
Existing tag/asset differences are conflicts. Builds use the commit timestamp
and trimmed paths, with fixed toolchain and dependencies.

```sh
scripts/build-release.sh v1.0.0 "$(git rev-parse HEAD)"
```

The previous Python implementation and tests remain as compatibility/regression
reference code. They are not called by `install.sh` or the native CLI. Historical
Python launcher fixtures expect the former launcher and must be compared against
that earlier committed checkout. They are not verification for the native
launcher; use the Go tests and native smoke above for current behavior.

Keep personal config, credentials, backups, evaluations, and installation records
outside source. Keep product behavior and repository-specific commands in their
owning repositories. `skills-manifest.json` defines the ten registrations; retain
upstream notices and keep THIRD_PARTY.md current. The installer activates only
committed snapshots, so source tests and installed-SHA evidence are distinct.
