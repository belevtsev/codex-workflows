package release

import (
	"bytes"
	json "encoding/json/v2"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync"
	"testing"
)

type publicationFixture struct {
	mu           sync.Mutex
	options      PublishOptions
	server       *httptest.Server
	tag          string
	remote       *remoteRelease
	assets       map[string][]byte
	ids          map[int64]string
	events       []string
	uncertain    string
	failed       bool
	uploadAbsent bool
	readStatus   int
	readPath     string
}

const fixtureMain = `package main
import "fmt"
var version, revision, builtAt, releaseIdentity string
func main() { fmt.Print(version, revision, builtAt, releaseIdentity) }
`

type compiledFixture struct {
	revision string
	files    map[string][]byte
	err      error
}

var compiledArchives func() compiledFixture
var fixtureCompile sync.Once

func newPublicationFixture(t *testing.T) *publicationFixture {
	t.Helper()
	source := t.TempDir()
	writeTest(t, filepath.Join(source, ".gitignore"), []byte("dist/\n"))
	writeTest(t, filepath.Join(source, "README.md"), []byte("Release fixture\n"))
	writeTest(t, filepath.Join(source, "go.mod"), []byte("module github.com/belevtsev/codex-workflows\n\ngo 1.27.1\n"))
	writeTest(t, filepath.Join(source, "cmd", "cw", "main.go"), []byte(fixtureMain))
	gitTest(t, source, "init", "-q")
	gitTest(t, source, "add", ".")
	gitTest(t, source, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
	revision := gitTest(t, source, "rev-parse", "HEAD")
	dist := filepath.Join(source, "dist")
	if err := os.Mkdir(dist, 0o755); err != nil {
		t.Fatal(err)
	}
	fixtureCompile.Do(func() {
		// The tiny four-platform manager fixture is compiled once per test
		// process, not once per publication scenario. All fixture Git commits
		// use identical files, author identity and dates, hence identical SHAs.
		compiledArchives = sync.OnceValue(func() compiledFixture {
			result := compiledFixture{revision: revision, files: make(map[string][]byte)}
			output := filepath.Join(t.TempDir(), "release")
			if _, err := Build(t.Context(), BuildOptions{Source: source, Version: "v1.0.8", Revision: revision, Dist: output}); err != nil {
				result.err = err
				return result
			}
			for _, name := range append(append([]string{}, ArchiveNames...), "SHA256SUMS") {
				result.files[name], result.err = os.ReadFile(filepath.Join(output, name))
				if result.err != nil {
					return result
				}
			}
			return result
		})
	})
	compiled := compiledArchives()
	if compiled.err != nil || compiled.revision != revision {
		t.Fatalf("native publication fixture: %v, revision %s != %s", compiled.err, compiled.revision, revision)
	}
	for name, data := range compiled.files {
		writeTest(t, filepath.Join(dist, name), data)
	}
	fixture := &publicationFixture{assets: make(map[string][]byte), ids: make(map[int64]string)}
	fixture.server = httptest.NewServer(http.HandlerFunc(fixture.serve))
	t.Cleanup(fixture.server.Close)
	fixture.options = PublishOptions{Source: source, Version: "v1.0.8", Revision: revision, Dist: dist, Token: "fixture-secret", APIURL: fixture.server.URL, Client: fixture.server.Client()}
	return fixture
}

func (fixture *publicationFixture) serve(writer http.ResponseWriter, request *http.Request) {
	fixture.mu.Lock()
	defer fixture.mu.Unlock()
	path := strings.TrimPrefix(request.URL.Path, "/repos/belevtsev/codex-workflows")
	if request.Header.Get("Authorization") != "Bearer fixture-secret" {
		http.Error(writer, "missing fixture authorization", http.StatusForbidden)
		return
	}
	if request.Method == http.MethodGet && fixture.readStatus != 0 && strings.HasPrefix(path, fixture.readPath) {
		http.Error(writer, "read unavailable", fixture.readStatus)
		return
	}
	respond := func(value any) {
		if err := json.MarshalWrite(writer, value); err != nil {
			panic(err)
		}
	}
	mutation := func(event string) bool {
		fixture.events = append(fixture.events, event)
		if fixture.uncertain == event && !fixture.failed {
			fixture.failed = true
			connection, _, err := writer.(http.Hijacker).Hijack()
			if err == nil {
				connection.Close()
			}
			return true
		}
		return false
	}
	switch {
	case request.Method == http.MethodGet && path == "/git/ref/tags/"+fixture.options.Version:
		if fixture.tag == "" {
			writer.WriteHeader(http.StatusNotFound)
			return
		}
		respond(map[string]any{"object": map[string]string{"sha": fixture.tag, "type": "commit"}})
	case request.Method == http.MethodPost && path == "/git/refs":
		var body map[string]string
		if err := json.UnmarshalRead(request.Body, &body); err != nil || fixture.tag != "" || body["ref"] != "refs/tags/"+fixture.options.Version || body["sha"] != fixture.options.Revision {
			http.Error(writer, "invalid tag creation", http.StatusUnprocessableEntity)
			return
		}
		fixture.tag = body["sha"]
		if !mutation("tag.create") {
			respond(map[string]any{})
		}
	case request.Method == http.MethodGet && path == "/releases":
		if fixture.remote == nil {
			respond([]remoteRelease{})
		} else {
			respond([]remoteRelease{*fixture.remote})
		}
	case request.Method == http.MethodPost && path == "/releases":
		var body map[string]any
		if err := json.UnmarshalRead(request.Body, &body); err != nil || fixture.remote != nil || fixture.tag != fixture.options.Revision || body["tag_name"] != fixture.options.Version || body["target_commitish"] != fixture.options.Revision || body["draft"] != true {
			http.Error(writer, "invalid draft creation", http.StatusUnprocessableEntity)
			return
		}
		fixture.remote = &remoteRelease{ID: 1, Tag: fixture.options.Version, Draft: true, UploadURL: fixture.server.URL + "/upload{?name,label}", URL: "https://example.invalid/release"}
		if !mutation("release.create") {
			respond(fixture.remote)
		}
	case request.Method == http.MethodGet && path == "/releases/1/assets":
		var assets []remoteAsset
		for id, name := range fixture.ids {
			assets = append(assets, remoteAsset{ID: id, Name: name, Size: int64(len(fixture.assets[name]))})
		}
		slices.SortFunc(assets, func(a, b remoteAsset) int { return strings.Compare(a.Name, b.Name) })
		respond(assets)
	case request.Method == http.MethodGet && strings.HasPrefix(path, "/releases/assets/"):
		id, _ := strconv.ParseInt(strings.TrimPrefix(path, "/releases/assets/"), 10, 64)
		name := fixture.ids[id]
		if name == "" {
			writer.WriteHeader(http.StatusNotFound)
			return
		}
		writer.Write(fixture.assets[name])
	case request.Method == http.MethodPost && request.URL.Path == "/upload":
		name := request.URL.Query().Get("name")
		if fixture.remote == nil || fixture.assets[name] != nil {
			http.Error(writer, "invalid upload", http.StatusUnprocessableEntity)
			return
		}
		data, _ := io.ReadAll(request.Body)
		if fixture.uploadAbsent {
			fixture.events = append(fixture.events, "asset.upload:"+name)
			http.Error(writer, "upload did not complete", http.StatusServiceUnavailable)
			return
		}
		fixture.assets[name] = data
		var id int64 = 1
		for fixture.ids[id] != "" {
			id++
		}
		fixture.ids[id] = name
		if !mutation("asset.upload:" + name) {
			respond(map[string]any{})
		}
	case request.Method == http.MethodPatch && path == "/releases/1":
		var body map[string]any
		if err := json.UnmarshalRead(request.Body, &body); err != nil || fixture.remote == nil || fixture.tag != fixture.options.Revision || body["draft"] != false || body["make_latest"] != "legacy" || len(fixture.assets) != 5 {
			http.Error(writer, "invalid publication", http.StatusUnprocessableEntity)
			return
		}
		fixture.remote.Draft = false
		if !mutation("release.publish") {
			respond(fixture.remote)
		}
	default:
		http.Error(writer, request.Method+" "+path, http.StatusNotFound)
	}
}

func (fixture *publicationFixture) seed(t *testing.T, draft bool) {
	t.Helper()
	fixture.tag = fixture.options.Revision
	fixture.remote = &remoteRelease{ID: 1, Tag: fixture.options.Version, Draft: draft, UploadURL: fixture.server.URL + "/upload{?name,label}", URL: "https://example.invalid/release"}
	for _, name := range append(append([]string{}, ArchiveNames...), "SHA256SUMS") {
		data, err := os.ReadFile(filepath.Join(fixture.options.Dist, name))
		if err != nil {
			t.Fatal(err)
		}
		fixture.assets[name] = data
		fixture.ids[int64(len(fixture.ids)+1)] = name
	}
}

func (fixture *publicationFixture) verify(t *testing.T) {
	t.Helper()
	if fixture.tag != fixture.options.Revision || fixture.remote == nil || fixture.remote.Draft {
		t.Fatal("release was not published at the exact SHA")
	}
	for name, remote := range fixture.assets {
		local, err := os.ReadFile(filepath.Join(fixture.options.Dist, name))
		if err != nil || !bytes.Equal(remote, local) {
			t.Fatalf("remote asset differs: %s: %v", name, err)
		}
	}
	if len(fixture.assets) != 5 {
		t.Fatalf("published %d assets, want five", len(fixture.assets))
	}
}

func TestPublishFreshAndUncertainOutcomes(t *testing.T) {
	for _, uncertain := range []string{"", "tag.create", "release.create", "asset.upload:cw_darwin_arm64.tar.gz", "release.publish"} {
		t.Run("uncertain_"+uncertain, func(t *testing.T) {
			fixture := newPublicationFixture(t)
			fixture.uncertain = uncertain
			publication, err := Publish(t.Context(), fixture.options)
			if err != nil {
				t.Fatal(err)
			}
			if !publication.Changed {
				t.Fatal("fresh publication should report a change")
			}
			fixture.verify(t)
			if fixture.events[0] != "tag.create" {
				t.Fatal("draft created before the exact Git tag")
			}
			counts := make(map[string]int)
			for _, event := range fixture.events {
				counts[event]++
			}
			for event, count := range counts {
				if count != 1 {
					t.Fatalf("mutation retried: %s: %d", event, count)
				}
			}
		})
	}
}

func TestPublishLocalPreflightNeverContactsGitHub(t *testing.T) {
	for _, malformed := range []string{"missing-archive", "missing-manifest", "checksum-mismatch", "duplicate-entry", "unknown-entry", "extra-archive", "symlink-archive", "symlink-manifest"} {
		t.Run(malformed, func(t *testing.T) {
			fixture := newPublicationFixture(t)
			manifest := filepath.Join(fixture.options.Dist, "SHA256SUMS")
			archive := filepath.Join(fixture.options.Dist, "cw_linux_amd64.tar.gz")
			data, err := os.ReadFile(manifest)
			if err != nil {
				t.Fatal(err)
			}
			switch malformed {
			case "missing-archive":
				err = os.Remove(archive)
			case "missing-manifest":
				err = os.Remove(manifest)
			case "checksum-mismatch":
				writeTest(t, archive, []byte("changed"))
			case "duplicate-entry":
				first, _, _ := strings.Cut(string(data), "\n")
				writeTest(t, manifest, append(data, []byte(first+"\n")...))
			case "unknown-entry":
				writeTest(t, manifest, bytes.ReplaceAll(data, []byte("cw_linux_amd64.tar.gz"), []byte("unknown.tar.gz")))
			case "extra-archive":
				writeTest(t, filepath.Join(fixture.options.Dist, "cw_unknown_amd64.tar.gz"), []byte("unexpected"))
			case "symlink-archive", "symlink-manifest":
				path := archive
				if malformed == "symlink-manifest" {
					path = manifest
				}
				err = os.Remove(path)
				if err == nil {
					err = os.Symlink("/outside", path)
				}
			}
			if err != nil {
				t.Fatal(err)
			}
			// A transport that records any request proves local validation runs
			// before both reads and writes.
			requests := 0
			fixture.options.Client = &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
				requests++
				return nil, fmt.Errorf("unexpected network request")
			})}
			if _, err := Publish(t.Context(), fixture.options); err == nil {
				t.Fatal("malformed local release accepted")
			}
			if requests != 0 {
				t.Fatal("local preflight contacted GitHub")
			}
		})
	}
}

