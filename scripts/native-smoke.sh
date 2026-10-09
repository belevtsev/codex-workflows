#!/bin/sh
# Fresh native CLI smoke against the exact committed source and isolated roots.
set -eu
root=$(CDPATH='' cd -P "$(dirname "$0")/.." && pwd)
smoke=$(mktemp -d)
trap 'rm -rf "$smoke"' EXIT HUP INT TERM
source="$smoke/source with spaces"
home="$smoke/home with spaces"
state="$smoke/state with spaces"
git clone --quiet --no-hardlinks "$root" "$source"
revision=$(git -C "$root" rev-parse HEAD)
[ "$(git -C "$source" rev-parse HEAD)" = "$revision" ]
mkdir "$source/.bin"
(cd "$root" && CGO_ENABLED=0 GOWORK=off go build -mod=mod -trimpath -ldflags "-X main.version=smoke -X main.revision=$revision" -o "$source/.bin/cw" ./cmd/cw)
unset TYPESAFE_API_KEY CODEX_HOME XDG_STATE_HOME CODEX_WORKFLOWS_FAULT
cd "$smoke"
launch() { "$source/install.sh" "$@" --home "$home" --codex-home "$home/.codex" --state-dir "$state"; }
launch --dry-run --shell bash > "$smoke/preview.json"
[ ! -e "$home" ] && [ ! -e "$state" ]
launch --shell bash > "$smoke/setup.json"
grep -F '"installed":true' "$smoke/setup.json" >/dev/null
[ ! -e "$source/.venv" ]
for skill in cc-skills-golang code-review db-postgres drawio-skill go-principal-engineer security-threat-model software-architecture task-orchestration test-strategy typesafe-ai; do
  [ -L "$home/.agents/skills/$skill" ] && [ -d "$home/.agents/skills/$skill" ]
done
cp "$state/state.json" "$smoke/state-before.json"
cp "$home/.codex/config.toml" "$smoke/config-before.toml"
cp "$home/.bashrc" "$smoke/rc-before"
launch > "$smoke/repeat.json"
cmp "$state/state.json" "$smoke/state-before.json"
cmp "$home/.codex/config.toml" "$smoke/config-before.toml"
cmp "$home/.bashrc" "$smoke/rc-before"
bash --noprofile --norc -c '. "$1"; cw help; cw status' cw-smoke "$home/.bashrc" > "$smoke/alias.txt"
grep -F '"installed":true' "$smoke/alias.txt" >/dev/null
launch status > "$smoke/status.json"
launch recover > "$smoke/recover.json"
launch uninstall > "$smoke/uninstall.json"
grep -F '"installed":false' "$smoke/uninstall.json" >/dev/null
[ ! -e "$home/.bashrc" ] && [ ! -e "$home/.codex/AGENTS.md" ]
printf '%s\n' 'Native setup, preview, status, alias, repeat, recovery no-op and uninstall passed without Python.'
