package cli

import (
	"bytes"
	"context"
	json "encoding/json/v2"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/belevtsev/codex-workflows/internal/manageruntime"
	"github.com/belevtsev/codex-workflows/internal/workflow"
)

const fixtureSHA = "0123456789012345678901234567890123456789"

type fakeService struct {
	action  string
	pending bool
}

func (f *fakeService) Execute(action string) (workflow.Object, error) {
	f.action = action
	return workflow.Object{"command": action, "pending": f.pending}, nil
}
func (f *fakeService) Status() (workflow.Object, error) {
	return workflow.Object{"installed": true}, nil
}
func testConfig(t *testing.T) (Config, *bytes.Buffer, *workflow.Options, *fakeService) {
	t.Helper()
	out := new(bytes.Buffer)
	options := new(workflow.Options)
	service := new(fakeService)
	config := Config{Version: "v1.2.3", Revision: fixtureSHA, BuiltAt: "now", Out: out, Err: io.Discard, HomeDir: func() (string, error) { return "/fixture/home", nil }, WorkingDir: func() (string, error) { return "/fixture/cwd", nil }, Executable: func() (string, error) { return os.Executable() }, Getenv: func(string) string { return "" }, Resolve: func(string) (manageruntime.Locator, error) { return manageruntime.Locator{}, os.ErrNotExist }, Inspect: func(_ context.Context, path string) (manageruntime.Candidate, error) {
		return manageruntime.Candidate{Path: path, Revision: fixtureSHA, Version: "v1.2.3", OS: "linux", Arch: "amd64"}, nil
	}, NewService: func(o workflow.Options) Service { *options = o; return service }}
	return config, out, options, service
}
func TestOfflineHelpAndVersionHaveNoEnvironmentDependencies(t *testing.T) {
	for _, args := range [][]string{{"help"}, {"help", "install"}, {"setup", "--help"}, {"version"}, {"--manager-protocol"}, {"--release-identity"}} {
		t.Run(strings.Join(args, "_"), func(t *testing.T) {
			config, out, _, _ := testConfig(t)
			config.ReleaseIdentity = "release-identity-fixture"
			config.Executable = func() (string, error) { t.Fatal("environment resolved for help/version"); return "", nil }
			config.HomeDir = config.Executable
			if err := Execute(t.Context(), args, config); err != nil {
				t.Fatal(err)
			}
			if len(out.Bytes()) == 0 {
				t.Fatal("empty output")
			}
			if args[0] == "--manager-protocol" && out.String() != ManagerProtocol+"\n" {
				t.Fatalf("wrong bootstrap protocol: %q", out.String())
			}
			if args[0] == "--release-identity" && out.String() != config.ReleaseIdentity+"\n" {
				t.Fatalf("wrong release identity: %q", out.String())
			}
			if args[0] == "version" {
				var report map[string]any
				if err := json.Unmarshal(out.Bytes(), &report); err != nil {
					t.Fatal(err)
				}
				if len(report) != 5 || report["revision"] != fixtureSHA {
					t.Fatalf("incompatible version protocol: %v", report)
				}
			}
		})
	}
}
func TestInstalledCommandResolvesLocatorInsteadOfCWD(t *testing.T) {
	config, out, options, service := testConfig(t)
	config.Resolve = func(string) (manageruntime.Locator, error) {
		return manageruntime.Locator{Source: "/owned/source", Home: "/owned/home", Codex: "/owned/codex", State: "/owned/state"}, nil
	}
	config.WorkingDir = func() (string, error) { t.Fatal("installed manager used cwd"); return "", nil }
	if err := Execute(t.Context(), []string{"status"}, config); err != nil {
		t.Fatal(err)
	}
	if options.Source != "/owned/source" || options.Home != "/owned/home" || options.State != "/owned/state" || service.action != "status" {
		t.Fatalf("wrong installation options: %+v", options)
	}
	var report resultReport
	if err := json.Unmarshal(out.Bytes(), &report); err != nil {
		t.Fatal(err)
	}
	if report.Action != "status" || report.Environment.Kind != "native_go" || report.Status["installed"] != true {
		t.Fatalf("incompatible report: %+v", report)
	}
}
func TestInstallAliasAndDefaultEnroll(t *testing.T) {
	for _, args := range [][]string{{}, {"install"}, {"setup"}, {"--home", "/custom", "install", "--shell", "none"}} {
		config, _, options, service := testConfig(t)
		if err := Execute(t.Context(), args, config); err != nil {
			t.Fatal(err)
		}
		if service.action != "setup" || !options.Apply {
			t.Fatalf("install must enroll by default: %s %+v", service.action, options)
		}
	}
}
func TestDryRunAndLegacyFlagsPreserved(t *testing.T) {
	config, _, options, _ := testConfig(t)
	if err := Execute(t.Context(), []string{"install", "--dry-run", "--typesafe-legacy", "/old/typesafe"}, config); err != nil {
		t.Fatal(err)
	}
	if options.Apply || options.TypeSafeLegacy == nil || *options.TypeSafeLegacy != "/old/typesafe" {
		t.Fatalf("wrong flags: %+v", options)
	}
	config, _, options, _ = testConfig(t)
	if err := Execute(t.Context(), []string{"install", "--bootstrap"}, config); err != nil {
		t.Fatal(err)
	}
	if options.Apply {
		t.Fatal("bootstrap compatibility must default read-only")
	}
}
func TestUsageFailuresHaveExitCodeTwo(t *testing.T) {
	for _, args := range [][]string{{"consult-jev"}, {"update", "--shell", "bash"}, {"install", "--shell", "fish"}, {"install", "--dry-run", "--apply"}, {"status", "extra"}, {"--missing"}, {"help", "unknown"}} {
		config, _, _, service := testConfig(t)
		err := Execute(t.Context(), args, config)
		if err == nil || ExitCode(err) != 2 {
			t.Fatalf("%v: %v code %d", args, err, ExitCode(err))
		}
		if service.action != "" {
			t.Fatalf("%v mutated service", args)
		}
	}
}
func TestCanceledContextReachesInstaller(t *testing.T) {
	config, _, options, _ := testConfig(t)
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	// The injected service deliberately succeeds: observe propagation directly.
	if err := Execute(ctx, []string{"status"}, config); err != nil {
		t.Fatal(err)
	}
	if !errors.Is(options.Context.Err(), context.Canceled) || ExitCode(context.Canceled) != 130 {
		t.Fatal("cancellation context lost")
	}
}
func TestSourceBinaryBindsItsCheckout(t *testing.T) {
	config, _, options, _ := testConfig(t)
	root := t.TempDir()
	bin := filepath.Join(root, ".bin")
	if err := os.Mkdir(bin, 0755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(bin, "cw")
	if err := os.WriteFile(path, []byte("fixture"), 0755); err != nil {
		t.Fatal(err)
	}
	config.Executable = func() (string, error) { return path, nil }
	config.WorkingDir = func() (string, error) { t.Fatal("source binary used cwd"); return "", nil }
	if err := Execute(t.Context(), []string{"status"}, config); err != nil {
		t.Fatal(err)
	}
	if options.Source != workflow.Normalize(root) {
		t.Fatalf("source %q want %q", options.Source, workflow.Normalize(root))
	}
}

func TestOwnedLayoutMissingLocatorNeverGuessesDefaults(t *testing.T) {
	config, _, _, service := testConfig(t)
	config.Resolve = func(string) (manageruntime.Locator, error) {
		return manageruntime.Locator{}, manageruntime.ErrLocatorMissing
	}
	config.WorkingDir = func() (string, error) { t.Fatal("guessed cwd for installed manager"); return "", nil }
	config.HomeDir = func() (string, error) { t.Fatal("guessed home for installed manager"); return "", nil }
	if err := Execute(t.Context(), []string{"recover", "--home", "/explicit/home"}, config); !errors.Is(err, manageruntime.ErrLocatorMissing) {
		t.Fatalf("missing locator silently defaulted: %v", err)
	}
	if service.action != "" {
		t.Fatal("service executed with guessed roots")
	}
	if err := Execute(t.Context(), []string{"recover", "--source", "/explicit/source", "--home", "/explicit/home", "--codex-home", "/explicit/codex", "--state-dir", "/explicit/state"}, config); err != nil {
		t.Fatal(err)
	}
	if service.action != "recover" {
		t.Fatal("explicit roots not accepted")
	}
}