func TestPublishExactReleaseHasZeroWrites(t *testing.T) {
	fixture := newPublicationFixture(t)
	fixture.seed(t, false)
	for range 2 {
		result, err := Publish(t.Context(), fixture.options)
		if err != nil || result.Changed {
			t.Fatalf("completed publication must be a verified no-op: %v, %v", result, err)
		}
	}
	fixture.verify(t)
	if len(fixture.events) != 0 {
		t.Fatalf("already-public release mutated: %v", fixture.events)
	}
}

func TestPublishResumesPendingDraftWithMissingTagAndAsset(t *testing.T) {
	fixture := newPublicationFixture(t)
	fixture.seed(t, true)
	fixture.tag = ""
	delete(fixture.assets, ArchiveNames[0])
	delete(fixture.ids, 1)
	if _, err := Publish(t.Context(), fixture.options); err != nil {
		t.Fatal(err)
	}
	fixture.verify(t)
	if !slices.Equal(fixture.events, []string{"tag.create", "asset.upload:" + ArchiveNames[0], "release.publish"}) {
		t.Fatalf("draft reconciliation repeated completed work: %v", fixture.events)
	}
}

func TestPublishConflictsAndIncompleteUploads(t *testing.T) {
	for _, scenario := range []string{"tag-conflict", "asset-conflict", "partial-asset-conflict", "upload-not-completed", "published-incomplete"} {
		t.Run(scenario, func(t *testing.T) {
			fixture := newPublicationFixture(t)
			switch scenario {
			case "tag-conflict":
				fixture.tag = strings.Repeat("0", 40)
			case "asset-conflict", "partial-asset-conflict":
				fixture.seed(t, true)
				name := "cw_linux_amd64.tar.gz"
				fixture.assets[name] = append(fixture.assets[name], 'x')
				if scenario == "partial-asset-conflict" {
					delete(fixture.assets, ArchiveNames[0])
					for id, name := range fixture.ids {
						if name == ArchiveNames[0] {
							delete(fixture.ids, id)
						}
					}
				}
			case "upload-not-completed":
				fixture.uploadAbsent = true
			case "published-incomplete":
				fixture.seed(t, false)
				delete(fixture.assets, ArchiveNames[0])
				delete(fixture.ids, 1)
			}
			if _, err := Publish(t.Context(), fixture.options); err == nil {
				t.Fatal("conflicting or incomplete publication accepted")
			}
			if scenario == "upload-not-completed" {
				if !slices.Equal(fixture.events, []string{"tag.create", "release.create", "asset.upload:" + ArchiveNames[0]}) {
					t.Fatalf("failed upload retried or published: %v", fixture.events)
				}
			} else if len(fixture.events) != 0 {
				t.Fatalf("preflight failure mutated GitHub: %v", fixture.events)
			}
		})
	}
}

