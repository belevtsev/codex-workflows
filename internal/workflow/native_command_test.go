package workflow

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func nativeFixtureInstaller(t *testing.T, fixture *installerFixture, revision string, apply bool) *Installer {
	t.Helper()
	t.Setenv("PATH", "/usr/bin:/bin")
	candidate := filepath.Join(fixture.base, "native candidate "+revision)
	installerWrite(t, candidate, "#!/bin/sh\nexit 0\n", 0o755)
	installer := fixture.installer(apply)
	installer.Context = t.Context()
	installer.RuntimeCandidate = candidate
	installer.RuntimeIdentity = RuntimeIdentity{Revision: revision, Version: "test", OS: runtime.GOOS, Arch: runtime.GOARCH}
	return installer
}

func TestNativeManagerAlreadyOnPATHDoesNotAddProfile(t *testing.T) {
	for _, legacy := range []bool{false, true} {
		t.Run(fmt.Sprintf("legacy %t", legacy), func(t *testing.T) {
			fixture := newInstallerFixture(t)
			original := fixture.seedUserFiles(t)
			if legacy {
				fixture.execute(t, "setup")
			}
			installer := nativeFixtureInstaller(t, fixture, fixture.first, true)
			t.Setenv("PATH", filepath.Join(fixture.paths.Home, ".local", "bin")+":/usr/bin:/bin")
			if _, err := installer.Setup(true); err != nil {
				t.Fatal(err)
			}
			state, err := installer.state(true)
			if err != nil {
				t.Fatal(err)
			}
			if object(state["manager"])["profile"] != nil {
				t.Fatal("unnecessary PATH profile was added")
			}
			rc := filepath.Join(fixture.paths.Home, ".bashrc")
			if got := installerRead(t, rc); got != original[rc] {
				t.Fatalf("startup bytes changed: %q", got)
			}
		})
	}
}

func TestNativeManagerLegacyShellOverridePreservesBothProfiles(t *testing.T) {
	for _, shell := range []string{"none", "zsh"} {
		t.Run(shell, func(t *testing.T) {
			fixture := newInstallerFixture(t)
			original := fixture.seedUserFiles(t)
			zsh := filepath.Join(fixture.paths.Home, ".zshrc")
			installerWrite(t, zsh, "# personal zsh bytes\n", 0o604)
			fixture.execute(t, "setup") // Legacy Bash wrapper.
			bash := filepath.Join(fixture.paths.Home, ".bashrc")
			installerAppend(t, bash, "# independent bash edit\n")
			installer := nativeFixtureInstaller(t, fixture, fixture.first, true)
			installer.Shell = shell
			t.Setenv("ZDOTDIR", "")
			if _, err := installer.Setup(true); err != nil {
				t.Fatal(err)
			}
			if got := installerRead(t, bash); got != original[bash]+"# independent bash edit\n" {
				t.Fatalf("legacy Bash block was retained or unrelated bytes lost: %q", got)
			}
			state, err := installer.state(true)
			if err != nil {
				t.Fatal(err)
			}
			profile := object(object(state["manager"])["profile"])
			if shell == "none" {
				if profile != nil || installerRead(t, zsh) != "# personal zsh bytes\n" {
					t.Fatal("shell none enrolled a profile")
				}
			} else if profile["shell"] != "zsh" || !strings.Contains(installerRead(t, zsh), profileStart) {
				t.Fatal("explicit Zsh profile was not enrolled")
			}
			installerAppend(t, zsh, "# independent zsh edit\n")
			if _, err = installer.Uninstall(); err != nil {
				t.Fatal(err)
			}
			if got := installerRead(t, bash); got != original[bash]+"# independent bash edit\n" {
				t.Fatalf("uninstall changed Bash bytes: %q", got)
			}
			if got := installerRead(t, zsh); got != "# personal zsh bytes\n# independent zsh edit\n" {
				t.Fatalf("uninstall changed Zsh bytes: %q", got)
			}
			info, err := os.Stat(zsh)
			if err != nil || info.Mode().Perm() != 0o604 {
				t.Fatalf("Zsh mode changed: %v", err)
			}
		})
	}
}

