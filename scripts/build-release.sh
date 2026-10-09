#!/bin/sh
# Build all standalone native cw release assets from one exact source commit.
set -eu

checkout=$(CDPATH='' cd -P "$(dirname "$0")/.." && pwd)
cd "$checkout"
version=${1:-${VERSION:-}}
revision=${2:-${REVISION:-$(git rev-parse --verify HEAD)}}
if [ -z "$version" ]; then printf '%s\n' 'usage: scripts/build-release.sh VERSION [REVISION]' >&2; exit 1; fi
case $version in *[!A-Za-z0-9._+-]*|'') printf '%s\n' 'invalid release version' >&2; exit 1 ;; esac
case $revision in *[!0-9a-f]*|'') printf '%s\n' 'invalid release revision' >&2; exit 1 ;; esac
if [ "${#revision}" -ne 40 ] || [ "$revision" != "$(git rev-parse --verify HEAD)" ]; then
    printf '%s\n' 'release revision must equal source HEAD' >&2
    exit 1
fi
dirty=$(GIT_OPTIONAL_LOCKS=0 git status --porcelain --untracked-files=normal)
[ -z "$dirty" ] || { printf '%s\n' 'release builds require a clean source checkout' >&2; exit 1; }
command -v go >/dev/null 2>&1 || { printf '%s\n' 'Go 1.27.1 is required' >&2; exit 1; }
if [ -n "${BUILT_AT:-}" ]; then built_at=$BUILT_AT
elif [ -n "${SOURCE_DATE_EPOCH:-}" ]; then
    built_at=$(date -u -d "@$SOURCE_DATE_EPOCH" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null) || built_at=$(date -u -r "$SOURCE_DATE_EPOCH" '+%Y-%m-%dT%H:%M:%SZ')
else built_at=$(git show -s --format=%cI "$revision")
fi
case $built_at in *[!A-Za-z0-9:+.-]*|'') printf '%s\n' 'invalid build timestamp' >&2; exit 1 ;; esac

dist=$checkout/dist
if [ -L "$dist" ] || { [ -e "$dist" ] && [ ! -d "$dist" ]; }; then printf '%s\n' 'dist is occupied or symlinked' >&2; exit 1; fi
mkdir -p "$dist"
temporary=$(mktemp -d "$dist/.release.XXXXXXXX")
trap 'rm -rf "$temporary"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
checksum_manifest=$temporary/SHA256SUMS
: > "$checksum_manifest"

for target_os in darwin linux; do
    for target_arch in arm64 amd64; do
        stage=$temporary/${target_os}_${target_arch}
        mkdir "$stage"
        GOWORK=off GOTOOLCHAIN=go1.27.1 CGO_ENABLED=0 GOOS=$target_os GOARCH=$target_arch go build -mod=mod -trimpath -ldflags "-s -w -X main.version=$version -X main.revision=$revision -X main.builtAt=$built_at" -o "$stage/cw" ./cmd/cw
        chmod 755 "$stage/cw"
        set -- cw
        for document in LICENSE THIRD_PARTY.md; do
            if [ -f "$checkout/$document" ]; then cp "$checkout/$document" "$stage/$document"; chmod 644 "$stage/$document"; set -- "$@" "$document"; fi
        done
        if [ -d "$checkout/licenses" ]; then
            cp -R "$checkout/licenses" "$stage/licenses"
            set -- "$@" licenses
        fi
        asset=cw_${target_os}_${target_arch}.tar.gz
        # CI uses GNU tar: fix archive ownership/timestamps and suppress gzip's
        # timestamp so rerunning this release for the same commit is stable.
        tar_version=$(tar --version 2>/dev/null) || tar_version=
        case $tar_version in *'GNU tar'*)
            epoch=$(git show -s --format=%ct "$revision")
            tar --format=ustar --sort=name --mtime="@$epoch" --owner=0 --group=0 --numeric-owner -cf "$temporary/$asset.tar" -C "$stage" "$@"
            ;;
        *) tar -cf "$temporary/$asset.tar" -C "$stage" "$@" ;;
        esac
        gzip -n -c "$temporary/$asset.tar" > "$temporary/$asset"
        if command -v sha256sum >/dev/null 2>&1; then digest=$(sha256sum "$temporary/$asset")
        elif command -v shasum >/dev/null 2>&1; then digest=$(shasum -a 256 "$temporary/$asset")
        else printf '%s\n' 'sha256sum or shasum is required' >&2; exit 1
        fi
        digest=${digest%% *}
        printf '%s  %s\n' "$digest" "$asset" >> "$checksum_manifest"
    done
done
for asset in cw_darwin_arm64.tar.gz cw_darwin_amd64.tar.gz cw_linux_arm64.tar.gz cw_linux_amd64.tar.gz SHA256SUMS; do
    mv -f "$temporary/$asset" "$dist/$asset"
done
printf '%s\n' "Native cw release assets built for $version at $revision in $dist"
