// Package release builds and publishes the immutable native cw release assets.
package release

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
)

var versionPattern = regexp.MustCompile(`^v[0-9]+\.[0-9]+\.[0-9]+$`)
var revisionPattern = regexp.MustCompile(`^[0-9a-f]{40}$`)

var ArchiveNames = []string{
	"cw_darwin_arm64.tar.gz", "cw_darwin_amd64.tar.gz",
	"cw_linux_arm64.tar.gz", "cw_linux_amd64.tar.gz",
}

// Assets is the verified local publication input, including its checksum file.
type Assets struct {
	Directory string
	Digests   map[string]string
}

// ValidateAssets rejects malformed, missing, extra, modified or symlinked assets
// before the publisher is allowed to contact GitHub.
func ValidateAssets(directory string) (*Assets, error) {
	info, err := os.Lstat(directory)
	if err != nil || !info.IsDir() {
		return nil, fmt.Errorf("release directory must be a regular directory: %s", directory)
	}
	manifest, err := regularBytes(filepath.Join(directory, "SHA256SUMS"))
	if err != nil {
		return nil, err
	}
	digests := make(map[string]string, len(ArchiveNames)+1)
	for line := range strings.SplitSeq(strings.TrimSuffix(string(manifest), "\n"), "\n") {
		fields := strings.Fields(line)
		if len(fields) != 2 || len(fields[0]) != 64 || !slices.Contains(ArchiveNames, fields[1]) {
			return nil, errors.New("checksum manifest must cover exactly four native archives")
		}
		decoded, err := hex.DecodeString(fields[0])
		if err != nil || len(decoded) != sha256.Size || strings.ToLower(fields[0]) != fields[0] || digests[fields[1]] != "" {
			return nil, errors.New("invalid or duplicate checksum manifest entry")
		}
		digests[fields[1]] = fields[0]
	}
	if len(digests) != len(ArchiveNames) {
		return nil, errors.New("checksum manifest must cover exactly four native archives")
	}
	entries, err := os.ReadDir(directory)
	if err != nil {
		return nil, err
	}
	for _, entry := range entries {
		if strings.HasSuffix(entry.Name(), ".tar.gz") && !slices.Contains(ArchiveNames, entry.Name()) {
			return nil, fmt.Errorf("unexpected native release archive: %s", entry.Name())
		}
	}
	for _, name := range ArchiveNames {
		actual, err := fileDigest(filepath.Join(directory, name))
		if err != nil {
			return nil, err
		}
		if actual != digests[name] {
			return nil, fmt.Errorf("local release checksum differs: %s", name)
		}
	}
	sum := sha256.Sum256(manifest)
	digests["SHA256SUMS"] = hex.EncodeToString(sum[:])
	return &Assets{Directory: directory, Digests: digests}, nil
}

func regularBytes(path string) ([]byte, error) {
	info, err := os.Lstat(path)
	limit := int64(maxArchiveSize)
	if filepath.Base(path) == "SHA256SUMS" {
		limit = 1024
	}
	if err != nil || !info.Mode().IsRegular() || info.Size() > limit {
		return nil, fmt.Errorf("missing regular release file: %s", filepath.Base(path))
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil || int64(len(data)) > limit {
		return nil, errors.Join(fmt.Errorf("release file exceeds input limit: %s", filepath.Base(path)), err)
	}
	return data, nil
}

func fileDigest(path string) (string, error) {
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() > maxArchiveSize {
		return "", fmt.Errorf("missing regular release file: %s", filepath.Base(path))
	}
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	digest := sha256.New()
	if size, err := io.Copy(digest, io.LimitReader(file, maxArchiveSize+1)); err != nil || size > maxArchiveSize {
		return "", errors.Join(fmt.Errorf("release file exceeds input limit: %s", filepath.Base(path)), err)
	}
	return hex.EncodeToString(digest.Sum(nil)), nil
}