func TestNativeManagerInterruptedShellMigrationRestoresLegacy(t *testing.T) {
	fixture := newInstallerFixture(t)
	original := fixture.seedUserFiles(t)
	zsh := filepath.Join(fixture.paths.Home, ".zshrc")
	installerWrite(t, zsh, "# zsh original\n", 0o600)
	fixture.execute(t, "setup")
	legacyState, err := fixture.installer(true).state(true)
	if err != nil {
		t.Fatal(err)
	}
	installer := nativeFixtureInstaller(t, fixture, fixture.first, true)
	installer.Shell = "zsh"
	t.Setenv("ZDOTDIR", "")
	t.Setenv("CODEX_WORKFLOWS_FAULT", "after-state")
	if _, err = installer.Setup(true); err == nil {
		t.Fatal("fault did not interrupt shell migration")
	}
	t.Setenv("CODEX_WORKFLOWS_FAULT", "")
	bash := filepath.Join(fixture.paths.Home, ".bashrc")
	installerAppend(t, bash, "# later bash bytes\n")
	installerAppend(t, zsh, "# later zsh bytes\n")
	if _, err = installer.Recover(); err != nil {
		t.Fatal(err)
	}
	state, err := installer.state(true)
	if err != nil {
		t.Fatal(err)
	}
	if !equal(state, legacyState) {
		t.Fatal("recovery did not restore exact legacy ownership")
	}
	got := installerRead(t, bash)
	start, end, err := aliasLocate([]byte(got), text(object(state["command_alias"])["segment"]))
	if err != nil {
		t.Fatal(err)
	}
	if unowned := got[:start] + got[end:]; unowned != original[bash]+"# later bash bytes\n" {
		t.Fatalf("Bash restoration lost independent bytes: %q", unowned)
	}
	if got := installerRead(t, zsh); got != "# zsh original\n# later zsh bytes\n" {
		t.Fatalf("Zsh reversal lost independent bytes: %q", got)
	}
}

func TestNativeManagerRejectsExternalPATHCommand(t *testing.T) {
	fixture := newInstallerFixture(t)
	fixture.seedUserFiles(t)
	installer := nativeFixtureInstaller(t, fixture, fixture.first, true)
	otherBin := filepath.Join(fixture.base, "other bin")
	installerWrite(t, filepath.Join(otherBin, "cw"), "#!/bin/sh\nexit 0\n", 0o755)
	t.Setenv("PATH", otherBin+":/usr/bin:/bin")
	before := installerSnapshot(t, fixture.base)
	if _, err := installer.Setup(true); err == nil || !strings.Contains(err.Error(), "another cw command") {
		t.Fatalf("external cw accepted: %v", err)
	}
	installerUnchanged(t, fixture.base, before)
}

