package main

import (
	json "encoding/json/v2"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/belevtsev/codex-workflows/internal/workflow"
)

var version = "dev"
var revision = "unknown"
var builtAt = "unknown"
var help = map[string]string{
	"setup":       "Install or verify all ten skills, global instructions, Sol model defaults, and the cw shell command. Activates validated local HEAD; never fetches.",
	"status":      "Read and verify the local installed release, ownership, registrations and model defaults. Does not fetch or call connected services.",
	"update":      "Fetch origin/main, validate the exact commit, fast-forward clean nondivergent source and activate. --dry-run performs local checks without fetching. --no-checkout leaves source HEAD unchanged.",
	"rollback":    "Restore the previous validated installed release and its owned instructions/model defaults. Does not rewind the source checkout or GitHub.",
	"recover":     "Reverse owned changes left by an interrupted transaction. Preserve unrelated edits; refuse changed owned content. No pending journal means no-op.",
	"uninstall":   "Remove managed registrations/instructions/cw, restore adopted registrations and original model values. Preserve unrelated edits, credentials, source and cached releases.",
	"validate":    "Validate the source manifest, skill metadata, references, licenses and model policy without activating it.",
	"consult-jev": "Send one validated Choice request to pinned Jev; --request PATH --output PATH. Dry-run makes no writes/network request.",
	"version":     "Show binary version, source revision, build time and platform as JSON.",
}

