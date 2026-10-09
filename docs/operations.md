# Installation operations

## Install and inspect

Use clean committed source and an existing Codex installation:

```sh
./install.sh --dry-run
./install.sh
cw status
```

The bootstrap obtains a verified executable, then Go performs the installation.
The default action is install; setup remains an alias. Mutations apply by default;
add --dry-run for a read-only local preview. A cold bootstrap preview reports
deferred validation without downloads or writes. cw status itself is offline.
The manager needs no Python or virtual environment; skill-specific helper scripts
retain their own dependencies.

Status reports `model_profiles` with each configured model, reasoning effort, and
scope from the active snapshot. This is policy evidence. It does not identify the
model or effort used by an existing chat or establish account runtime availability.

## Paths and ownership

--source selects the checkout. --home selects the installation home; --codex-home
selects the existing Codex directory; --state-dir selects device-local state.
Initial defaults use the user home, CODEX_HOME, and XDG_STATE_HOME. Subsequent
installed commands resolve their installation locator rather than the current
working directory. Explicit flags can override recorded paths.

```sh
./install.sh --home '/path/with spaces/home' --codex-home /path/to/codex --state-dir /path/to/state
```

State holds immutable releases/<SHA> snapshots, the active current pointer,
ownership/history, recovery records, and immutable manager runtime versions.
Skill registrations resolve through current. The source checkout remains editable;
installed snapshots are never edited directly. The manager version and active
skill revision are distinct, especially after rollback or --no-checkout.

The current manifest manages 26 registrations with 71 entrypoints, a marked block in global AGENTS.md,
the top-level model/model_reasoning_effort values, and enrolled command/PATH
registration. It preserves unrelated content, comments, modes, credentials, and
repository instructions. Original settings and adopted registrations remain
reserved for uninstall. Modified owned content is a conflict.

## Direct cw command

The managed ~/.local/bin/cw link executes the Go binary beneath the selected
state directory. It never calls install.sh. A PATH block is added only when
necessary. Use --shell bash, --shell zsh, or --shell none during install to
override shell selection. Unknown shells and custom zsh startup locations are
reported for manual PATH enrollment. Existing unowned cw definitions/paths are
not replaced.

Open a new terminal after migration. An existing shell may retain the former
function: use unfunction cw in zsh or unset -f cw in Bash, then reload the matching
startup file. Retain unrelated shell/profile edits.

## Migration

Existing managed installations are read using their historical state and checksum
format. Run the new bootstrap with explicit source when migrating an installation
that previously used --shell none. Recover any pending old journal before
migration. Source-independent removal of an owned legacy block does not require
its old launcher to remain executable.

For unmanaged legacy registrations, opt in to their adoption explicitly:

```sh
./install.sh --migrate-from /path/to/previous-source --dry-run
./install.sh --migrate-from /path/to/previous-source
```

For the separately installed TypeSafe skill under the selected home's
.codex/skills/typesafe-ai, add --typesafe-legacy. Adoption verifies its exact
matching files and keeps an ownership-checked backup. Unrelated occupied or
dangling paths remain conflicts. Credentials are never migration inputs.

The known vendor-to-third_party resource move changes owned registration targets
through the journal. Historical snapshots/receipts stay intact. Rollback derives
targets and names from the older snapshot. Forward install/update may add new
registrations but refuses removal, rename, or arbitrary retargeting of existing
ones. Each addition must be absent under ~/.agents/skills and free of collisions
under both the selected Codex home and standard ~/.codex/skills. New names are
not adopted from occupied paths, including dangling symlinks, during ordinary
installation or update.

### Manager v3, v4, or v5 to v6

After a compatible cw-manager-v6 release is published, run these commands from
the clean checkout:

```sh
git pull --ff-only
./install.sh --adopt-personal-skills
cw status
```

The old cw update rejects manifest v2 during validation, before
acquiring the new runtime. This one-time bootstrap route upgrades without
uninstalling or losing adoption records. The policy changes to Sol 6.1 max for
coordinator/substantive work, Luna xhigh for bounded execution, and Luna high for
bounded evidence. These model defaults are retained from v5. The pack grows to
26 registrations and 71 entrypoints.

Bootstrap verifies platform, checksum and capability. If latest still serves v3
v4, or v5, it refuses activation and preserves the old binary and owned installation.
Retry after v6 publication. Go separately requires an exact candidate runtime, downloading
its release or building source if unavailable. Building requires the Go version
in go.mod. An independently verified exact-commit local v6 binary can be used in
isolated development environments before publication.

