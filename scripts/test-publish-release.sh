#!/bin/sh
# Exercise the real publisher with isolated Git and filesystem-backed GitHub fixtures.
set -eu
root=$(CDPATH='' cd -P "$(dirname "$0")/.." && pwd)
publisher=$root/scripts/publish-release.sh
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir "$temporary/bin"
cat > "$temporary/bin/gh" <<'MOCK_GH'
#!/bin/sh
set -eu
: "${MOCK_GH_DIR:?}"
: "${MOCK_VERSION:?}"
: "${MOCK_REVISION:?}"
event() { printf '%s\n' "$1" >> "$MOCK_GH_DIR/events"; }
mutation() { event "$1"; printf '%s\n' "$1" >> "$MOCK_GH_DIR/mutations"; }
failure() { printf '%s\n' "Mock gh: $*" >&2; exit 1; }
uncertain() {
  if [ "$MOCK_SCENARIO" = "$1" ] && [ ! -f "$MOCK_GH_DIR/uncertain-$1" ]; then
    : > "$MOCK_GH_DIR/uncertain-$1"
    failure 'the response was lost after the operation completed'
  fi
}
command=$1
shift
if [ "$command" = api ]; then
  method=GET endpoint= query= ref= sha=
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --method|-X) method=$2; shift 2 ;;
      --jq) query=$2; shift 2 ;;
      -f) case "$2" in ref=*) ref=${2#ref=} ;; sha=*) sha=${2#sha=} ;; *) failure 'unexpected API field' ;; esac; shift 2 ;;
      repos/*) endpoint=$1; shift ;;
      *) failure "unexpected API argument: $1" ;;
    esac
  done
  case "$endpoint" in
    repos/belevtsev/codex-workflows/git/ref/tags/"$MOCK_VERSION")
      [ "$method" = GET ] || failure 'unexpected ref method'
      event tag.read
      [ -f "$MOCK_GH_DIR/tag" ] || failure 'tag was not found'
      if [ "$query" = '.object.sha' ]; then cat "$MOCK_GH_DIR/tag"
      else printf '{"object":{"sha":"%s","type":"commit"}}\n' "$(cat "$MOCK_GH_DIR/tag")"
      fi
      ;;
    repos/belevtsev/codex-workflows/git/refs)
      [ "$method" = POST ] && [ "$ref" = "refs/tags/$MOCK_VERSION" ] && [ "$sha" = "$MOCK_REVISION" ] || failure 'incorrect ref creation'
      [ ! -e "$MOCK_GH_DIR/tag" ] || failure 'ref already exists'
      mutation tag.create
      printf '%s\n' "$sha" > "$MOCK_GH_DIR/tag"
      uncertain tag-create
      printf '{}\n'
      ;;
    *) failure "unexpected API endpoint: $endpoint" ;;
  esac
  exit 0
fi
[ "$command" = release ] || failure "unexpected command: $command"
action=$1 version=$2
shift 2
[ "$version" = "$MOCK_VERSION" ] || failure 'incorrect release version'
asset= target= fields= query= pattern= destination= draft=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) [ "$2" = belevtsev/codex-workflows ] || failure 'incorrect repository'; shift 2 ;;
    --target) target=$2; shift 2 ;;
    --title|--notes) shift 2 ;;
    --draft) draft=true; shift ;;
    --draft=false) draft=false; shift ;;
    --json) fields=$2; shift 2 ;;
    --jq) query=$2; shift 2 ;;
    --pattern) pattern=$2; shift 2 ;;
    --dir) destination=$2; shift 2 ;;
    --*) failure "unexpected release option: $1" ;;
    *) [ -z "$asset" ] || failure 'unexpected extra asset'; asset=$1; shift ;;
  esac
done
case "$action" in
  view)
    event release.read
    [ -f "$MOCK_GH_DIR/release" ] || failure 'release was not found'
    if [ "$fields" = assets ]; then
      [ "$query" = '.assets[].name' ] || failure 'incorrect asset query'
      for file in "$MOCK_GH_DIR/assets/"*; do
        if [ -f "$file" ]; then basename "$file"; fi
      done
    elif [ "$fields" = url,tagName,isDraft ]; then
      printf '{"url":"https://example.invalid/release","tagName":"%s","isDraft":%s}\n' "$version" "$(cat "$MOCK_GH_DIR/release")"
    elif [ -z "$fields" ]; then printf 'Fixture release %s\n' "$version"
    else failure 'unexpected release fields'
    fi
    ;;
  create)
    [ ! -f "$MOCK_GH_DIR/release" ] && [ "$target" = "$MOCK_REVISION" ] && [ "$draft" = true ] || failure 'incorrect draft creation'
    # A draft can exist before its pending tag becomes a Git ref.
    mutation release.create
    printf 'true\n' > "$MOCK_GH_DIR/release"
    uncertain release-create
    ;;
  upload)
    [ -f "$MOCK_GH_DIR/release" ] && [ -f "$asset" ] || failure 'upload requires a release and asset'
    name=$(basename "$asset")
    [ ! -e "$MOCK_GH_DIR/assets/$name" ] || failure 'asset already exists'
    mutation "asset.upload:$name"
    if [ "$MOCK_SCENARIO" = upload-not-completed ]; then failure 'upload did not complete'; fi
    cp "$asset" "$MOCK_GH_DIR/assets/$name"
    uncertain upload
    ;;
  download)
    event "asset.download:$pattern"
    [ -f "$MOCK_GH_DIR/assets/$pattern" ] && [ -d "$destination" ] || failure 'requested asset does not exist'
    [ ! -e "$destination/$pattern" ] || failure 'download would overwrite an existing file'
    cp "$MOCK_GH_DIR/assets/$pattern" "$destination/$pattern"
    ;;
  edit)
    [ -f "$MOCK_GH_DIR/release" ] && [ "$draft" = false ] || failure 'incorrect publication'
    [ -f "$MOCK_GH_DIR/tag" ] && [ "$(cat "$MOCK_GH_DIR/tag")" = "$MOCK_REVISION" ] || failure 'publication requires the exact tag'
    mutation release.publish
    printf 'false\n' > "$MOCK_GH_DIR/release"
    ;;
  *) failure "unexpected release action: $action" ;;
esac
MOCK_GH
chmod 755 "$temporary/bin/gh"
PATH=$temporary/bin:$PATH
export PATH
unset GH_TOKEN GITHUB_TOKEN
assets='cw_darwin_arm64.tar.gz cw_darwin_amd64.tar.gz cw_linux_arm64.tar.gz cw_linux_amd64.tar.gz'
checks=0
fail() {
  printf '%s\n' "FAIL: $case_name: $*" >&2
  if [ -f "$fixture/stderr" ]; then cat "$fixture/stderr" >&2; fi
  exit 1
}
fixture() {
  case_name=$1
  fixture=$temporary/$case_name
  mkdir -p "$fixture/scripts" "$fixture/dist" "$fixture/github/assets"
  cp "$publisher" "$fixture/scripts/publish-release.sh"
  git -C "$fixture" init -q
  git -C "$fixture" -c user.name=fixture -c user.email=fixture@example.invalid add scripts
  git -C "$fixture" -c user.name=fixture -c user.email=fixture@example.invalid commit -qm fixture
  VERSION=v1.0.8
  REVISION=$(git -C "$fixture" rev-parse HEAD)
  MOCK_GH_DIR=$fixture/github
  MOCK_VERSION=$VERSION
  MOCK_REVISION=$REVISION
  MOCK_SCENARIO=normal
  export VERSION REVISION MOCK_GH_DIR MOCK_VERSION MOCK_REVISION MOCK_SCENARIO
  : > "$MOCK_GH_DIR/events"
  : > "$MOCK_GH_DIR/mutations"
  : > "$fixture/dist/SHA256SUMS"
  for name in $assets; do
    printf '%s\n' "Fixture archive for $name at $REVISION" > "$fixture/dist/$name"
    if command -v sha256sum >/dev/null 2>&1; then digest=$(sha256sum "$fixture/dist/$name")
    else digest=$(shasum -a 256 "$fixture/dist/$name")
    fi
    printf '%s  %s\n' "${digest%% *}" "$name" >> "$fixture/dist/SHA256SUMS"
  done
}
run_success() {
  if ! sh "$fixture/scripts/publish-release.sh" > "$fixture/stdout" 2> "$fixture/stderr"; then fail 'publisher unexpectedly failed'; fi
}
run_failure() {
  if sh "$fixture/scripts/publish-release.sh" > "$fixture/stdout" 2> "$fixture/stderr"; then fail 'publisher unexpectedly succeeded'; fi
}
count() { awk -v expected="$1" '$0 == expected { count++ } END { print count+0 }' "$MOCK_GH_DIR/events"; }
assert_count() { [ "$(count "$1")" -eq "$2" ] || fail "expected $2 occurrences of $1"; }
assert_no_mutation() { [ ! -s "$MOCK_GH_DIR/mutations" ] || fail 'failure changed mocked GitHub'; }
assert_published() {
  if [ "$(cat "$MOCK_GH_DIR/tag")" != "$REVISION" ] || [ "$(cat "$MOCK_GH_DIR/release")" != false ]; then
    fail 'release was not published at the exact SHA'
  fi
  for name in $assets SHA256SUMS; do
    cmp "$fixture/dist/$name" "$MOCK_GH_DIR/assets/$name" || fail "remote asset differs: $name"
  done
}
seed_remote() {
  printf '%s\n' "$REVISION" > "$MOCK_GH_DIR/tag"
  printf 'true\n' > "$MOCK_GH_DIR/release"
  for name in $assets SHA256SUMS; do cp "$fixture/dist/$name" "$MOCK_GH_DIR/assets/$name"; done
}
passed() { checks=$((checks+1)); printf '%s\n' "PASS: $case_name"; }

fixture fresh-draft
run_success
assert_published
assert_count tag.create 1
assert_count release.create 1
assert_count release.publish 1
[ "$(head -n 1 "$MOCK_GH_DIR/mutations")" = tag.create ] || fail 'draft was created before the immutable tag'
passed

for uncertain in tag-create release-create upload; do
  fixture "uncertain-$uncertain"
  MOCK_SCENARIO=$uncertain
  run_success
  assert_published
  assert_count tag.create 1
  assert_count release.create 1
  for name in $assets SHA256SUMS; do assert_count "asset.upload:$name" 1; done
  assert_count release.publish 1
  passed
done

for malformed in missing-archive missing-manifest checksum-mismatch duplicate-entry unknown-entry extra-archive symlink-archive symlink-manifest; do
  fixture "$malformed"
  case "$malformed" in
    missing-archive) rm "$fixture/dist/cw_linux_amd64.tar.gz" ;;
    missing-manifest) rm "$fixture/dist/SHA256SUMS" ;;
    checksum-mismatch) printf '%s\n' altered >> "$fixture/dist/cw_linux_arm64.tar.gz" ;;
    duplicate-entry) head -n 1 "$fixture/dist/SHA256SUMS" > "$fixture/entry"; cat "$fixture/entry" >> "$fixture/dist/SHA256SUMS" ;;
    unknown-entry) sed 's/cw_linux_amd64.tar.gz/unknown.tar.gz/' "$fixture/dist/SHA256SUMS" > "$fixture/sums"; mv "$fixture/sums" "$fixture/dist/SHA256SUMS" ;;
    extra-archive) cp "$fixture/dist/cw_linux_amd64.tar.gz" "$fixture/dist/cw_unknown_amd64.tar.gz" ;;
    symlink-archive) mv "$fixture/dist/cw_linux_amd64.tar.gz" "$fixture/archive"; ln -s ../archive "$fixture/dist/cw_linux_amd64.tar.gz" ;;
    symlink-manifest) mv "$fixture/dist/SHA256SUMS" "$fixture/sums"; ln -s ../sums "$fixture/dist/SHA256SUMS" ;;
  esac
  run_failure
  assert_no_mutation
  [ ! -s "$MOCK_GH_DIR/events" ] || fail 'local preflight called GitHub'
  passed
done

fixture exact-assets-idempotent
seed_remote
printf 'false\n' > "$MOCK_GH_DIR/release"
run_success
run_success
assert_published
assert_count tag.create 0
assert_count release.create 0
for name in $assets SHA256SUMS; do assert_count "asset.upload:$name" 0; done
assert_count release.publish 2
passed

fixture conflicting-existing-tag
printf '%040d\n' 0 > "$MOCK_GH_DIR/tag"
run_failure
assert_no_mutation
passed

fixture conflicting-existing-assets
seed_remote
for name in $assets SHA256SUMS; do printf '%s\n' conflict >> "$MOCK_GH_DIR/assets/$name"; done
run_failure
assert_no_mutation
assert_count release.publish 0
passed

fixture uncertain-upload-not-completed
MOCK_SCENARIO=upload-not-completed
run_failure
assert_count release.publish 0
uploads=$(awk '/^asset.upload:/ { count++ } END { print count+0 }' "$MOCK_GH_DIR/events")
[ "$uploads" -eq 1 ] || fail 'failed upload was retried'
passed

printf '%s\n' "$checks publisher fixture checks passed without network or credentials."
