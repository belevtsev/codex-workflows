package devcheck

import (
	"crypto/sha256"
	"encoding/hex"
	json "encoding/json/v2"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

type personalImportFile struct {
	Path        string `json:"path"`
	Mode        int    `json:"mode"`
	SourceSHA   string `json:"source_sha256"`
	ImportedSHA string `json:"imported_sha256"`
	SourceBlob  string `json:"source_git_blob"`
	Adaptation  string `json:"adaptation"`
}

type personalInventoryFile struct {
	Path string `json:"path"`
	Kind string `json:"kind"`
	Mode int    `json:"mode"`
	SHA  string `json:"sha256,omitempty"`
}

func TestPersonalImportHashesAndCompleteOriginalInventories(t *testing.T) {
	source := filepath.Clean(filepath.Join("..", ".."))
	var provenance struct {
		Version int    `json:"version"`
		Catalog string `json:"adoption_catalog"`
		Format  string `json:"inventory_digest_format"`
		Imports map[string]struct {
			Classification string `json:"classification"`
			Destination    string `json:"destination"`
			Source         struct {
				Kind            string `json:"kind"`
				Repository      string `json:"repository"`
				DeclaredVersion string `json:"declared_version"`
				Tag             string `json:"tag"`
				Commit          string `json:"commit"`
				CommitVerified  bool   `json:"commit_verified"`
				FileCount       int    `json:"original_file_count"`
				EntryCount      int    `json:"original_entry_count"`
				InventorySHA    string `json:"inventory_sha256"`
				Limits          string `json:"verification_limits"`
			} `json:"source"`
			Files    []personalImportFile `json:"files"`
			Excluded []string             `json:"excluded_source_files"`
		} `json:"imports"`
		Notices []struct {
			Path       string `json:"path"`
			Source     string `json:"source"`
			Blob       string `json:"git_blob"`
			SHA        string `json:"sha256"`
			Unmodified bool   `json:"unmodified"`
		} `json:"additional_notices"`
	}
	read := func(path string, value any) {
		t.Helper()
		data, err := os.ReadFile(filepath.Join(source, path))
		if err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(data, value, json.RejectUnknownMembers(true)); err != nil {
			t.Fatal(err)
		}
	}
	read("third_party/personal-skill-imports.json", &provenance)
	if provenance.Version != 1 || provenance.Catalog != "personal-skill-origins.json" || len(provenance.Imports) != 13 {
		t.Fatalf("incomplete personal provenance: version=%d imports=%d", provenance.Version, len(provenance.Imports))
	}
	var catalog struct {
		Version int `json:"version"`
		Skills  map[string]struct {
			Inventory []personalInventoryFile `json:"inventory"`
		} `json:"skills"`
	}
	read(provenance.Catalog, &catalog)
	if catalog.Version != 1 || len(catalog.Skills) != len(provenance.Imports) {
		t.Fatal("catalog and imports disagree")
	}
	digest := func(data []byte) string { sum := sha256.Sum256(data); return hex.EncodeToString(sum[:]) }
	for name, imported := range provenance.Imports {
		t.Run(name, func(t *testing.T) {
			if !filepath.IsLocal(imported.Destination) || strings.Contains(imported.Destination, "slack-pr-review") {
				t.Fatal("unsafe import root")
			}
			inventory := catalog.Skills[name].Inventory
			data, err := json.Marshal(inventory)
			if err != nil {
				t.Fatal(err)
			}
			if len(inventory) != imported.Source.EntryCount || digest(data) != imported.Source.InventorySHA {
				t.Fatal("original inventory digest changed")
			}
			originals := map[string]personalInventoryFile{}
			for _, entry := range inventory {
				if entry.Kind == "file" {
					originals[entry.Path] = entry
				}
			}
			if len(originals) != imported.Source.FileCount {
				t.Fatal("original file count changed")
			}
			files := map[string]personalImportFile{}
			for _, file := range imported.Files {
				if !filepath.IsLocal(file.Path) || filepath.ToSlash(filepath.Clean(file.Path)) != file.Path {
					t.Fatalf("unsafe imported path %s", file.Path)
				}
				if _, exists := files[file.Path]; exists {
					t.Fatal("duplicate imported file")
				}
				files[file.Path] = file
				if original, exists := originals[file.Path]; exists {
					if file.SourceSHA != original.SHA {
						t.Fatalf("original source hash lost: %s", file.Path)
					}
					delete(originals, file.Path)
				}
				if file.SourceSHA != file.ImportedSHA && file.Adaptation == "" {
					t.Fatalf("unexplained adaptation: %s", file.Path)
				}
			}
			if !slices.IsSorted(imported.Excluded) {
				t.Fatal("excluded inventory is not sorted")
			}
			for _, excluded := range imported.Excluded {
				if _, exists := originals[excluded]; !exists {
					t.Fatalf("unknown or duplicated exclusion: %s", excluded)
				}
				delete(originals, excluded)
			}
			if len(originals) != 0 {
				t.Fatal("original inventory contains unrecorded omissions")
			}
			root := filepath.Join(source, imported.Destination)
			err = filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
				if err != nil {
					return err
				}
				if entry.Type()&os.ModeSymlink != 0 {
					t.Fatalf("imported link: %s", path)
				}
				if entry.IsDir() {
					if entry.Name() == "node_modules" || entry.Name() == ".git" || entry.Name() == ".cache" {
						t.Fatalf("excluded runtime state: %s", path)
					}
					return nil
				}
				relative, err := filepath.Rel(root, path)
				if err != nil {
					return err
				}
				file, exists := files[filepath.ToSlash(relative)]
				if !exists {
					t.Fatalf("unrecorded import: %s", path)
				}
				data, err := os.ReadFile(path)
				if err != nil {
					return err
				}
				info, err := entry.Info()
				if err != nil {
					return err
				}
				if !info.Mode().IsRegular() || int(info.Mode().Perm()) != file.Mode || digest(data) != file.ImportedSHA {
					t.Fatalf("import changed without provenance: %s", path)
				}
				delete(files, filepath.ToSlash(relative))
				return nil
			})
			if err != nil {
				t.Fatal(err)
			}
			if len(files) != 0 {
				t.Fatal("provenance references missing files")
			}
		})
	}
	for _, notice := range provenance.Notices {
		if !filepath.IsLocal(notice.Path) || !notice.Unmodified {
			t.Fatal("invalid additional notice")
		}
		data, err := os.ReadFile(filepath.Join(source, notice.Path))
		if err != nil || digest(data) != notice.SHA {
			t.Fatalf("notice changed: %s %v", notice.Path, err)
		}
	}
}
