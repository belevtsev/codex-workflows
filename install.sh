#!/bin/sh
# Run the native installer from this source checkout.
set -eu

checkout=$(CDPATH='' cd -P "$(dirname "$0")" && pwd)
binary=$checkout/.bin/cw
repository=belevtsev/codex-workflows

fail() {
    printf 'codex-workflows: %s\n' "$*" >&2
    exit 1
}

static_help() {
    cat <<'HELP'
cw — Codex workflows

Usage: ./install.sh [setup|status|update|rollback|recover|uninstall|validate|consult-jev|version|help] [options]

setup installs the validated local checkout and its cw shell command by default.
status verifies the installed release without fetching.
update fetches and activates origin/main; rollback restores the previous installation.
recover reverses an interrupted transaction; uninstall restores owned user settings.
validate checks the local workflow suite; version identifies the native installer.
consult-jev submits a prepared coordinator request to the installed Jev CLI.

Options: --dry-run, --home PATH, --codex-home PATH, --state-dir PATH,
         --shell auto|bash|zsh|none, --migrate-from PATH, --no-checkout,
         --request PATH, --output PATH (consult-jev)
Dry runs make no downloads or persistent writes. Initial setup prepares a verified
native binary from an exact-revision GitHub release or builds it with Go 1.27.1.
HELP
}

action=setup
has_action=false
want_help=false
dry_run=false
explicit_apply=false
bootstrap=false
prepare_only=false
skip_value=false
optional_value=false
for argument in "$@"; do
    if "$skip_value"; then skip_value=false; continue; fi
    if "$optional_value"; then
        optional_value=false
        case $argument in -*) ;; *) continue ;; esac
    fi
    case $argument in
        --help|-h) want_help=true ;;
        --dry-run) dry_run=true ;;
        --apply) explicit_apply=true ;;
        --bootstrap) bootstrap=true ;;
        --prepare-only) prepare_only=true ;;
        --source|--home|--codex-home|--state-dir|--shell|--migrate-from|--request|--output) skip_value=true ;;
        --typesafe-legacy) optional_value=true ;;
        --source=*|--home=*|--codex-home=*|--state-dir=*|--shell=*|--migrate-from=*|--request=*|--output=*|--typesafe-legacy=*|--json|--no-checkout) ;;
        -*) fail "unknown option: $argument" ;;
        *)
            if ! "$has_action"; then action=$argument; has_action=true
            elif [ "$action" != help ]; then fail "unexpected argument: $argument"
            fi
            ;;
    esac
done
if "$skip_value"; then fail 'an option needs a value'; fi
if "$dry_run" && "$explicit_apply"; then fail '--apply and --dry-run are mutually exclusive'; fi
if "$bootstrap" && ! "$explicit_apply"; then dry_run=true; fi
case $action in setup|status|update|rollback|recover|uninstall|validate|consult-jev|version|help) ;; *) fail "unknown command: $action" ;; esac
if "$prepare_only" && [ "$action" != setup ]; then fail '--prepare-only is supported only for setup'; fi
if "$prepare_only" && "$want_help"; then fail '--prepare-only cannot be combined with --help'; fi

case $(uname -s) in Darwin) target_os=darwin ;; Linux) target_os=linux ;; *) fail 'native cw supports macOS and Linux' ;; esac
case $(uname -m) in arm64|aarch64) target_arch=arm64 ;; x86_64|amd64) target_arch=amd64 ;; *) fail 'native cw supports arm64 and amd64' ;; esac

# The native CLI emits deterministic JSON. Require its complete version shape,
# platform, and a real Git revision before accepting an existing executable.
identify_binary() {
    [ -f "$1" ] && [ ! -L "$1" ] && [ -x "$1" ] || return 1
    identity=$("$1" version 2>/dev/null) || return 1
    identified=$(printf '%s\n' "$identity" | sed -n 's/^{"arch":"\([^"]*\)","built_at":"[^"]*","os":"\([^"]*\)","revision":"\([0-9a-f]*\)","version":"[^"]*"}$/\1 \2 \3/p')
    case $identified in "$target_arch $target_os "*) identified_revision=${identified#"$target_arch $target_os "} ;; *) return 1 ;; esac
    [ "${#identified_revision}" -eq 40 ] || return 1
    case $identified_revision in *[!0-9a-f]*) return 1 ;; esac
}

