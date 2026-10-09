package manageruntime

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	json "encoding/json/v2"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

const fixtureSHA = "0123456789012345678901234567890123456789"

func realTemp(t *testing.T) string {
	t.Helper()
	path, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	return path
}
func archiveFixture(t *testing.T, headers []tar.Header, bodies []string) []byte {
	t.Helper()
	out := new(bytes.Buffer)
	zip := gzip.NewWriter(out)
	archive := tar.NewWriter(zip)
	for index, header := range headers {
		header.Size = int64(len(bodies[index]))
		if err := archive.WriteHeader(&header); err != nil {
			t.Fatal(err)
		}
		if _, err := archive.Write([]byte(bodies[index])); err != nil {
			t.Fatal(err)
		}
	}
	if err := archive.Close(); err != nil {
		t.Fatal(err)
	}
	if err := zip.Close(); err != nil {
		t.Fatal(err)
	}
	return out.Bytes()
}
func TestExactReleaseChecksumAndAtomicCache(t *testing.T) {
	archive := archiveFixture(t, []tar.Header{{Name: "cw", Typeflag: tar.TypeReg, Mode: 0755}}, []string{"fixture-manager"})
	digest := sha256.Sum256(archive)
	asset := "cw_" + runtime.GOOS + "_" + runtime.GOARCH + ".tar.gz"
	downloads := 0
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/releases":
			fmt.Fprintf(w, `[{"tag_name":"v1.2.3","target_commitish":"%s"}]`, fixtureSHA)
		case "/download/v1.2.3/SHA256SUMS":
			fmt.Fprintf(w, "%s  %s\n", hex.EncodeToString(digest[:]), asset)
		case "/download/v1.2.3/" + asset:
			downloads++
			_, _ = w.Write(archive)
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	root := realTemp(t)
	acquirer := Acquirer{Client: server.Client(), APIBase: server.URL + "/api", DownloadBase: server.URL + "/download", Inspect: func(_ context.Context, path string) (Candidate, error) {
		data, err := os.ReadFile(path)
		if err != nil {
			return Candidate{}, err
		}
		if string(data) != "fixture-manager" {
			return Candidate{}, errors.New("invalid fixture")
		}
		return Candidate{Path: path, Revision: fixtureSHA, Version: "v1.2.3", OS: runtime.GOOS, Arch: runtime.GOARCH}, nil
	}, Build: func(context.Context, string, string, string) error { t.Fatal("release used Go build"); return nil }}
	first, err := acquirer.Prepare(t.Context(), root, fixtureSHA, root)
	if err != nil {
		t.Fatal(err)
	}
	second, err := acquirer.Prepare(t.Context(), root, fixtureSHA, root)
	if err != nil {
		t.Fatal(err)
	}
	if first.Path != second.Path || downloads != 1 {
		t.Fatalf("not cached: %v %v downloads=%d", first, second, downloads)
	}
	if _, err := os.Lstat(filepath.Join(root, "runtime", "current")); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("acquisition activated a runtime pointer")
	}
}
func TestChecksumMismatchNeverBuildsOrPublishes(t *testing.T) {
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/releases") {
			fmt.Fprintf(w, `[{"tag_name":"v1.2.3","target_commitish":"%s"}]`, fixtureSHA)
		} else if strings.HasSuffix(r.URL.Path, "SHA256SUMS") {
			fmt.Fprintf(w, "%s  cw_%s_%s.tar.gz\n", strings.Repeat("0", 64), runtime.GOOS, runtime.GOARCH)
		} else {
			_, _ = w.Write([]byte("altered"))
		}
	}))
	defer server.Close()
	root := realTemp(t)
	a := Acquirer{Client: server.Client(), APIBase: server.URL, DownloadBase: server.URL, Build: func(context.Context, string, string, string) error {
		t.Fatal("integrity failure fell back to build")
		return nil
	}}
	_, err := a.Prepare(t.Context(), root, fixtureSHA, root)
	if err == nil || !strings.Contains(err.Error(), "checksum mismatch") {
		t.Fatalf("%v", err)
	}
	if _, err = os.Stat(filepath.Join(root, "runtime", "candidates", fixtureSHA, "cw")); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("invalid candidate published")
	}
}
func TestArchiveRejectsLinksDuplicateAndMissingBinary(t *testing.T) {
	cases := []struct {
		name    string
		headers []tar.Header
		bodies  []string
	}{{"link", []tar.Header{{Name: "cw", Typeflag: tar.TypeSymlink, Linkname: "../victim"}}, []string{""}}, {"duplicate", []tar.Header{{Name: "cw", Typeflag: tar.TypeReg}, {Name: "cw", Typeflag: tar.TypeReg}}, []string{"one", "two"}}, {"missing", []tar.Header{{Name: "other", Typeflag: tar.TypeReg}}, []string{"other"}}}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			err := extractBinary(archiveFixture(t, test.headers, test.bodies), filepath.Join(t.TempDir(), "cw"))
			if err == nil {
				t.Fatal("invalid archive accepted")
			}
		})
	}
}
func TestResolveInstalledLocatorThroughNativeLink(t *testing.T) {
	root := realTemp(t)
	runtimeRoot := filepath.Join(root, "runtime")
	releaseRoot := filepath.Join(runtimeRoot, "releases", fixtureSHA)
	if err := os.MkdirAll(releaseRoot, 0755); err != nil {
		t.Fatal(err)
	}
	binary := filepath.Join(releaseRoot, "cw")
	if err := os.WriteFile(binary, []byte("fixture"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(releaseRoot, filepath.Join(runtimeRoot, "current")); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(root, "cw")
	if err := os.Symlink(filepath.Join(runtimeRoot, "current", "cw"), link); err != nil {
		t.Fatal(err)
	}
	locator := Locator{Source: filepath.Join(root, "source"), Home: root, Codex: filepath.Join(root, "codex"), State: root}
	data, err := json.Marshal(locator)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(runtimeRoot, "locator.json"), data, 0600); err != nil {
		t.Fatal(err)
	}
	got, err := Resolve(link)
	if err != nil {
		t.Fatal(err)
	}
	if got != locator {
		t.Fatalf("got %+v", got)
	}
	locator.State = filepath.Join(root, "different")
	data, _ = json.Marshal(locator)
	if err = os.WriteFile(filepath.Join(runtimeRoot, "locator.json"), data, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = Resolve(link); err == nil {
		t.Fatal("cross-installation locator accepted")
	}
}
func TestResolveNeverSearchesDeveloperAncestors(t *testing.T) {
	root := realTemp(t)
	binary := filepath.Join(root, "cw")
	if err := os.WriteFile(binary, []byte("fixture"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "locator.json"), []byte("broken"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := Resolve(binary); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("unexpected developer locator resolution: %v", err)
	}
}
func TestSecureDirectoriesRefuseSymlink(t *testing.T) {
	root := realTemp(t)
	if err := os.Symlink(t.TempDir(), filepath.Join(root, "runtime")); err != nil {
		t.Fatal(err)
	}
	_, err := (Acquirer{}).Prepare(t.Context(), root, fixtureSHA, root)
	if err == nil || !strings.Contains(err.Error(), "unsafe manager directory") {
		t.Fatalf("%v", err)
	}
}
func TestFetchRequiresHTTPSAndBoundsResponse(t *testing.T) {
	if _, err := (Acquirer{}).fetch(t.Context(), "http://example.test/file", 10); err == nil {
		t.Fatal("HTTP accepted")
	}
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { _, _ = w.Write([]byte("too-large")) }))
	defer server.Close()
	if _, err := (Acquirer{Client: server.Client()}).fetch(t.Context(), server.URL, 3); err == nil {
		t.Fatal("unbounded response accepted")
	}
}

func gitFixture(t *testing.T, root string, args ...string) string {
	t.Helper()
	command := exec.CommandContext(t.Context(), "git", append([]string{"-C", root}, args...)...)
	data, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v: %s", args, err, data)
	}
	return strings.TrimSpace(string(data))
}
func TestGoFallbackBuildsExactSnapshotWithoutMovingHEAD(t *testing.T) {
	root := realTemp(t)
	source := filepath.Join(root, "source with spaces")
	if err := os.Mkdir(source, 0755); err != nil {
		t.Fatal(err)
	}
	gitFixture(t, source, "init", "--quiet")
	gitFixture(t, source, "config", "user.name", "Fixture")
	gitFixture(t, source, "config", "user.email", "fixture@example.test")
	writeFixture(t, filepath.Join(source, "go.mod"), "module example.test/fixture\n\ngo 1.27.1\n", 0644)
	writeFixture(t, filepath.Join(source, "snapshot"), "target", 0644)
	gitFixture(t, source, "add", ".")
	gitFixture(t, source, "commit", "--quiet", "-m", "target")
	target := gitFixture(t, source, "rev-parse", "HEAD")
	writeFixture(t, filepath.Join(source, "snapshot"), "later", 0644)
	gitFixture(t, source, "add", ".")
	gitFixture(t, source, "commit", "--quiet", "-m", "later")
	head := gitFixture(t, source, "rev-parse", "HEAD")
	mockBin := filepath.Join(root, "mock-bin")
	if err := os.Mkdir(mockBin, 0755); err != nil {
		t.Fatal(err)
	}
	record := filepath.Join(root, "build-record")
	writeFixture(t, filepath.Join(mockBin, "go"), `#!/bin/sh
set -eu
[ "$GOWORK" = off ]
[ "$GOTOOLCHAIN" = go1.27.1 ]
[ "$CGO_ENABLED" = 0 ]
[ "$(cat snapshot)" = target ]
printf '%s\n' "$@" > "$CW_BUILD_RECORD"
next=false
output=
for argument in "$@"; do
 if "$next"; then output=$argument; next=false; continue; fi
 if [ "$argument" = -o ]; then next=true; fi
done
printf '%s\n' fixture > "$output"
`, 0755)
	t.Setenv("PATH", mockBin+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("CW_BUILD_RECORD", record)
	output := filepath.Join(root, "candidate with spaces")
	if err := buildSource(t.Context(), source, target, output); err != nil {
		t.Fatal(err)
	}
	if got := gitFixture(t, source, "rev-parse", "HEAD"); got != head {
		t.Fatal("build moved source HEAD")
	}
	argv, err := os.ReadFile(record)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(argv), "-X main.revision="+target) || !strings.Contains(string(argv), "\n"+output+"\n") {
		t.Fatalf("build did not preserve exact SHA and path arguments: %s", argv)
	}
	writeFixture(t, filepath.Join(source, "snapshot"), "dirty", 0644)
	if err := buildSource(t.Context(), source, target, filepath.Join(root, "dirty-candidate")); err == nil || !strings.Contains(err.Error(), "dirty") {
		t.Fatalf("dirty source accepted: %v", err)
	}
}