Recover a pending old transaction before migration. If an interruption leaves cw
running an older manager during the first v6 activation, use ./install.sh recover
with the compatible v6 cached bootstrap binary. Before writing a v2 journal,
activation stages a verified v6 executable, sealed locator, and receipt beneath
STATE/runtime/releases/REVISION/. Without the checkout, invoke that exact
STATE/runtime/releases/REVISION/cw executable directly with `recover`. Its
immutable locator retains installation roots even if recovery has already
reversed the active runtime pointer. Custom roots can also be supplied explicitly
with --source, --home, --codex-home, and --state-dir. Preserve receipts and journals;
the old enrolled command cannot recover a v2 transaction.

### Adopting standalone personal skills

Only install/setup accepts --adopt-personal-skills. A fresh installation with
absent destinations needs no flag. An existing standalone production-plan,
Archify, or Docker skill requires explicit adoption:

```sh
./install.sh --adopt-personal-skills --dry-run
./install.sh --adopt-personal-skills
cw status
```

Manifest v2 refers to personal-skill-origins.json. Its source-relative hashes,
paths, and modes describe the verified originals, including files deliberately
omitted from the distributed Archify runtime. Exactly one matching directory
may exist per name across ~/.agents/skills, the selected Codex skills directory,
and standard ~/.codex/skills. Duplicate directories, modified contents or modes,
dangling links, symlink aliases, unsafe paths, occupied backups, and a backup on
an incompatible filesystem are conflicts. No copy fallback is attempted.

The manager moves originals into STATE/backups/personal-skills/NAME and records
their inventories. Adoption composes the original directory, backup, and managed
link into one recoverable operation; this also handles Archify occupying its own
managed registration path. All mutation paths are checked for overlap before
activation and recovery. Uninstall checks the owned links and original backup
inventories before restoring the directories. Changed owned content or backups
stop the transaction. No credentials or personal tool configuration are adopted.

Rollback refuses a target snapshot that omits an adopted registration. Keep the
current release or uninstall to restore originals; do not remove adoption records
to bypass this protection. Ordinary absent-origin additions remain removable by
rollback. Existing v1 snapshots, receipts, and journals retain their encoding;
pending legacy transactions must be recovered before adoption.

## Update and rollback

Install validates local HEAD without fetching. Repeated installation is a no-op
when owned content and runtime match. A clean local fast-forward can be installed;
divergent or rewound activation is refused. Updates are always manual:

```sh
cw update --dry-run
cw update
cw status
```

A preview checks local evidence without contacting GitHub. Applied update fetches
origin/main, validates the exact commit, prepares a verified manager candidate,
fast-forwards clean source, and activates owned changes recoverably. Candidate
preparation failure leaves the active installation unchanged. --no-checkout keeps
source HEAD while installing the fetched snapshot. Git uses existing authentication.
New destinations are preflighted before the Git fast-forward and checked again
before activation. Existing conflicts leave source HEAD and activation unchanged;
a subsequent external edit can still stop activation after Git advances. Recovery
preserves that fast-forward. Dry-run registration changes describe local evidence
without fetching a remote candidate.

```sh
cw rollback --dry-run
cw rollback
```

Rollback restores the previous skills and owned instruction/model defaults, while
keeping a compatible manager. It does not rewind source Git or change GitHub.
Returning to a previous snapshot with ultra restores its historical defaults
while retaining the v6 manager. Status then reports those restored model profiles.
The target snapshot must have a subset of the active registration names. A path
absent from that snapshot is removed only if its recorded origin was absent and
its current link remains exactly owned. Adopted symlink/directory origins cannot
be dropped; their restoration remains an uninstall responsibility.
Install/update/rollback require a fresh Codex chat to observe new instructions.

## Interrupted activation and removal

```sh
cw recover --dry-run
cw recover
```

Recovery reverses journaled owned changes, preserving unrelated edits and refusing
changed owned content. It includes runtime/command changes, and is a no-op without
a pending transaction. It does not rewind Git fast-forwards or delete caches.
Use a verified cached executable or ./install.sh recover if a crash occurred
before cw enrollment. Do not hand-edit ownership or recovery records.

```sh
cw uninstall --dry-run
cw uninstall
```

Uninstall restores adopted registrations/original model values and removes owned
registrations, global/PATH blocks, and the command link. It preserves source,
immutable caches, unrelated settings, credentials, and connectors. Reinstall
through ./install.sh. Status, recovery, rollback, and uninstall use installed
records even if source is dirty, invalid, or unavailable.