cached=false
if [ -L "$checkout/.bin" ] || { [ -e "$checkout/.bin" ] && [ ! -d "$checkout/.bin" ]; }; then fail '.bin is occupied or symlinked'; fi
if [ -e "$binary" ] || [ -L "$binary" ]; then
    identify_binary "$binary" || fail 'unidentified .bin/cw; remove or replace it with a verified native cw binary'
    cached=true
fi
if "$want_help" || [ "$action" = help ]; then
    if "$cached"; then exec "$binary" --source "$checkout" "$@"; fi
    static_help
    exit 0
fi

command -v git >/dev/null 2>&1 || fail 'Git is required for this source checkout'
revision=$(git -C "$checkout" rev-parse --verify HEAD) || fail 'cannot identify the source checkout HEAD'
case $revision in *[!0-9a-f]*) fail 'invalid source checkout revision' ;; esac
[ "${#revision}" -eq 40 ] || fail 'invalid source checkout revision'

run_native() {
    # Preparation is private launcher work, not a native activation command.
    if "$prepare_only"; then exit 0; fi
    if [ "$action" = update ] && ! "$dry_run"; then
        if update_report=$("$binary" --source "$checkout" "$@"); then
            :
        else
            update_status=$?
            [ -z "$update_report" ] || printf '%s\n' "$update_report"
            exit "$update_status"
        fi
        if updated_revision=$(git -C "$checkout" rev-parse --verify HEAD); then
            :
        else
            printf '%s\n' "$update_report"
            fail 'active workflows updated but source HEAD could not be checked for installer refresh'
        fi
        if [ "$updated_revision" != "$revision" ]; then
            # The running executable belongs to the former source HEAD. Prepare
            # the new installer without applying setup a second time, and keep
            # update's one original JSON report even after replacing the cache.
            if "$checkout/install.sh" setup --prepare-only >/dev/null; then
                :
            else
                printf '%s\n' "$update_report"
                fail 'active workflows updated but installer refresh failed; rerun ./install.sh setup from the updated checkout'
            fi
        fi
        printf '%s\n' "$update_report"
        exit 0
    fi
    exec "$binary" --source "$checkout" "$@"
}

case $action in
    setup|update)
        if "$cached" && [ "$identified_revision" = "$revision" ]; then run_native "$@"; fi
        ;;
    *)
        if "$cached"; then exec "$binary" --source "$checkout" "$@"; fi
        ;;
esac

if "$dry_run"; then
    # Preparing an environment is itself a mutation. A first dry run reports
    # this deferred gate without creating a cache, lock, Go cache, or download.
    printf '{"action":"%s","dry_run":true,"environment":{"kind":"native_go","revision":"%s","status":"deferred"},"next_step":"Run ./install.sh setup to prepare the exact-revision native installer","validation":"deferred"}\n' "$action" "$revision"
    exit 0
fi
case $action in setup|update) ;; *) fail "native installer is not prepared; run ./install.sh setup from a clean checkout before $action" ;; esac

# Preparation must not disguise edits as the source revision embedded in cw.
dirty=$(GIT_OPTIONAL_LOCKS=0 git -C "$checkout" status --porcelain --untracked-files=all) || fail 'cannot inspect source checkout cleanliness'
[ -z "$dirty" ] || fail 'source checkout is dirty; commit or preserve its changes before preparing cw'

lock=$checkout/.bin.lock
mkdir "$lock" 2>/dev/null || fail 'another native installer preparation holds .bin.lock; wait and retry (remove a stale lock after its process has exited)'
temporary=
candidate=
cleanup() {
    [ -z "$temporary" ] || rm -rf "$temporary"
    [ -z "$candidate" ] || rm -f "$candidate"
    rmdir "$lock" 2>/dev/null || :
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

bin_dir=$checkout/.bin
if [ -L "$bin_dir" ] || { [ -e "$bin_dir" ] && [ ! -d "$bin_dir" ]; }; then fail '.bin is occupied or symlinked'; fi
mkdir -p "$bin_dir"
# Recheck after obtaining the lock: a concurrent preparer may have completed.
if [ -e "$binary" ] || [ -L "$binary" ]; then
    identify_binary "$binary" || fail 'unidentified .bin/cw; refusing to overwrite it'
    if [ "$identified_revision" = "$revision" ]; then cleanup; trap - EXIT INT TERM; run_native "$@"; fi
fi
candidate=$(mktemp "$bin_dir/.cw-preparation.XXXXXXXX")

checksum() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"
    elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1"
    else return 1
    fi
}

