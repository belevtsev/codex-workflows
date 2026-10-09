package manageruntime

import (
	"archive/tar"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func writeFixture(t *testing.T, path, contents string, mode os.FileMode) {
	t.Helper()
	if err := os.WriteFile(path, []byte(contents), mode); err != nil {
		t.Fatal(err)
	}
}
func managerScript(protocol bool) string {
	identity := fmt.Sprintf(`{"arch":"%s","built_at":"unknown","os":"%s","revision":"%s","version":"v1.2.3"}`, runtime.GOARCH, runtime.GOOS, fixtureSHA)
	script := "#!/bin/sh\nif [ \"${1-}\" = version ]; then printf '%s\\n' '" + identity + "'; exit 0; fi\n"
	if protocol {
		script += "if [ \"${1-}\" = --manager-protocol ]; then printf '%s\\n' cw-manager-v3; exit 0; fi\nprintf '%s\\n' '{\"forwarded\":true}'; exit 0\n"
	} else {
		script += "exit 2\n"
	}
	return script
}

func bootstrapFixture(t *testing.T, legacy bool) (string, string, string) {
	t.Helper()
	root := realTemp(t)
	checkout := filepath.Join(root, "source with spaces")
	bin := filepath.Join(checkout, ".bin")
	if err := os.MkdirAll(bin, 0755); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile("../../install.sh")
	if err != nil {
		t.Fatal(err)
	}
	launcher := filepath.Join(checkout, "install.sh")
	writeFixture(t, launcher, string(data), 0755)
	binary := filepath.Join(bin, "cw")
	if legacy {
		writeFixture(t, binary, managerScript(false), 0755)
	}
	mockBin := filepath.Join(root, "mock-bin")
	if err := os.Mkdir(mockBin, 0755); err != nil {
		t.Fatal(err)
	}
	archive := archiveFixture(t, []tar.Header{{Name: "cw", Typeflag: tar.TypeReg, Mode: 0755}}, []string{managerScript(true)})
	archivePath := filepath.Join(root, "release.tar.gz")
	if err := os.WriteFile(archivePath, archive, 0644); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(archive)
	sums := filepath.Join(root, "SHA256SUMS")
	writeFixture(t, sums, fmt.Sprintf("%s  cw_%s_%s.tar.gz\n", hex.EncodeToString(sum[:]), runtime.GOOS, runtime.GOARCH), 0644)
	calls := filepath.Join(root, "calls")
	writeFixture(t, filepath.Join(mockBin, "curl"), `#!/bin/sh
set -eu
output=
address=
next=false
for argument in "$@"; do
 if "$next"; then output=$argument; next=false; continue; fi
 case $argument in -o) next=true ;; https:*) address=$argument ;; esac
done
printf '%s\n' "$address" >> "$CW_MOCK_CALLS"
case $address in */SHA256SUMS) cp "$CW_MOCK_SUMS" "$output" ;; *) cp "$CW_MOCK_ARCHIVE" "$output" ;; esac
`, 0755)
	t.Setenv("PATH", mockBin+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("CW_MOCK_CALLS", calls)
	t.Setenv("CW_MOCK_SUMS", sums)
	t.Setenv("CW_MOCK_ARCHIVE", archivePath)
	return launcher, binary, calls
}

func runBootstrap(ctx context.Context, launcher string, args ...string) (string, error) {
	command := exec.CommandContext(ctx, launcher, args...)
	data, err := command.CombinedOutput()
	return string(data), err
}

func TestBootstrapRefreshesRecognizedLegacyManager(t *testing.T) {
	launcher, binary, calls := bootstrapFixture(t, true)
	output, err := runBootstrap(t.Context(), launcher, "status", "--home", "/fixture/home")
	if err != nil {
		t.Fatalf("%v: %s", err, output)
	}
	if strings.TrimSpace(output) != `{"forwarded":true}` {
		t.Fatalf("not forwarded: %q", output)
	}
	data, err := os.ReadFile(binary)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != managerScript(true) {
		t.Fatal("legacy manager not refreshed")
	}
	requested, err := os.ReadFile(calls)
	if err != nil {
		t.Fatal(err)
	}
	if len(strings.Split(strings.TrimSpace(string(requested)), "\n")) != 2 {
		t.Fatalf("unexpected downloads: %s", requested)
	}
}
func TestBootstrapColdDryRunAndHelpPreserveLegacy(t *testing.T) {
	for _, args := range [][]string{{"--dry-run"}, {"--dry-run=1"}, {"--dry-run=t"}, {"--dry-run=T"}, {"--dry-run=true"}, {"--dry-run=TRUE"}, {"--dry-run=True"}, {"help"}} {
		t.Run(args[0], func(t *testing.T) {
			launcher, binary, calls := bootstrapFixture(t, true)
			before, _ := os.ReadFile(binary)
			output, err := runBootstrap(t.Context(), launcher, args...)
			if err != nil {
				t.Fatalf("%v: %s", err, output)
			}
			after, _ := os.ReadFile(binary)
			if string(before) != string(after) {
				t.Fatal("read-only bootstrap replaced legacy cache")
			}
			if _, err = os.Stat(calls); !os.IsNotExist(err) {
				t.Fatal("read-only bootstrap downloaded")
			}
		})
	}
}
func TestBootstrapRefreshesOlderNativeProtocol(t *testing.T) {
	launcher, binary, calls := bootstrapFixture(t, false)
	writeFixture(t, binary, strings.Replace(managerScript(true), "cw-manager-v3", "cw-manager-v2", 1), 0755)
	output, err := runBootstrap(t.Context(), launcher, "status")
	if err != nil || strings.TrimSpace(output) != `{"forwarded":true}` {
		t.Fatalf("%v: %s", err, output)
	}
	data, err := os.ReadFile(binary)
	if err != nil || string(data) != managerScript(true) {
		t.Fatalf("old native protocol not refreshed: %v", err)
	}
	if _, err := os.Stat(calls); err != nil {
		t.Fatal("old native manager did not acquire a compatible release")
	}
}
func TestBootstrapColdDryRunBooleanFormsNeverCreateCache(t *testing.T) {
	for _, argument := range []string{"--dry-run", "--dry-run=1", "--dry-run=t", "--dry-run=T", "--dry-run=true", "--dry-run=TRUE", "--dry-run=True"} {
		t.Run(argument, func(t *testing.T) {
			launcher, binary, calls := bootstrapFixture(t, false)
			cache := filepath.Dir(binary)
			if err := os.Remove(cache); err != nil {
				t.Fatal(err)
			}
			output, err := runBootstrap(t.Context(), launcher, "install", argument)
			if err != nil || !strings.Contains(output, `"validation":"deferred"`) {
				t.Fatalf("%v: %s", err, output)
			}
			for _, path := range []string{cache, filepath.Dir(cache) + "/.bin.lock", calls} {
				if _, err := os.Lstat(path); !os.IsNotExist(err) {
					t.Fatalf("dry run created %s: %v", path, err)
				}
			}
		})
	}
}
func TestBootstrapPreservesUnidentifiedCache(t *testing.T) {
	launcher, binary, calls := bootstrapFixture(t, true)
	writeFixture(t, binary, "#!/bin/sh\nprintf '%s\\n' unknown\n", 0755)
	before, _ := os.ReadFile(binary)
	output, err := runBootstrap(t.Context(), launcher, "status")
	if err == nil || !strings.Contains(output, "unidentified .bin/cw") {
		t.Fatalf("%v: %s", err, output)
	}
	after, _ := os.ReadFile(binary)
	if string(before) != string(after) {
		t.Fatal("unidentified cache replaced")
	}
	if _, err = os.Stat(calls); !os.IsNotExist(err) {
		t.Fatal("unidentified cache downloaded")
	}
}
