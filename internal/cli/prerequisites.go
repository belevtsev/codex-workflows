package cli

import (
	"os"
	"strings"

	"github.com/belevtsev/codex-workflows/internal/workflow"
)

// Detection deliberately does not execute optional tools: plugin startup can
// contact services or change caches. Version and subcommand gates belong to use.
type toolPrerequisite struct {
	Status string `json:"status"`
	Detail string `json:"detail"`
}

func skillPrerequisites(status workflow.Object, stat func(string) (os.FileInfo, error), lookup func(string) (string, error)) map[string]toolPrerequisite {
	report := make(map[string]toolPrerequisite)
	registrations, _ := status["registrations"].([]string)
	archify, docker := false, false
	for _, name := range registrations {
		archify = archify || name == "archify"
		docker = docker || strings.HasPrefix(name, "docker-")
	}
	detect := func(names ...string) string {
		for _, name := range names {
			if _, err := lookup(name); err == nil {
				return "detected"
			}
		}
		return "missing"
	}
	if archify {
		report["node"] = toolPrerequisite{detect("node"), "Archify requires Node.js 18+; detection does not verify its version"}
		browser := detect("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
		for _, path := range []string{"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"} {
			if info, err := stat(path); err == nil && info.Mode().IsRegular() && info.Mode().Perm()&0111 != 0 {
				browser = "detected"
			}
		}
		report["browser"] = toolPrerequisite{browser, "Archify browser verification requires Chrome or Chromium; detection does not prove rendering"}
		report["archify_generator_packages"] = toolPrerequisite{"not_checked", "Optional generators check Ajv and Simple Icons only when requested"}
	}
	if docker {
		report["docker"] = toolPrerequisite{detect("docker"), "Docker skills require their task's Docker CLI and runtime; daemon access is not checked"}
		report["docker_agent"] = toolPrerequisite{"not_checked", "Docker Agent availability is checked by the agent skill when used"}
		report["docker_sandboxes"] = toolPrerequisite{"not_checked", "Sandbox tools and platform support are checked by the relevant skill when used"}
	}
	return report
}