download_release() {
    command -v curl >/dev/null 2>&1 && command -v tar >/dev/null 2>&1 || return 1
    command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1 || return 1
    tag=$(git -C "$checkout" tag --points-at "$revision" --sort=-version:refname | sed -n '/^v[0-9]/p' | sed -n '1p')
    case $tag in *[!A-Za-z0-9._-]*) tag= ;; esac
    if [ -z "$tag" ]; then
        # update fetches no tags. Query the canonical remote without adding any
        # local refs; only a lightweight tag's object can equal the commit SHA.
        remote_tags=$(GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=false git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=15 ls-remote --refs --tags "https://github.com/$repository.git" 'refs/tags/v*' 2>/dev/null) || remote_tags=
        tag=$(printf '%s\n' "$remote_tags" | while read -r remote_revision remote_ref remote_extra; do
            if [ "$remote_revision" != "$revision" ]; then continue; fi
            if [ -n "$remote_extra" ]; then continue; fi
            case $remote_ref in refs/tags/v*) remote_tag=${remote_ref#refs/tags/} ;; *) continue ;; esac
            case $remote_tag in *[!A-Za-z0-9._-]*) continue ;; esac
            printf '%s\n' "$remote_tag"
            break
        done)
    fi
    if [ -z "$tag" ]; then
        # Only use latest when its release metadata names this exact commit;
        # never install a newer snapshot if the requested release is absent.
        release=$(curl --fail --silent --show-error --location --proto '=https' --connect-timeout 10 --max-time 60 "https://api.github.com/repos/$repository/releases/latest" 2>/dev/null) || return 1
        release=$(printf '%s' "$release" | tr -d '\n')
        target=$(printf '%s\n' "$release" | sed -n 's/.*"target_commitish"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
        [ "$target" = "$revision" ] || return 1
        tag=$(printf '%s\n' "$release" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
        case $tag in v[0-9]* ) ;; *) return 1 ;; esac
        case $tag in *[!A-Za-z0-9._-]*) return 1 ;; esac
    fi
    temporary=$(mktemp -d "$bin_dir/.cw-download.XXXXXXXX")
    asset=cw_${target_os}_${target_arch}.tar.gz
    base=https://github.com/$repository/releases/download/$tag
    curl --fail --silent --show-error --location --proto '=https' --connect-timeout 10 --max-time 120 "$base/$asset" -o "$temporary/$asset" || return 1
    curl --fail --silent --show-error --location --proto '=https' --connect-timeout 10 --max-time 60 "$base/SHA256SUMS" -o "$temporary/SHA256SUMS" || return 1
    expected=$(sed -n "s/^\([0-9a-f]\{64\}\)  cw_${target_os}_${target_arch}\\.tar\\.gz\$/\1/p" "$temporary/SHA256SUMS")
    [ "${#expected}" -eq 64 ] || fail 'release checksum manifest is missing or duplicates the requested asset'
    actual=$(checksum "$temporary/$asset") || fail 'cannot calculate the release checksum'
    actual=${actual%% *}
    [ "$actual" = "$expected" ] || fail 'release archive checksum mismatch'
    # Write only the named binary to our own temporary path. No archive member
    # is extracted as a filesystem path, including links or traversal entries.
    tar -xOzf "$temporary/$asset" cw > "$candidate" || fail 'release archive has no readable cw binary'
    chmod 755 "$candidate"
    identify_binary "$candidate" || fail 'release asset is not an identifiable native cw binary'
    [ "$identified_revision" = "$revision" ] || fail 'release binary revision differs from source HEAD'
}

if download_release; then
    :
elif command -v go >/dev/null 2>&1; then
    built_at=$(git -C "$checkout" show -s --format=%cI "$revision")
    (cd "$checkout" && GOWORK=off GOTOOLCHAIN=go1.27.1 CGO_ENABLED=0 go build -mod=mod -trimpath -ldflags "-s -w -X main.version=dev -X main.revision=$revision -X main.builtAt=$built_at" -o "$candidate" ./cmd/cw) >/dev/null || fail 'native Go installer build failed'
    chmod 755 "$candidate"
    identify_binary "$candidate" || fail 'built installer is not an identifiable native cw binary'
    [ "$identified_revision" = "$revision" ] || fail 'built binary revision differs from source HEAD'
else
    fail 'no exact-revision native release is available; install Go 1.27.1 and rerun ./install.sh setup'
fi
mv -f "$candidate" "$binary"
candidate=
cleanup
trap - EXIT INT TERM
run_native "$@"
