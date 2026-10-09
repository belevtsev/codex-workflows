# Installation operations

To set up from any checkout location, use clean, committed source:

```sh
./install.sh
./install.sh status
```

The default launcher action is `setup`. It creates or reuses the checkout's
ignored `.venv`, installs pinned PyYAML 6.0.3 and tomlkit 0.13.3, validates the
committed snapshot, activates it, enrolls the two root Codex config defaults and cw,
and reads back status. Git, Python 3.9 or newer with `venv`, and an existing
Codex installation are prerequisites. No runtime or optional service is
installed automatically.

Launcher mutations (`setup`, `update`, `rollback`, `recover`, and `uninstall`)
apply by default. Add `--dry-run` to preview an action:

```sh
./install.sh --dry-run
./install.sh update --dry-run
```

A launcher dry run makes no environment, download, or installation-state
writes. When `.venv` is not prepared, full validation is explicitly deferred.
`status` is read-only and never prepares the environment; missing pinned
dependencies cause a deferred-status error. No API key is required.
Only `setup` and `update` require a clean current checkout and full validation
of its source. `status`, `recover`, `rollback`, and `uninstall` operate on owned
state and validated releases, so they remain usable while current source is
dirty or its suite content is invalid. They still need the launcher's prepared
dependencies; a damaged source checkout must retain a usable launcher and
bootstrap implementation.

The direct bootstrap interface remains compatible: `install`, `setup`,
`update`, `rollback`, `recover`, and `uninstall` show their plan unless `--apply`
is present. `install` owns registrations and global instructions only; `setup`
also enrolls config and shell-command ownership. For example:

```sh
.venv/bin/python scripts/bootstrap.py setup
.venv/bin/python scripts/bootstrap.py setup --apply
```

## Paths and ownership

