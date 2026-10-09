#!/bin/sh
# Immutable assets: reconcile uncertain outcomes before any retry.
set -eu
: "${VERSION:?VERSION is required}"
: "${REVISION:?REVISION is required}"
repo=belevtsev/codex-workflows
root=$(CDPATH='' cd -P "$(dirname "$0")/.." && pwd)
cd "$root"
printf '%s\n' "$VERSION" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$' || { printf '%s\n' 'Invalid release version' >&2; exit 1; }
[ "$(git rev-parse HEAD)" = "$REVISION" ] || { printf '%s\n' 'Release source revision mismatch' >&2; exit 1; }
assets='cw_darwin_arm64.tar.gz cw_darwin_amd64.tar.gz cw_linux_arm64.tar.gz cw_linux_amd64.tar.gz'
if [ ! -f dist/SHA256SUMS ] || [ -L dist/SHA256SUMS ]; then
  printf '%s\n' 'Missing regular checksum manifest' >&2
  exit 1
fi
awk '
  NF != 2 || length($1) != 64 || $1 ~ /[^0-9a-f]/ { exit 1 }
  $2 !~ /^cw_(darwin|linux)_(arm64|amd64)\.tar\.gz$/ || seen[$2]++ { exit 1 }
  END { if (NR != 4) exit 1 }
' dist/SHA256SUMS || { printf '%s\n' 'Checksum manifest must cover exactly four native archives' >&2; exit 1; }
for asset in dist/cw_*.tar.gz; do
  case " $assets " in *" $(basename "$asset") "*) ;; *) printf '%s\n' 'Unexpected native release archive' >&2; exit 1;; esac
done
for name in $assets; do
  asset=dist/$name
  if [ ! -f "$asset" ] || [ -L "$asset" ]; then
    printf '%s\n' "Missing regular release archive: $name" >&2
    exit 1
  fi
  expected=$(awk -v name="$name" '$2 == name { print $1 }' dist/SHA256SUMS)
  if command -v sha256sum >/dev/null 2>&1; then actual=$(sha256sum "$asset")
  elif command -v shasum >/dev/null 2>&1; then actual=$(shasum -a 256 "$asset")
  else printf '%s\n' 'sha256sum or shasum is required' >&2; exit 1
  fi
  [ "${actual%% *}" = "$expected" ] || { printf '%s\n' "Local release checksum differs: $name" >&2; exit 1; }
done
verify_tag() {
  tag_sha=$(gh api "repos/$repo/git/ref/tags/$VERSION" --jq '.object.sha')
  [ "$tag_sha" = "$REVISION" ] || { printf '%s\n' 'Existing release tag points to another revision' >&2; exit 1; }
}
# Draft releases can have a pending tag. Establish the immutable Git ref first.
if ! gh api "repos/$repo/git/ref/tags/$VERSION" >/dev/null 2>&1; then
  if ! gh api --method POST "repos/$repo/git/refs" \
      -f "ref=refs/tags/$VERSION" -f "sha=$REVISION" >/dev/null; then
    # A response failure may follow a completed create; verify instead of retrying.
    verify_tag
  fi
fi
verify_tag
if ! gh release view "$VERSION" --repo "$repo" >/dev/null 2>&1; then
  if ! gh release create "$VERSION" --repo "$repo" --target "$REVISION" --draft \
      --title "Codex workflows $VERSION" --notes "Native cw for macOS/Linux on AMD64 and ARM64. Source revision: $REVISION. SHA256SUMS verifies each archive."; then
    gh release view "$VERSION" --repo "$repo" >/dev/null
  fi
fi
verify_tag
verification=$(mktemp -d)
trap 'rm -rf "$verification"' EXIT HUP INT TERM
for name in $assets SHA256SUMS; do
  asset=dist/$name
  remote_names=$(gh release view "$VERSION" --repo "$repo" --json assets --jq '.assets[].name')
  if ! printf '%s\n' "$remote_names" | grep -Fx "$name" >/dev/null; then
    if ! gh release upload "$VERSION" "$asset" --repo "$repo"; then
      # The upload may have completed despite its response. Read it back once.
      gh release download "$VERSION" --repo "$repo" --pattern "$name" --dir "$verification"
    fi
  fi
  if [ ! -f "$verification/$name" ]; then
    gh release download "$VERSION" --repo "$repo" --pattern "$name" --dir "$verification"
  fi
  cmp "$asset" "$verification/$name" || { printf '%s\n' "Remote release asset differs: $name" >&2; exit 1; }
done
verify_tag
gh release edit "$VERSION" --repo "$repo" --draft=false
gh release view "$VERSION" --repo "$repo" --json url,tagName,isDraft
