package release

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestArchiveIsDeterministicAndIncludesNotices(t *testing.T) {
	root := t.TempDir()
	stage := filepath.Join(root, "stage")
	source := filepath.Join(root, "source")
	writeTest(t, filepath.Join(stage, "cw"), []byte("native executable"))
	writeTest(t, filepath.Join(source, "LICENSE"), []byte("repository notice"))
	writeTest(t, filepath.Join(source, "THIRD_PARTY.md"), []byte("provenance"))
	writeTest(t, filepath.Join(source, "licenses", "dependency.txt"), []byte("dependency notice"))
	stamp := time.Unix(1700000000, 0).UTC()
	first, second := filepath.Join(root, "first.gz"), filepath.Join(root, "second.gz")
	if err := archive(first, stage, source, stamp); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(filepath.Join(stage, "cw"), time.Now(), time.Now()); err != nil {
		t.Fatal(err)
	}
	if err := archive(second, stage, source, stamp); err != nil {
		t.Fatal(err)
	}
	a, err := os.ReadFile(first)
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(second)
	if err != nil || !bytes.Equal(a, b) {
		t.Fatalf("archive depends on filesystem timestamps: %v", err)
	}
	zipped, err := gzip.NewReader(bytes.NewReader(a))
	if err != nil {
		t.Fatal(err)
	}
	defer zipped.Close()
	reader := tar.NewReader(zipped)
	want := []string{"LICENSE", "THIRD_PARTY.md", "cw", "licenses/", "licenses/dependency.txt"}
	for _, name := range want {
		header, err := reader.Next()
		if err != nil {
			t.Fatal(err)
		}
		if header.Name != name || header.Uid != 0 || header.Gid != 0 || !header.ModTime.Equal(stamp) {
			t.Fatalf("unexpected normalized archive entry: %#v", header)
		}
		if name == "cw" && header.Mode != 0o755 {
			t.Fatal("cw executable mode was not retained")
		}
	}
	if _, err := reader.Next(); !errors.Is(err, io.EOF) {
		t.Fatalf("unexpected extra archive entry: %v", err)
	}
}

func TestSourceIdentityRejectsDifferentOrDirtyRevision(t *testing.T) {
	fixture := newPublicationFixture(t)
	if _, _, err := SourceIdentity(t.Context(), fixture.options.Source, "0000000000000000000000000000000000000000", true); err == nil {
		t.Fatal("different source revision accepted")
	}
	writeTest(t, filepath.Join(fixture.options.Source, "README.md"), []byte("uncommitted source"))
	if _, _, err := SourceIdentity(t.Context(), fixture.options.Source, fixture.options.Revision, true); err == nil {
		t.Fatal("dirty release source accepted")
	}
}