func TestNativeManagerMigratesLegacyAndMaintainsWithoutSource(t *testing.T) {
	fixture := newInstallerFixture(t)
	original := fixture.seedUserFiles(t)
	fixture.execute(t, "setup")
	installer := nativeFixtureInstaller(t, fixture, fixture.first, true)
	legacy, err := installer.state(true)
	if err != nil {
		t.Fatal(err)
	}
	delete(legacy, "source") // A historical v1 record has source only in its wrapper.
	installerWrite(t, installer.statePath, string(legacyJSON(seal(legacy))), 0o600)
	if _, err = installer.Setup(true); err != nil {
		t.Fatal(err)
	}
	state, err := installer.state(true)
	if err != nil {
		t.Fatal(err)
	}
	if state["command_alias"] != nil || object(state["manager"]) == nil {
		t.Fatal("legacy wrapper ownership was not migrated")
	}
	for path, want := range map[string]string{installer.commandPath(): filepath.Join(installer.runtimeCurrent(), "cw"), installer.runtimeCurrent(): installer.runtimeDir(fixture.first)} {
		got, err := os.Readlink(path)
		if err != nil || got != want {
			t.Fatalf("native link %s = %q, %v", path, got, err)
		}
	}
	rc := filepath.Join(fixture.paths.Home, ".bashrc")
	contents := installerRead(t, rc)
	if strings.Contains(contents, "function cw") || !strings.Contains(contents, profileStart) {
		t.Fatalf("wrapper remains: %s", contents)
	}
	before := installerSnapshot(t, fixture.base)
	if report, err := installer.Setup(true); err != nil || report["changed"] != false {
		t.Fatalf("repeat native setup: %#v, %v", report, err)
	}
	installerUnchanged(t, fixture.base, before)
	installerAppend(t, rc, "# unrelated after native enrollment\n")
	if err = os.Rename(fixture.paths.Source, fixture.paths.Source+" unavailable"); err != nil {
		t.Fatal(err)
	}
	installer.Source = filepath.Join(fixture.base, "a missing source")
	if _, err = installer.Status(); err != nil {
		t.Fatalf("source-independent status: %v", err)
	}
	if _, err = installer.Uninstall(); err != nil {
		t.Fatalf("source-independent uninstall: %v", err)
	}
	if contents = installerRead(t, rc); contents != original[rc]+"# unrelated after native enrollment\n" {
		t.Fatalf("uninstall lost rc bytes: %q", contents)
	}
	for _, path := range []string{installer.commandPath(), installer.runtimeCurrent(), installer.locatorPath(), installer.statePath} {
		if exists(path) {
			t.Fatalf("uninstall retained owned path %s", path)
		}
	}
	if _, err = installer.runtimeRelease(fixture.first); err != nil {
		t.Fatalf("uninstall removed runtime cache: %v", err)
	}
}

func TestNativeManagerRecoversEveryNativeBoundary(t *testing.T) {
	for _, label := range []string{"after-manager-runtime", "after-manager-command", "after-manager-locator", "after-command-profile", "after-state"} {
		t.Run(label, func(t *testing.T) {
			fixture := newInstallerFixture(t)
			original := fixture.seedUserFiles(t)
			installer := nativeFixtureInstaller(t, fixture, fixture.first, true)
			t.Setenv("CODEX_WORKFLOWS_FAULT", label)
			if _, err := installer.Setup(true); err == nil {
				t.Fatal("fault did not interrupt native enrollment")
			}
			t.Setenv("CODEX_WORKFLOWS_FAULT", "")
			installer.Source = filepath.Join(fixture.base, "unavailable")
			if _, err := installer.Recover(); err != nil {
				t.Fatal(err)
			}
			for path, want := range original {
				if got := installerRead(t, path); got != want {
					t.Fatalf("recovery changed %s: %q", path, got)
				}
			}
			for _, path := range []string{installer.commandPath(), installer.runtimeCurrent(), installer.locatorPath(), installer.statePath, installer.journalPath} {
				if exists(path) {
					t.Fatalf("recovery retained %s", path)
				}
			}
		})
	}
}

func TestNativeManagerRecoveryPreservesIndependentProfileEdits(t *testing.T) {
	fixture := newInstallerFixture(t)
	original := fixture.seedUserFiles(t)
	installer := nativeFixtureInstaller(t, fixture, fixture.first, true)
	t.Setenv("CODEX_WORKFLOWS_FAULT", "after-command-profile")
	if _, err := installer.Setup(true); err == nil {
		t.Fatal("fault did not interrupt profile installation")
	}
	t.Setenv("CODEX_WORKFLOWS_FAULT", "")
	rc := filepath.Join(fixture.paths.Home, ".bashrc")
	installerAppend(t, rc, "# independent after failure\n")
	t.Setenv("CODEX_WORKFLOWS_FAULT", "after-recover-command-profile")
	if _, err := installer.Recover(); err == nil {
		t.Fatal("fault did not interrupt recovery")
	}
	t.Setenv("CODEX_WORKFLOWS_FAULT", "")
	installerAppend(t, rc, "# independent during recovery\n")
	if _, err := installer.Recover(); err != nil {
		t.Fatal(err)
	}
	if got := installerRead(t, rc); got != original[rc]+"# independent after failure\n# independent during recovery\n" {
		t.Fatalf("lost independent profile bytes: %q", got)
	}
}

