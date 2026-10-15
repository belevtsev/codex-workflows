package cli

import (
	json "encoding/json/v2"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/belevtsev/codex-workflows/internal/taskflow"
	"github.com/spf13/cobra"
)

func addTaskCommands(root *cobra.Command, config Config, _ options) {
	noArgs := func(cmd *cobra.Command, args []string) error {
		if err := cobra.NoArgs(cmd, args); err != nil {
			return usage(err)
		}
		return nil
	}
	task := &cobra.Command{Use: "task", Short: "Record source-bound requirements, checks and task completion", Args: noArgs, RunE: func(cmd *cobra.Command, _ []string) error { return cmd.Help() }}
	root.AddCommand(task)
	output := func(cmd *cobra.Command, value any) error {
		data, err := json.Marshal(value, json.Deterministic(true))
		if err != nil {
			return err
		}
		_, err = fmt.Fprintln(cmd.OutOrStdout(), string(data))
		return err
	}
	read := func(cmd *cobra.Command, path string, value any) error {
		if path == "" {
			return usage(errors.New("a JSON input file is required"))
		}
		var reader io.Reader = cmd.InOrStdin()
		if path != "-" {
			file, err := os.Open(path)
			if err != nil {
				return err
			}
			defer file.Close()
			reader = file
		}
		return taskflow.Decode(reader, value)
	}
	guard := func(cmd *cobra.Command) error {
		dryRun, _ := root.PersistentFlags().GetBool("dry-run")
		if dryRun {
			return usage(errors.New("task state commands reject --dry-run; no files or checks were changed"))
		}
		return nil
	}
	var repo, planFile, store string
	start := &cobra.Command{Use: "start", Short: "Capture a baseline and an explicit JSON requirement/check plan", Args: noArgs, RunE: func(cmd *cobra.Command, _ []string) error {
		if err := guard(cmd); err != nil {
			return err
		}
		var plan taskflow.Plan
		if err := read(cmd, planFile, &plan); err != nil {
			return err
		}
		selected := repo
		if selected == "" {
			var err error
			selected, err = config.WorkingDir()
			if err != nil {
				return err
			}
		}
		chosenStore := store
		if chosenStore == "" {
			codexHome, _ := root.PersistentFlags().GetString("codex-home")
			if codexHome == "" {
				codexHome = config.Getenv("CODEX_HOME")
			}
			if codexHome == "" {
				home, _ := root.PersistentFlags().GetString("home")
				if home == "" {
					var err error
					home, err = config.HomeDir()
					if err != nil {
						return err
					}
				}
				codexHome = filepath.Join(home, ".codex")
			}
			chosenStore = filepath.Join(codexHome, "workflow-tasks")
		}
		record, err := taskflow.Start(cmd.Context(), selected, chosenStore, plan)
		if err != nil {
			return err
		}
		return output(cmd, record)
	}}
	start.Flags().StringVar(&repo, "repo", "", "Selected project directory (default: current working directory)")
	start.Flags().StringVar(&planFile, "plan", "", "Explicit plan JSON file, or - for standard input")
	start.Flags().StringVar(&store, "store", "", "Private task storage directory outside the target project")
	task.AddCommand(start)
	var contextTask, phase string
	contextCommand := &cobra.Command{Use: "context", Short: "Emit the exact before/final source context for shared adviser state", Args: noArgs, RunE: func(cmd *cobra.Command, _ []string) error {
		if err := guard(cmd); err != nil {
			return err
		}
		value, err := taskflow.PrepareContext(cmd.Context(), contextTask, phase)
		if err != nil {
			return err
		}
		return output(cmd, value)
	}}
	contextCommand.Flags().StringVar(&contextTask, "task", "", "Task directory returned by start")
	contextCommand.Flags().StringVar(&phase, "phase", "", "before or final")
	task.AddCommand(contextCommand)
	var runTask, check string
	run := &cobra.Command{Use: "run", Short: "Execute one planned argv check with bounded private logs", Args: noArgs, RunE: func(cmd *cobra.Command, _ []string) error {
		if err := guard(cmd); err != nil {
			return err
		}
		value, err := taskflow.Run(cmd.Context(), runTask, check)
		if value.ID != "" {
			if outputErr := output(cmd, value); outputErr != nil {
				return outputErr
			}
		}
		return err
	}}
	run.Flags().StringVar(&runTask, "task", "", "Task directory returned by start")
	run.Flags().StringVar(&check, "check", "", "Check ID from the immutable explicit plan")
	task.AddCommand(run)
	var assessTask, assessmentFile string
	assess := &cobra.Command{Use: "assess", Short: "Record acceptance and Codex decisions against actual source/check references", Args: noArgs, RunE: func(cmd *cobra.Command, _ []string) error {
		if err := guard(cmd); err != nil {
			return err
		}
		var input taskflow.AssessmentInput
		if err := read(cmd, assessmentFile, &input); err != nil {
			return err
		}
		value, err := taskflow.Assess(cmd.Context(), assessTask, input)
		if err != nil {
			return err
		}
		return output(cmd, value)
	}}
	assess.Flags().StringVar(&assessTask, "task", "", "Task directory returned by start")
	assess.Flags().StringVar(&assessmentFile, "input", "", "Assessment JSON file, or - for standard input")
	task.AddCommand(assess)
	var consultTask, consultPhase, consultFile string
	consult := &cobra.Command{Use: "consult", Short: "Preserve and validate a version-three raw/adjudicated adviser artifact", Args: noArgs, RunE: func(cmd *cobra.Command, _ []string) error {
		if err := guard(cmd); err != nil {
			return err
		}
		if consultFile == "" || consultFile == "-" {
			return usage(errors.New("consult needs a distinct original artifact file via --input"))
		}
		value, err := taskflow.AttachConsultation(cmd.Context(), consultTask, consultPhase, consultFile)
		if err != nil {
			return err
		}
		return output(cmd, value)
	}}
	consult.Flags().StringVar(&consultTask, "task", "", "Task directory returned by start")
	consult.Flags().StringVar(&consultPhase, "phase", "", "before or final")
	consult.Flags().StringVar(&consultFile, "input", "", "Original helper version-three consultation/adjudication JSON file")
	task.AddCommand(consult)
	var verifyTask string
	verify := &cobra.Command{Use: "verify", Short: "Gate completion against current source, requirements, checks and Codex decisions", Args: noArgs, RunE: func(cmd *cobra.Command, _ []string) error {
		if err := guard(cmd); err != nil {
			return err
		}
		value, err := taskflow.Verify(cmd.Context(), verifyTask)
		if value.TaskID != "" {
			if outputErr := output(cmd, value); outputErr != nil {
				return outputErr
			}
		}
		return err
	}}
	verify.Flags().StringVar(&verifyTask, "task", "", "Task directory returned by start")
	task.AddCommand(verify)
	var showTask string
	show := &cobra.Command{Use: "show", Short: "Read a task and validate its immutable revision chain", Args: noArgs, RunE: func(cmd *cobra.Command, _ []string) error {
		value, err := taskflow.Load(showTask)
		if err != nil {
			return err
		}
		return output(cmd, value)
	}}
	show.Flags().StringVar(&showTask, "task", "", "Task directory returned by start")
	task.AddCommand(show)
}
