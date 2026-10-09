package cli

import (
	"os"
	"testing"

	"github.com/belevtsev/codex-workflows/internal/workflow"
)

func TestOptionalPrerequisitesReportMissingToolsWithoutExecutingThem(t *testing.T) {
	missing := func(string) (string, error) { return "", os.ErrNotExist }
	noFile := func(string) (os.FileInfo, error) { return nil, os.ErrNotExist }
	report := skillPrerequisites(workflow.Object{"registrations": []string{"archify", "docker-agent-run"}}, noFile, missing)
	for _, name := range []string{"node", "browser", "docker"} {
		if report[name].Status != "missing" {
			t.Fatalf("missing %s not reported: %+v", name, report[name])
		}
	}
	if report["docker_agent"].Status != "not_checked" || report["docker_sandboxes"].Status != "not_checked" {
		t.Fatal("invented subcommand availability")
	}
	detected := func(string) (string, error) { return "/fixture/tool", nil }
	report = skillPrerequisites(workflow.Object{"registrations": []string{"archify"}}, noFile, detected)
	if report["node"].Status != "detected" || report["browser"].Status != "detected" {
		t.Fatal("available executable not detected")
	}
	if len(skillPrerequisites(workflow.Object{"registrations": []string{"typesafe-ai"}}, noFile, detected)) != 0 {
		t.Fatal("reported prerequisites for uninstalled skills")
	}
}