func TestPublishReadErrorsNeverAuthorizeMutation(t *testing.T) {
	for _, path := range []string{"/git/ref", "/releases"} {
		for _, status := range []int{http.StatusForbidden, http.StatusInternalServerError} {
			t.Run(fmt.Sprintf("%s_%d", path, status), func(t *testing.T) {
				fixture := newPublicationFixture(t)
				fixture.readPath, fixture.readStatus = path, status
				if _, err := Publish(t.Context(), fixture.options); err == nil {
					t.Fatal("read failure accepted")
				}
				if len(fixture.events) != 0 {
					t.Fatalf("read failure authorized mutations: %v", fixture.events)
				}
			})
		}
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (function roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return function(request)
}

func writeTest(t *testing.T, path string, contents []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, contents, 0o644); err != nil {
		t.Fatal(err)
	}
}

func gitTest(t *testing.T, source string, arguments ...string) string {
	t.Helper()
	command := exec.CommandContext(t.Context(), "git", append([]string{"-C", source}, arguments...)...)
	command.Env = environment(map[string]string{"GIT_CONFIG_GLOBAL": os.DevNull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_AUTHOR_DATE": "2023-11-14T22:13:20+0000", "GIT_COMMITTER_DATE": "2023-11-14T22:13:20+0000"})
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v\n%s", arguments, err, output)
	}
	return strings.TrimSpace(string(output))
}
