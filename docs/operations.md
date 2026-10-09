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

The manager owns ten skill registrations, a marked block in global AGENTS.md,
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
targets from the older snapshot; arbitrary registration changes are refused.

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

```sh
cw rollback --dry-run
cw rollback
```

Rollback restores the previous skills and owned instruction/model defaults, while
keeping a compatible manager. It does not rewind source Git or change GitHub.
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