func TestInspectRejectsWrongProtocolAndPreservesCancellation(t *testing.T) {
	for _, test := range []struct{ name, output string }{{"unknown member", fmt.Sprintf(`{"arch":"%s","built_at":"now","os":"%s","revision":"%s","version":"v1.2.3","extra":true}`, runtime.GOARCH, runtime.GOOS, fixtureSHA)}, {"wrong platform", fmt.Sprintf(`{"arch":"wrong","built_at":"now","os":"%s","revision":"%s","version":"v1.2.3"}`, runtime.GOOS, fixtureSHA)}, {"unbounded output", strings.Repeat("x", 8192)}} {
		t.Run(test.name, func(t *testing.T) {
			path := filepath.Join(realTemp(t), "cw")
			writeFixture(t, path, "#!/bin/sh\nprintf '%s\\n' '"+test.output+"'\n", 0755)
			if _, err := Inspect(t.Context(), path); err == nil {
				t.Fatal("invalid executable protocol accepted")
			}
		})
	}
	path := filepath.Join(realTemp(t), "cw")
	writeFixture(t, path, managerScript(true), 0755)
	identity, err := Inspect(t.Context(), path)
	if err != nil {
		t.Fatal(err)
	}
	if identity.Revision != fixtureSHA {
		t.Fatalf("wrong identity: %+v", identity)
	}
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	if _, err := Inspect(ctx, path); !errors.Is(err, context.Canceled) {
		t.Fatalf("cancellation lost: %v", err)
	}
}