func TestNativeManagerConflictAndPreparationFailureDoNotActivate(t *testing.T) {
	for _, conflict := range []string{"command", "candidate"} {
		t.Run(conflict, func(t *testing.T) {
			fixture := newInstallerFixture(t)
			fixture.seedUserFiles(t)
			installer := nativeFixtureInstaller(t, fixture, fixture.first, true)
			if conflict == "command" {
				installerWrite(t, installer.commandPath(), "user command", 0o755)
			} else {
				installer.RuntimeIdentity.Revision = strings.Repeat("b", 40)
				installer.PrepareRuntime = func(context.Context, string, string, string) (RuntimeCandidate, error) {
					return RuntimeCandidate{}, errors.New("download failed")
				}
			}
			before := installerSnapshot(t, fixture.base)
			if _, err := installer.Setup(true); err == nil {
				t.Fatal("invalid native preparation succeeded")
			}
			installerUnchanged(t, fixture.base, before)
		})
	}
}

func TestNativeManagerRejectsTamperedRuntime(t *testing.T) {
	fixture := newInstallerFixture(t)
	fixture.seedUserFiles(t)
	installer := nativeFixtureInstaller(t, fixture, fixture.first, true)
	if _, err := installer.Setup(true); err != nil {
		t.Fatal(err)
	}
	runtimePath := filepath.Join(installer.runtimeDir(fixture.first), "cw")
	installerAppend(t, runtimePath, "# tampered\n")
	if _, err := installer.Status(); err == nil {
		t.Fatal("modified executable accepted")
	}
}