`--home` selects the user home, and `--codex-home` selects the Codex directory
(otherwise `CODEX_HOME`, then the selected home's `.codex` directory).
`--state-dir` overrides the state location. Otherwise state is stored under
`$XDG_STATE_HOME/codex-workflows`, or `~/.local/state/codex-workflows` when
`XDG_STATE_HOME` is unset. The launcher uses its own checkout as the source;
the direct bootstrap also accepts `--source`.

The state directory contains a `releases/<SHA>` snapshot for each installed
commit, a `current` link, and ownership and activation records. Skill
registrations under the selected home's `.agents/skills` point through the
managed release. The global Codex `AGENTS.md` has a managed block delimited by
`codex-workflows-start` and `codex-workflows-end`; bytes outside that block are
preserved. Repository-specific `AGENTS.md` files remain in their repositories.

Setup also owns the root `model` and `model_reasoning_effort` settings in
`config.toml`. Their values come from the validated release's coordinator model
policy, currently `gpt-6.1-sol` and `ultra`. It preserves unrelated config keys,
comments, permissions, trusted projects, and credentials. Malformed TOML,
symlinked config paths, and later changes to owned values are refused.

The original values or absence of the two owned keys are recorded at first
enrollment and retained independently of activation history until uninstall.
Setup can enroll an existing version 1 installation without losing its original
registration ownership or history.

## The cw command

Setup adds a marked `cw` shell function to the selected home's `.bashrc` or
`.zshrc`. It detects Bash or zsh from `SHELL`, using Bash when `SHELL` is absent.
Use `./install.sh --shell bash`, `--shell zsh`, or `--shell none` to choose or
skip enrollment. Unsupported shells and custom `ZDOTDIR` locations are reported
as manual setup steps; the workflow installation can still complete.

Open a new terminal, or load the selected file in the current Bash/zsh terminal.
Bash login shells may require sourcing `.bashrc` from their local profile.

```sh
cw help
cw help update
cw update --help
cw status
```

Help works offline before dependencies are prepared; use `./install.sh help`
before `cw` is loaded. The function routes to the absolute editable checkout
and captures its installation's home/Codex/state overrides, so it works from
another directory. Keep that checkout at its installed location.

The shell block joins the installation's ownership and recovery journal.
Unrelated startup-file bytes and permissions are preserved; the journal stores
only the owned block. Existing `cw` definitions, symlinked startup files, malformed
markers, and changed owned content are conflicts. Uninstall removes only the
owned block and retains unrelated later edits. Rollback keeps the enrolled command
available through the editable checkout, including when the target release
predates command enrollment. An already running shell retains its loaded function
until that shell exits or the function is explicitly unset.

Pass the same path overrides on subsequent commands for a custom installation:

```sh
./install.sh \
  --home /path/to/user-home \
  --codex-home /path/to/codex-home \
  --state-dir /path/to/workflow-state
```

Do not edit release snapshots or the `current` link manually. Make maintained
changes in the source checkout, validate and commit them, then activate through
setup or update. Ownership checks reject conflicting paths and modified managed
content so another installation or a local edit is preserved.

## Migrate an existing installation

Review existing registrations and keep the previous source until migration is
verified. Identify it explicitly rather than treating every existing skill as
owned by this repository:

```sh
./install.sh --migrate-from /path/to/previous-source --dry-run
./install.sh --migrate-from /path/to/previous-source
```

For the separately installed TypeSafe skill at `~/.codex/skills/typesafe-ai`, add
`--typesafe-legacy` to opt in. An explicit path must identify that same location
under the selected `--home`, for example
`--typesafe-legacy /path/to/user-home/.codex/skills/typesafe-ai`. Adoption requires
exactly the three matching vendored files and their modes. The installer keeps
an ownership-checked backup for restoration. Credentials stay local and are not
migration inputs.

## Setup, update, and rollback

Setup validates and activates local HEAD without fetching. Repeating setup at
the active SHA leaves the release unchanged while enrolling config if needed.
A clean local fast-forward of the active SHA can be activated by setup when its
registration manifest is unchanged. Diverged or rewound history is refused.

To explicitly fetch and activate a remote update:

```sh
./install.sh update --dry-run
./install.sh update
./install.sh status
```

A prepared dry run validates local source HEAD and reports the planned remote
fetch; it does not contact GitHub. An applied update fetches `origin/main`,
validates the selected commit, stages its exact SHA as a release, fast-forwards
the clean source checkout, and activates the release. Add `--no-checkout` to
keep the source checkout at its current commit while activating the fetched
release. Updates never activate uncommitted source changes. Git authentication
uses the machine's existing personal configuration; the launcher does not
install credentials.

Version 1 refuses an update that changes registration names or source roots.
Review such a manifest change, then explicitly uninstall and set up the new
installation so ownership is established deliberately.

To return to the previous validated active release:

```sh
./install.sh rollback --dry-run
./install.sh rollback
./install.sh status
```

Rollback follows activation history and does not reset the source checkout's
Git revision. Enrolled config defaults follow the rollback target's coordinator
policy; the original config values remain reserved for uninstall. Open a fresh
Codex chat after setup, update, or rollback. An existing chat can retain already
loaded instructions, skill content, and model settings.

## Interrupted activation and removal

If activation was interrupted, inspect status and the recovery plan:

```sh
./install.sh status
./install.sh recover --dry-run
./install.sh recover
./install.sh status
```

Recovery undoes the interrupted activation only when expected ownership still
matches. A conflict requires reviewing and preserving the changed file or
registration before another attempt. Verify completion through status.

To remove managed registrations and the global block, restore adopted legacy
registrations where applicable, and restore the original owned config keys:

```sh
./install.sh uninstall --dry-run
./install.sh uninstall
./install.sh status
```

Uninstall checks ownership and protects local edits. Unrelated later config
edits and comments, skills, global instructions, and credentials are preserved.
Release snapshots remain cached in the state directory, and the checkout's
`.venv` remains available; uninstall reports the retained release-cache location.

There is no background synchronization or scheduled update. Jev credential
reporting checks presence only and never makes a consultation request.
Connectors need separate authentication in Codex on each device.