func TestResolveImmutableReleaseLocatorAfterActiveLocatorRemoved(t *testing.T) {
	root := realTemp(t)
	runtimeRoot := filepath.Join(root, "runtime")
	releaseRoot := filepath.Join(runtimeRoot, "releases", fixtureSHA)
	if err := os.MkdirAll(releaseRoot, 0755); err != nil {
		t.Fatal(err)
	}
	binary := filepath.Join(releaseRoot, "cw")
	writeFixture(t, binary, managerScript(true), 0755)
	locator := Locator{Source: filepath.Join(root, "source"), Home: root, Codex: filepath.Join(root, "codex"), State: root}
	data, err := json.Marshal(locator)
	if err != nil {
		t.Fatal(err)
	}
	releaseLocator := filepath.Join(releaseRoot, "locator.json")
	if err = os.WriteFile(releaseLocator, data, 0600); err != nil {
		t.Fatal(err)
	}
	got, err := Resolve(binary)
	if err != nil {
		t.Fatal(err)
	}
	if got != locator {
		t.Fatalf("wrong recovery roots: %+v", got)
	}
	primary := filepath.Join(runtimeRoot, "locator.json")
	writeFixture(t, primary, "malformed", 0600)
	if _, err = Resolve(binary); err == nil || errors.Is(err, ErrLocatorMissing) {
		t.Fatalf("malformed primary fell back: %v", err)
	}
	if err = os.Remove(primary); err != nil {
		t.Fatal(err)
	}
	if err = os.Remove(releaseLocator); err != nil {
		t.Fatal(err)
	}
	if _, err = Resolve(binary); !errors.Is(err, ErrLocatorMissing) {
		t.Fatalf("owned layout without descriptors did not require explicit roots: %v", err)
	}
}
