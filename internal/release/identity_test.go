package release

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestNativePublicationIdentityRejectsBeforeAnyRequest(t *testing.T) {
	for _, scenario := range []string{"stale-version", "stale-revision", "plaintext", "missing-marker", "duplicate-marker", "wrong-target", "missing-cw", "duplicate-cw", "unsafe-path", "link-member"} {
		t.Run(scenario, func(t *testing.T) {
			fixture := newPublicationFixture(t)
			name := "cw_linux_amd64.tar.gz"
			executable, err := archiveExecutable(filepath.Join(fixture.options.Dist, name))
			if err != nil {
				t.Fatal(err)
			}
			entries := []testArchiveEntry{{name: "cw", kind: tar.TypeReg, mode: 0o755, data: executable}}
			switch scenario {
			case "stale-version":
				fixture.options.Version = "v1.0.9"
			case "stale-revision":
				writeTest(t, filepath.Join(fixture.options.Source, "README.md"), []byte("next exact source revision\n"))
				gitTest(t, fixture.options.Source, "add", "README.md")
				gitTest(t, fixture.options.Source, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "next")
				fixture.options.Revision = gitTest(t, fixture.options.Source, "rev-parse", "HEAD")
			case "plaintext":
				entries[0].data = []byte("not a native Go executable")
			case "missing-marker":
				entries[0].data = bytes.ReplaceAll(executable, []byte("CWRELEASE1|"), []byte("BWRELEASE1|"))
			case "duplicate-marker":
				_, stamp, err := SourceIdentity(t.Context(), fixture.options.Source, fixture.options.Revision, true)
				if err != nil {
					t.Fatal(err)
				}
				entries[0].data = append(bytes.Clone(executable), []byte(releaseMarker(fixture.options.Version, fixture.options.Revision, stamp, "linux", "amd64"))...)
			case "wrong-target":
				entries[0].data, err = archiveExecutable(filepath.Join(fixture.options.Dist, "cw_darwin_arm64.tar.gz"))
				if err != nil {
					t.Fatal(err)
				}
			case "missing-cw":
				entries = []testArchiveEntry{{name: "LICENSE", kind: tar.TypeReg, mode: 0o644, data: []byte("notice")}}
			case "duplicate-cw":
				entries = append(entries, entries[0])
			case "unsafe-path":
				entries = append(entries, testArchiveEntry{name: "licenses/../../outside", kind: tar.TypeReg, mode: 0o644, data: []byte("unsafe")})
			case "link-member":
				entries = append(entries, testArchiveEntry{name: "licenses/linked", kind: tar.TypeSymlink, mode: 0o644})
			}
			if scenario != "stale-version" && scenario != "stale-revision" {
				writeTest(t, filepath.Join(fixture.options.Dist, name), testArchive(t, entries))
				rewriteManifest(t, fixture.options.Dist)
			}
			if _, err := ValidateAssets(fixture.options.Dist); err != nil {
				t.Fatalf("scenario must have self-consistent checksums: %v", err)
			}
			requests := 0
			fixture.options.Client = &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
				requests++
				return nil, fmt.Errorf("unexpected publication request")
			})}
			if _, err := Publish(t.Context(), fixture.options); err == nil {
				t.Fatalf("invalid binary identity was accepted: %s", scenario)
			}
			if requests != 0 {
				t.Fatal("binary identity preflight contacted GitHub")
			}
		})
	}
}

type testArchiveEntry struct {
	name string
	kind byte
	mode int64
	data []byte
}

func testArchive(t *testing.T, entries []testArchiveEntry) []byte {
	t.Helper()
	var buffer bytes.Buffer
	zipped := gzip.NewWriter(&buffer)
	writer := tar.NewWriter(zipped)
	for _, entry := range entries {
		header := &tar.Header{Name: entry.name, Typeflag: entry.kind, Mode: entry.mode, Format: tar.FormatUSTAR}
		if entry.kind == tar.TypeReg {
			header.Size = int64(len(entry.data))
		}
		if entry.kind == tar.TypeSymlink {
			header.Linkname = "../../outside"
		}
		if err := writer.WriteHeader(header); err != nil {
			t.Fatal(err)
		}
		if entry.kind == tar.TypeReg {
			if _, err := writer.Write(entry.data); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	if err := zipped.Close(); err != nil {
		t.Fatal(err)
	}
	return buffer.Bytes()
}

func rewriteManifest(t *testing.T, directory string) {
	t.Helper()
	var manifest strings.Builder
	for _, name := range ArchiveNames {
		data, err := os.ReadFile(filepath.Join(directory, name))
		if err != nil {
			t.Fatal(err)
		}
		digest := sha256.Sum256(data)
		fmt.Fprintf(&manifest, "%s  %s\n", hex.EncodeToString(digest[:]), name)
	}
	writeTest(t, filepath.Join(directory, "SHA256SUMS"), []byte(manifest.String()))
}