func TestNativeManagerUninstallRecoversEveryNativeBoundary(t *testing.T) {
	for _, label := range []string{"after-command-profile", "after-manager-command", "after-manager-runtime", "after-manager-locator", "after-state"} {
		t.Run(label, func(t *testing.T) {
			fixture := newInstallerFixture(t)
			fixture.seedUserFiles(t)
			installer := nativeFixtureInstaller(t, fixture, fixture.first, true)
			if _, err := installer.Setup(true); err != nil {
				t.Fatal(err)
			}
			stateBefore, err := installer.state(true)
			if err != nil {
				t.Fatal(err)
			}
			t.Setenv("CODEX_WORKFLOWS_FAULT", label)
			if _, err = installer.Uninstall(); err == nil {
				t.Fatal("fault did not interrupt native uninstall")
			}
			t.Setenv("CODEX_WORKFLOWS_FAULT", "")
			if _, err = installer.runtimeRelease(fixture.first); err != nil {
				t.Fatalf("immutable recovery metadata unavailable: %v", err)
			}
			installer.Source = filepath.Join(fixture.base, "missing source during recovery")
			if _, err = installer.Recover(); err != nil {
				t.Fatalf("native uninstall recovery: %v", err)
			}
			stateAfter, err := installer.state(true)
			if err != nil {
				t.Fatal(err)
			}
			if !equal(stateBefore, stateAfter) {
				t.Fatal("native recovery lost original ownership")
			}
			if _, err = installer.Status(); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestNativeManagerUnsafeRecoveryJournalRefusesAllReversals(t *testing.T) {
	for _, corruption := range []string{"command-path", "runtime-target", "locator-roots", "profile-path", "profile-content"} {
		t.Run(corruption, func(t *testing.T) {
			fixture := newInstallerFixture(t)
			fixture.seedUserFiles(t)
			installer := nativeFixtureInstaller(t, fixture, fixture.first, true)
			t.Setenv("CODEX_WORKFLOWS_FAULT", "after-state")
			if _, err := installer.Setup(true); err == nil {
				t.Fatal("fault did not interrupt native setup")
			}
			t.Setenv("CODEX_WORKFLOWS_FAULT", "")
			journal, err := readJSON(installer.journalPath)
			if err != nil {
				t.Fatal(err)
			}
			for _, raw := range sequence(journal["operations"]) {
				op := object(raw)
				switch {
				case corruption == "command-path" && op["path"] == installer.commandPath():
					op["path"] = filepath.Join(fixture.base, "foreign command")
				case corruption == "runtime-target" && op["path"] == installer.runtimeCurrent():
					object(op["after"])["target"] = fixture.paths.Source
				case corruption == "locator-roots" && op["path"] == installer.locatorPath():
					object(op["after"])["data"] = encode(legacyJSON(RuntimeLocator{Source: fixture.paths.Source, Home: fixture.base, Codex: fixture.paths.Codex, State: fixture.paths.State}))
				case corruption == "profile-path" && op["kind"] == "command_profile":
					op["path"] = filepath.Join(fixture.base, "foreign rc")
				case corruption == "profile-content" && op["kind"] == "command_profile":
					op["after_segment"] = "unowned content"
				}
			}
			installerWrite(t, installer.journalPath, string(legacyJSON(seal(journal))), 0o600)
			before := installerSnapshot(t, fixture.base)
			if _, err = installer.Recover(); err == nil {
				t.Fatal("unsafe native recovery journal accepted")
			}
			installerUnchanged(t, fixture.base, before)
		})
	}
}

func TestNativeManagerSymlinkedCommandParentRefusesUninstall(t *testing.T) {
	fixture := newInstallerFixture(t)
	fixture.seedUserFiles(t)
	installer := nativeFixtureInstaller(t, fixture, fixture.first, true)
	if _, err := installer.Setup(true); err != nil {
		t.Fatal(err)
	}
	bin := filepath.Dir(installer.commandPath())
	foreign := filepath.Join(fixture.base, "foreign bin")
	if err := os.Rename(bin, foreign); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(foreign, bin); err != nil {
		t.Fatal(err)
	}
	before := installerSnapshot(t, fixture.base)
	if _, err := installer.Uninstall(); err == nil {
		t.Fatal("symlinked command parent was accepted")
	}
	installerUnchanged(t, fixture.base, before)
}

func TestInstallerContextCancellationLeavesInstallationUntouched(t *testing.T) {
	fixture := newInstallerFixture(t)
	fixture.seedUserFiles(t)
	installer := fixture.installer(true)
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	installer.Context = ctx
	before := installerSnapshot(t, fixture.base)
	if _, err := installer.Setup(true); !errors.Is(err, context.Canceled) {
		t.Fatalf("cancelled setup: %v", err)
	}
	installerUnchanged(t, fixture.base, before)
}

func TestNativeRootMigrationRollbackRetainsRuntimeAndOriginalOwnership(t *testing.T) {
	fixture := newInstallerFixture(t)
	manifestPath := filepath.Join(fixture.paths.Source, "skills-manifest.json")
	manifest := strings.ReplaceAll(installerRead(t, manifestPath), "third_party/", "vendor/")
	if err := os.Rename(filepath.Join(fixture.paths.Source, "third_party"), filepath.Join(fixture.paths.Source, "vendor")); err != nil {
		t.Fatal(err)
	}
	installerWrite(t, manifestPath, manifest, 0o644)
	fixture.git(t, "add", "-A")
	fixture.git(t, "commit", "-qm", "legacy roots")
	fixture.first = fixture.git(t, "rev-parse", "HEAD")
	var err error
	fixture.manifest, err = LoadManifest(fixture.paths.Source)
	if err != nil {
		t.Fatal(err)
	}
	fixture.seedUserFiles(t)
	installer := nativeFixtureInstaller(t, fixture, fixture.first, true)
	if _, err = installer.Setup(true); err != nil {
		t.Fatal(err)
	}
	before, err := installer.state(true)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.Rename(filepath.Join(fixture.paths.Source, "vendor"), filepath.Join(fixture.paths.Source, "third_party")); err != nil {
		t.Fatal(err)
	}
	installerWrite(t, manifestPath, strings.ReplaceAll(manifest, "vendor/", "third_party/"), 0o644)
	fixture.git(t, "add", "-A")
	fixture.git(t, "commit", "-qm", "modern third-party roots")
	second := fixture.git(t, "rev-parse", "HEAD")
	installer = nativeFixtureInstaller(t, fixture, second, true)
	if _, err = installer.Setup(true); err != nil {
		t.Fatal(err)
	}
	state, err := installer.state(true)
	if err != nil {
		t.Fatal(err)
	}
	for name, raw := range object(state["registrations"]) {
		if !equal(object(raw)["original"], object(object(before["registrations"])[name])["original"]) {
			t.Fatalf("root migration lost original ownership: %s", name)
		}
		target, err := os.Readlink(filepath.Join(installer.skills, name))
		if err != nil || target != installer.target(text(object(state["manifest_registrations"])[name])) {
			t.Fatalf("registration target %s: %q, %v", name, target, err)
		}
	}
	if err = os.Rename(fixture.paths.Source, fixture.paths.Source+" unavailable"); err != nil {
		t.Fatal(err)
	}
	if _, err = installer.Rollback(); err != nil {
		t.Fatalf("source-independent root rollback: %v", err)
	}
	state, err = installer.state(true)
	if err != nil {
		t.Fatal(err)
	}
	if state["release"] != fixture.first || !equal(state["manifest_registrations"], before["manifest_registrations"]) {
		t.Fatal("rollback did not restore legacy roots")
	}
	if object(object(state["manager"])["runtime"])["revision"] != second {
		t.Fatal("skill rollback downgraded native manager")
	}
	if _, err = installer.Status(); err != nil {
		t.Fatal(err)
	}
}

func TestNativeUpdateNoCheckoutPreparesFetchedRuntime(t *testing.T) {
	fixture := newInstallerFixture(t)
	fixture.seedUserFiles(t)
	origin := fixture.bareOrigin(t)
	installer := nativeFixtureInstaller(t, fixture, fixture.first, true)
	if _, err := installer.Setup(true); err != nil {
		t.Fatal(err)
	}
	second := fixture.newRelease(t)
	fixture.git(t, "push", origin, "main")
	fixture.git(t, "reset", "--hard", fixture.first)
	candidate := nativeFixtureInstaller(t, fixture, second, true)
	calls := 0
	installer.NoCheckout = true
	installer.PrepareRuntime = func(ctx context.Context, source, sha, root string) (RuntimeCandidate, error) {
		calls++
		if ctx != installer.Context || source != installer.Source || sha != second || root != installer.State {
			t.Fatal("runtime preparation did not receive exact update inputs")
		}
		return RuntimeCandidate{Path: candidate.RuntimeCandidate, Identity: candidate.RuntimeIdentity}, nil
	}
	if _, err := installer.Update(); err != nil {
		t.Fatal(err)
	}
	if calls != 1 {
		t.Fatalf("runtime prepare calls = %d", calls)
	}
	if got := fixture.git(t, "rev-parse", "HEAD"); got != fixture.first {
		t.Fatalf("no-checkout advanced source: %s", got)
	}
	state, err := installer.state(true)
	if err != nil {
		t.Fatal(err)
	}
	if state["release"] != second || object(object(state["manager"])["runtime"])["revision"] != second {
		t.Fatal("no-checkout failed to update manager and skills")
	}
}
