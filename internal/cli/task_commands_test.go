package cli

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	json "encoding/json/v2"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/belevtsev/codex-workflows/internal/manageruntime"
	"github.com/belevtsev/codex-workflows/internal/taskflow"
)

func TestTaskCLIUsesSelectedProjectAndPrivateExternalStorage(t *testing.T) {
	repo, home := t.TempDir(), t.TempDir()
	data := []byte("verified source\n")
	if err := os.WriteFile(filepath.Join(repo, "source.txt"), data, 0600); err != nil {
		t.Fatal(err)
	}
	config, out, _, _ := testConfig(t)
	config.HomeDir = func() (string, error) { return home, nil }
	config.WorkingDir = func() (string, error) { return repo, nil }
	config.Getenv = func(key string) string {
		if key != "CODEX_HOME" {
			t.Fatal("task command queried adviser credentials")
		}
		return ""
	}
	plan := `{"title":"Inspect real source","kind":"small","requirements":[{"id":"source","description":"Existing source inspected","check_ids":[],"allow_non_execution":true}],"checks":[]}`
	config.In = strings.NewReader(plan)
	if err := Execute(t.Context(), []string{"task", "start", "--plan", "-"}, config); err != nil {
		t.Fatal(err)
	}
	var record taskflow.Record
	if err := json.Unmarshal(out.Bytes(), &record); err != nil {
		t.Fatal(err)
	}
	canonicalRepo, err := filepath.EvalSymlinks(repo)
	if err != nil {
		t.Fatal(err)
	}
	canonicalHome, err := filepath.EvalSymlinks(home)
	if err != nil {
		t.Fatal(err)
	}
	if record.Baseline.Root != canonicalRepo || !strings.HasPrefix(record.Directory, filepath.Join(canonicalHome, ".codex", "workflow-tasks")) {
		t.Fatalf("wrong project/storage: %+v", record)
	}
	out.Reset()
	if err := Execute(t.Context(), []string{"task", "verify", "--task", record.Directory}, config); err == nil {
		t.Fatal("incomplete task was completed")
	}
	var gate taskflow.Verification
	if err := json.Unmarshal(out.Bytes(), &gate); err != nil || gate.Complete || len(gate.Problems) == 0 {
		t.Fatalf("missing gate problems: %s %v", out.String(), err)
	}
	hash := sha256.Sum256(data)
	ref := taskflow.SourceRef{Path: "source.txt", StartLine: 1, EndLine: 1, SHA256: hex.EncodeToString(hash[:])}
	input := taskflow.AssessmentInput{Requirements: []taskflow.Assessment{{ID: "source", Status: "satisfied", Evidence: []taskflow.SourceRef{ref}, CheckIDs: []string{}, NonExecutionReason: "Read-only source inspection; no executable behavior changed."}}, Decision: &taskflow.Decision{Status: "resolved", Reason: "Actual source reference establishes this small inspection result.", Evidence: []taskflow.SourceRef{ref}, CheckIDs: []string{}, NonExecutionReason: "Read-only source inspection; no executable behavior changed."}}
	encoded, err := json.Marshal(input)
	if err != nil {
		t.Fatal(err)
	}
	config.In = bytes.NewReader(encoded)
	out.Reset()
	if err := Execute(t.Context(), []string{"task", "assess", "--task", record.Directory, "--input", "-"}, config); err != nil {
		t.Fatal(err)
	}
	out.Reset()
	if err := Execute(t.Context(), []string{"task", "verify", "--task", record.Directory}, config); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(out.Bytes(), &gate); err != nil || !gate.Complete {
		t.Fatalf("gate failed: %s %v", out.String(), err)
	}
	out.Reset()
	if err := Execute(t.Context(), []string{"--dry-run", "task", "show", "--task", record.Directory}, config); err != nil {
		t.Fatal(err)
	}
}

func TestTaskMutationsRejectInheritedDryRunBeforeWrites(t *testing.T) {
	for _, command := range []string{"start", "context", "run", "assess", "consult", "verify"} {
		t.Run(command, func(t *testing.T) {
			config, _, _, _ := testConfig(t)
			config.HomeDir = func() (string, error) { t.Fatal("dry-run accessed storage"); return "", nil }
			config.WorkingDir = config.HomeDir
			err := Execute(t.Context(), []string{"--dry-run", "task", command}, config)
			if err == nil || ExitCode(err) != 2 || !strings.Contains(err.Error(), "reject --dry-run") {
				t.Fatalf("dry-run was not rejected explicitly: %v", err)
			}
		})
	}
}