func printHelp(topic string) error {
	fmt.Println("cw — Codex workflows\n\nUsage: cw [setup|status|update|rollback|recover|uninstall|validate|consult-jev|version|help] [options]")
	if topic != "" {
		description, ok := help[topic]
		if !ok {
			return fmt.Errorf("unknown help topic: %s", topic)
		}
		fmt.Printf("\n%s: %s\n", topic, description)
	} else {
		for _, name := range []string{"setup", "status", "update", "rollback", "recover", "uninstall", "validate", "consult-jev", "version"} {
			fmt.Printf("\n%s: %s\n", name, help[name])
		}
	}
	fmt.Println("\nOptions: --dry-run, --source PATH, --home PATH, --codex-home PATH, --state-dir PATH,\n         --shell auto|bash|zsh|none (setup only), --migrate-from PATH, --typesafe-legacy [PATH], --no-checkout,\n         --request PATH, --output PATH (consult-jev)\nMutations apply by default. Dry runs make no downloads or persistent writes.")
	return nil
}
func run(args []string) error {
	home, e := os.UserHomeDir()
	if e != nil {
		return e
	}
	source, e := os.Getwd()
	if e != nil {
		return e
	}
	options := workflow.Options{Paths: workflow.Paths{Home: home, Source: source}, Apply: true, Shell: "auto"}
	action := "setup"
	hasAction := false
	wantHelp := false
	topic := ""
	requestPath, outputPath := "", ""
	bootstrap := false
	dryRun := false
	explicitApply := false
	for index := 0; index < len(args); index++ {
		arg := args[index]
		name, value, inline := strings.Cut(arg, "=")
		take := func() (string, error) {
			if inline {
				return value, nil
			}
			index++
			if index >= len(args) {
				return "", fmt.Errorf("%s needs a value", name)
			}
			return args[index], nil
		}
		switch name {
		case "--help", "-h":
			wantHelp = true
		case "--json":
		case "--dry-run":
			dryRun = true
		case "--apply":
			explicitApply = true
		case "--bootstrap":
			bootstrap = true
		case "--no-checkout":
			options.NoCheckout = true
		case "--source", "--home", "--codex-home", "--state-dir", "--shell", "--migrate-from", "--request", "--output":
			v, e := take()
			if e != nil {
				return e
			}
			switch name {
			case "--request":
				requestPath = v
			case "--output":
				outputPath = v
			case "--source":
				options.Source = v
			case "--home":
				options.Home = v
			case "--codex-home":
				options.Codex = v
			case "--state-dir":
				options.State = v
			case "--shell":
				options.Shell = v
			case "--migrate-from":
				options.MigrateFrom = v
			}
		case "--typesafe-legacy":
			v := ""
			if inline {
				v = value
			} else if index+1 < len(args) && !strings.HasPrefix(args[index+1], "-") {
				index++
				v = args[index]
			}
			options.TypeSafeLegacy = new(v)
		default:
			if strings.HasPrefix(arg, "-") {
				return fmt.Errorf("unknown option: %s", arg)
			}
			if !hasAction {
				action = arg
				hasAction = true
			} else if action == "help" && topic == "" {
				topic = arg
			} else {
				return fmt.Errorf("unexpected argument: %s", arg)
			}
		}
	}
	if action == "help" {
		return printHelp(topic)
	}
	if wantHelp {
		if hasAction {
			return printHelp(action)
		}
		return printHelp("")
	}
	if action == "version" {
		return output(workflow.Object{"version": version, "revision": revision, "built_at": builtAt, "os": runtime.GOOS, "arch": runtime.GOARCH})
	}
	if options.Codex == "" {
		options.Codex = os.Getenv("CODEX_HOME")
		if options.Codex == "" {
			options.Codex = filepath.Join(options.Home, ".codex")
		}
	}
	if options.State == "" {
		state := os.Getenv("XDG_STATE_HOME")
		if state == "" {
			state = filepath.Join(options.Home, ".local", "state")
		}
		options.State = filepath.Join(state, "codex-workflows")
	}
	if bootstrap {
		options.Apply = explicitApply
	}
	if dryRun {
		options.Apply = false
	}
	if dryRun && explicitApply {
		return errors.New("--apply and --dry-run are mutually exclusive")
	}
	if options.Shell != "auto" && options.Shell != "bash" && options.Shell != "zsh" && options.Shell != "none" {
		return errors.New("--shell must be auto, bash, zsh or none")
	}
	if action != "setup" && options.Shell != "auto" {
		return errors.New("--shell is supported only for setup")
	}
	installer := workflow.NewInstaller(options)
	if action == "consult-jev" {
		if requestPath == "" || outputPath == "" {
			return errors.New("consult-jev requires --request and --output")
		}
		report, err := workflow.Consult(installer.Source, requestPath, outputPath, !options.Apply)
		if err != nil {
			return err
		}
		summary := workflow.Object{"status": report["status"], "requested_model": report["requested_model"], "duration_seconds": report["duration_seconds"], "output": outputPath}
		if err = output(summary); err != nil {
			return err
		}
		if report["status"] == "unavailable" {
			return errors.New("Jev consultation unavailable; see sanitized record")
		}
		return nil
	}
	if action == "validate" {
		report, e := workflow.ValidateSuite(installer.Source)
		if e != nil {
			return e
		}
		return output(report)
	}
	report, e := installer.Execute(action)
	if e != nil {
		return e
	}
	if bootstrap {
		return output(report)
	}
	var status workflow.Object
	if action == "recover" && !options.Apply && report["pending"] == true {
		status = workflow.Object{"recovery_pending": true}
	} else {
		status, e = installer.Status()
		if e != nil {
			return e
		}
	}
	return output(workflow.Object{"action": action, "dry_run": !options.Apply, "validation": "complete", "environment": workflow.Object{"kind": "native_go", "version": version, "revision": revision}, "result": report, "status": status, "jev_credential_present": os.Getenv("TYPESAFE_API_KEY") != "", "integrations": workflow.Object{"typesafe": workflow.Object{"credential_available": os.Getenv("TYPESAFE_API_KEY") != ""}}, "next_step": "Reload your shell startup file for cw and open a fresh Codex chat"})
}
func output(v any) error {
	data, e := json.Marshal(v, json.Deterministic(true))
	if e != nil {
		return e
	}
	_, e = fmt.Fprintln(os.Stdout, string(data))
	return e
}
func main() {
	if e := run(os.Args[1:]); e != nil {
		fmt.Fprintln(os.Stderr, "codex-workflows:", e)
		os.Exit(1)
	}
}