func TestTaskCLIRejectsUnknownPlanFields(t *testing.T) {
	config, _, _, _ := testConfig(t)
	config.In = strings.NewReader(`{"title":"x","kind":"small","commands_from_agents_md":true}`)
	if err := Execute(t.Context(), []string{"task", "start", "--plan", "-"}, config); err == nil || !strings.Contains(err.Error(), "unknown") {
		t.Fatalf("unknown plan accepted: %v", err)
	}
}

func TestTaskUnexpectedArgumentsUseUsageExitCode(t *testing.T) {
	for _, args := range [][]string{{"task", "unknown"}, {"task", "start", "unexpected"}, {"task", "show", "unexpected"}} {
		t.Run(strings.Join(args, "_"), func(t *testing.T) {
			config, _, _, _ := testConfig(t)
			config.HomeDir = func() (string, error) { t.Fatal("invalid arguments reached task execution"); return "", nil }
			config.WorkingDir = config.HomeDir
			if err := Execute(t.Context(), args, config); err == nil || ExitCode(err) != 2 {
				t.Fatalf("task usage %v returned %v (exit %d)", args, err, ExitCode(err))
			}
		})
	}
}

func TestTaskStoreUsesActiveCodexProfilePrecedence(t *testing.T) {
	base := t.TempDir()
	repo := filepath.Join(base, "repo")
	if err := os.Mkdir(repo, 0700); err != nil {
		t.Fatal(err)
	}
	defaultHome := filepath.Join(base, "default-home")
	explicitHome := filepath.Join(base, "explicit-home")
	envCodex := filepath.Join(base, "environment-codex")
	explicitCodex := filepath.Join(base, "explicit-codex")
	explicitStore := filepath.Join(base, "explicit-store")
	plan := `{"title":"Profile storage","kind":"small","requirements":[{"id":"source","description":"Read source","allow_non_execution":true}],"checks":[]}`
	cases := []struct {
		name, environment, want string
		flags                   []string
	}{
		{name: "default", want: filepath.Join(defaultHome, ".codex", "workflow-tasks")},
		{name: "explicit home", flags: []string{"--home", explicitHome}, want: filepath.Join(explicitHome, ".codex", "workflow-tasks")},
		{name: "environment beats home", environment: envCodex, flags: []string{"--home", explicitHome}, want: filepath.Join(envCodex, "workflow-tasks")},
		{name: "explicit Codex beats environment", environment: envCodex, flags: []string{"--home", explicitHome, "--codex-home", explicitCodex}, want: filepath.Join(explicitCodex, "workflow-tasks")},
		{name: "explicit store beats profile", environment: envCodex, flags: []string{"--home", explicitHome, "--codex-home", explicitCodex, "--store", explicitStore}, want: explicitStore},
	}
	for _, item := range cases {
		t.Run(item.name, func(t *testing.T) {
			config, out, _, _ := testConfig(t)
			config.In = strings.NewReader(plan)
			config.HomeDir = func() (string, error) {
				if item.name == "explicit store beats profile" {
					t.Fatal("explicit storage resolved a home")
				}
				return defaultHome, nil
			}
			config.WorkingDir = func() (string, error) { return repo, nil }
			config.Getenv = func(key string) string {
				if item.name == "explicit store beats profile" {
					t.Fatal("explicit storage read environment")
				}
				if key != "CODEX_HOME" {
					t.Fatalf("unexpected environment query %s", key)
				}
				return item.environment
			}
			config.Resolve = func(string) (manageruntime.Locator, error) {
				t.Fatal("task storage acquired installer locator")
				return manageruntime.Locator{}, nil
			}
			args := append([]string{"task", "start", "--plan", "-"}, item.flags...)
			if err := Execute(t.Context(), args, config); err != nil {
				t.Fatal(err)
			}
			var record taskflow.Record
			if err := json.Unmarshal(out.Bytes(), &record); err != nil {
				t.Fatal(err)
			}
			canonical, err := filepath.EvalSymlinks(item.want)
			if err != nil {
				t.Fatal(err)
			}
			if filepath.Dir(record.Directory) != canonical {
				t.Fatalf("profile store got %s want %s", record.Directory, canonical)
			}
		})
	}
}
