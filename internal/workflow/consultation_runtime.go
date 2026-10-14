package workflow

import (
	"bytes"
	"context"
	json "encoding/json/v2"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// ConsultationRuntimePreparer provisions the isolated helper cache. Replacements
// let installer fixtures exercise activation without installing Python packages.
type ConsultationRuntimePreparer func(context.Context, string, bool) (Object, error)

const consultationPythonMinimum = "3.7"
const consultationPyYAMLRequirement = "PyYAML>=6,<7"

const consultationPythonProbe = `import json, sys
status = "ready" if sys.version_info >= (3, 7) else "python_unsupported"
if status == "ready":
    try:
        import multiprocessing, signal, venv
        from multiprocessing.connection import wait
        if not all(hasattr(multiprocessing.Process, name) for name in ("kill", "close")) or not hasattr(signal, "setitimer"):
            status = "runtime_unsupported"
    except Exception:
        status = "venv_unavailable"
print(json.dumps({"status": status, "python_version": ".".join(str(n) for n in sys.version_info[:3])}))
`

const consultationEnvironmentProbe = `import importlib.util, json, os, re, sys
status, version = "ready", ""
if sys.version_info < (3, 7):
    status = "python_unsupported"
else:
    try:
        import multiprocessing, signal
        from multiprocessing.connection import wait
        if not all(hasattr(multiprocessing.Process, name) for name in ("kill", "close")) or not hasattr(signal, "setitimer"):
            status = "runtime_unsupported"
    except Exception:
        status = "runtime_unsupported"
if status == "ready" and sys.prefix == sys.base_prefix:
    status = "not_virtualenv"
if status == "ready":
    try:
        import yaml
        version = yaml.__version__
        if os.path.commonpath((os.path.realpath(sys.prefix), os.path.realpath(yaml.__file__))) != os.path.realpath(sys.prefix):
            status = "pyyaml_external"
        elif not re.fullmatch(r"6(?:\.[0-9]+)*(?:\.post[0-9]+)?", version):
            status = "pyyaml_unsupported"
    except ModuleNotFoundError:
        status = "pyyaml_missing"
    except Exception:
        status = "pyyaml_import_failed"
print(json.dumps({"status": status, "python_version": ".".join(str(n) for n in sys.version_info[:3]),
                  "pyyaml_version": version, "pip_available": importlib.util.find_spec("pip") is not None}))
`

type consultationProbe struct {
	Status        string `json:"status"`
	PythonVersion string `json:"python_version"`
	PyYAMLVersion string `json:"pyyaml_version,omitempty"`
	PipAvailable  bool   `json:"pip_available,omitzero"`
}

type consultationRuntime struct {
	lookPath func(string) (string, error)
	run      func(context.Context, string, ...string) ([]byte, error)
}

var consultationPythonVersion = regexp.MustCompile(`^3\.([0-9]+)\.[0-9]+$`)
var consultationPyYAMLVersion = regexp.MustCompile(`^6(?:\.[0-9]+)*(?:\.post[0-9]+)?$`)
var errConsultationOutputLimit = errors.New("consultation subprocess output exceeds limit")

func (i *Installer) prepareConsultationRuntime() (Object, error) {
	return i.prepareConsultationRuntimeFor(i.Source)
}

func (i *Installer) prepareConsultationRuntimeFor(sourceRoot string) (Object, error) {
	path := filepath.Join(i.Home, ".venvs", "codex-decisions")
	defaults, err := SharedConfigDefaults(sourceRoot)
	if err != nil {
		return nil, err
	}
	if defaults == nil {
		report := consultationRuntimeReport(path, "not_required", false)
		report["managed"] = false
		return report, nil
	}
	if !i.Apply {
		return (consultationRuntime{}).prepare(i.Context, path, false)
	}
	prepare := i.PrepareConsultationRuntime
	if prepare == nil {
		prepare = (consultationRuntime{}).prepare
	}
	return prepare(i.Context, path, true)
}

func consultationRuntimeReport(path, status string, changed bool) Object {
	return Object{"managed": true, "path": path, "python": filepath.Join(path, "bin", "python"),
		"python_minimum": consultationPythonMinimum, "pyyaml_requirement": consultationPyYAMLRequirement,
		"status": status, "changed": changed}
}

func (r consultationRuntime) prepare(ctx context.Context, path string, apply bool) (Object, error) {
	if !filepath.IsAbs(path) || Normalize(path) != path {
		return nil, errors.New("consultation runtime requires an absolute clean environment path")
	}
	if err := realDirectory(path, false); err != nil {
		return nil, err
	}
	if !apply {
		return consultationRuntimeReport(path, "deferred", false), nil
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if r.lookPath == nil {
		r.lookPath = exec.LookPath
	}
	if r.run == nil {
		r.run = runConsultationProcess
	}
	ctx, cancel := context.WithTimeout(ctx, 3*time.Minute)
	defer cancel()
	interpreter := filepath.Join(path, "bin", "python")
	probe, err := r.environment(ctx, interpreter)
	if err != nil {
		return nil, err
	}
	if probe.Status == "ready" {
		return consultationReadyReport(path, probe, false), nil
	}
	base := ""
	if !consultationDependencyRepair(probe.Status) {
		base, err = r.python(ctx)
		if err != nil {
			return nil, err
		}
	}
	unlock, err := lockConsultationRuntime(path)
	if err != nil {
		return nil, err
	}
	defer unlock()
	// A concurrent installer may have completed the same device cache.
	probe, err = r.environment(ctx, interpreter)
	if err != nil {
		return nil, err
	}
	if probe.Status == "ready" {
		return consultationReadyReport(path, probe, false), nil
	}
	if base != "" {
		if _, err := r.command(ctx, time.Minute, base, "-I", "-B", "-m", "venv", path); err != nil {
			return nil, consultationFailure("venv", err, "use Python 3.7+ with venv and ensurepip support on PATH, then rerun cw install")
		}
		probe, err = r.environment(ctx, interpreter)
		if err != nil {
			return nil, err
		}
	}
	if !consultationDependencyRepair(probe.Status) && probe.Status != "ready" {
		return nil, consultationFailure("environment", nil, "the isolated Python environment is incomplete; use Python 3.7+ with venv support on PATH and rerun cw install")
	}
	if !probe.PipAvailable {
		if _, err := r.command(ctx, time.Minute, interpreter, "-I", "-B", "-m", "ensurepip", "--upgrade"); err != nil {
			return nil, consultationFailure("ensurepip", err, "use Python with ensurepip support, then rerun cw install")
		}
	}
	arguments := []string{"-I", "-B", "-m", "pip", "--isolated", "--disable-pip-version-check", "install", "--index-url", "https://pypi.org/simple", "--no-cache-dir"}
	if probe.Status == "pyyaml_import_failed" {
		arguments = append(arguments, "--force-reinstall")
	}
	if probe.Status == "pyyaml_external" {
		arguments = append(arguments, "--ignore-installed")
	}
	arguments = append(arguments, consultationPyYAMLRequirement)
	if _, err := r.command(ctx, 2*time.Minute, interpreter, arguments...); err != nil {
		return nil, consultationFailure("pip", err, "check PyPI connectivity and this interpreter's pip support, then rerun cw install")
	}
	probe, err = r.environment(ctx, interpreter)
	if err != nil {
		return nil, err
	}
	if probe.Status != "ready" {
		return nil, consultationFailure("verification", nil, "the isolated interpreter still cannot use PyYAML 6; repair its Python installation and rerun cw install")
	}
	return consultationReadyReport(path, probe, true), nil
}

func consultationDependencyRepair(status string) bool {
	return status == "pyyaml_missing" || status == "pyyaml_unsupported" || status == "pyyaml_import_failed" || status == "pyyaml_external"
}

func consultationReadyReport(path string, probe consultationProbe, changed bool) Object {
	report := consultationRuntimeReport(path, "ready", changed)
	report["python_version"], report["pyyaml_version"] = probe.PythonVersion, probe.PyYAMLVersion
	return report
}

func (r consultationRuntime) command(ctx context.Context, timeout time.Duration, path string, arguments ...string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	output, err := r.run(ctx, path, arguments...)
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	return output, err
}

func (r consultationRuntime) probe(ctx context.Context, interpreter, program string) (consultationProbe, error) {
	output, err := r.command(ctx, 10*time.Second, interpreter, "-I", "-B", "-c", program)
	if err != nil {
		return consultationProbe{}, consultationFailure("probe", err, "check that the selected Python interpreter can start, then rerun cw install")
	}
	var probe consultationProbe
	if err := json.Unmarshal(output, &probe, json.RejectUnknownMembers(true)); err != nil {
		return consultationProbe{}, consultationFailure("probe_protocol", nil, "the selected interpreter did not return a valid runtime probe")
	}
	version := consultationPythonVersion.FindStringSubmatch(probe.PythonVersion)
	if version == nil {
		return consultationProbe{}, consultationFailure("probe_protocol", nil, "the selected interpreter did not identify a Python 3 runtime")
	}
	minor, _ := strconv.Atoi(version[1])
	if probe.Status == "ready" && (minor < 7 || (program == consultationEnvironmentProbe && !consultationPyYAMLVersion.MatchString(probe.PyYAMLVersion))) {
		return consultationProbe{}, consultationFailure("probe_protocol", nil, "the selected interpreter reported unsupported Python or PyYAML versions")
	}
	return probe, nil
}

func (r consultationRuntime) environment(ctx context.Context, interpreter string) (consultationProbe, error) {
	if err := realDirectory(filepath.Dir(interpreter), false); err != nil {
		return consultationProbe{}, err
	}
	info, err := os.Stat(interpreter) // Venv interpreter symlinks are expected.
	if errors.Is(err, os.ErrNotExist) {
		return consultationProbe{Status: "environment_incomplete"}, nil
	}
	if err != nil {
		return consultationProbe{}, err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0o111 == 0 {
		return consultationProbe{Status: "environment_incomplete"}, nil
	}
	return r.probe(ctx, interpreter, consultationEnvironmentProbe)
}

func (r consultationRuntime) python(ctx context.Context) (string, error) {
	names := []string{"python3"}
	for minor := 15; minor >= 7; minor-- {
		names = append(names, fmt.Sprintf("python3.%d", minor))
	}
	seen := map[string]bool{}
	for _, name := range names {
		path, err := r.lookPath(name)
		if err != nil || seen[path] {
			continue
		}
		seen[path] = true
		probe, err := r.probe(ctx, path, consultationPythonProbe)
		if err != nil {
			if ctx.Err() != nil || errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
				return "", err
			}
			continue
		}
		if probe.Status == "ready" {
			return path, nil
		}
	}
	return "", consultationFailure("python_unavailable", nil, "put Python 3.7+ with the venv module on PATH, then rerun cw install")
}

func lockConsultationRuntime(path string) (func(), error) {
	parent := filepath.Dir(path)
	if err := realDirectory(parent, true); err != nil {
		return nil, err
	}
	lock := filepath.Join(parent, ".codex-decisions.lock")
	if info, err := os.Lstat(lock); err == nil && !info.Mode().IsRegular() {
		return nil, errors.New("unsafe consultation runtime lock")
	} else if err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}
	file, err := os.OpenFile(lock, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		file.Close()
		return nil, errors.New("another installer is preparing the consultation runtime; retry when it completes")
	}
	return func() { file.Close() }, nil
}

type consultationFailureError struct {
	stage, category, action string
	cause                   error
}

func (e *consultationFailureError) Error() string {
	return fmt.Sprintf("consultation runtime %s failed (%s); %s", e.stage, e.category, e.action)
}
func (e *consultationFailureError) Unwrap() error { return e.cause }

func consultationFailure(stage string, cause error, action string) error {
	category := "unavailable"
	switch {
	case errors.Is(cause, context.Canceled):
		category = "canceled"
	case errors.Is(cause, context.DeadlineExceeded):
		category = "timeout"
	case errors.Is(cause, errConsultationOutputLimit):
		category = "output_limit"
	case cause != nil:
		if _, ok := errors.AsType[*exec.ExitError](cause); ok {
			category = "process_failed"
		} else {
			category = "startup_failed"
		}
	}
	return &consultationFailureError{stage: stage, category: category, action: action, cause: cause}
}

// A named buffer avoids promoting ReaderFrom, which would bypass bounded Write.
type consultationOutput struct{ buffer bytes.Buffer }

func (output *consultationOutput) Write(data []byte) (int, error) {
	if output.buffer.Len()+len(data) > 32<<10 {
		return 0, errConsultationOutputLimit
	}
	return output.buffer.Write(data)
}

func runConsultationProcess(ctx context.Context, interpreter string, arguments ...string) ([]byte, error) {
	command := exec.CommandContext(ctx, interpreter, arguments...)
	command.WaitDelay = time.Second
	command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	command.Cancel = func() error {
		if err := syscall.Kill(-command.Process.Pid, syscall.SIGKILL); errors.Is(err, syscall.ESRCH) {
			return os.ErrProcessDone
		} else {
			return err
		}
	}
	command.Env = consultationProcessEnvironment(os.Environ())
	var output, diagnostics consultationOutput
	command.Stdout, command.Stderr = &output, &diagnostics
	err := command.Run()
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if errors.Is(err, exec.ErrWaitDelay) && command.Process != nil {
		_ = syscall.Kill(-command.Process.Pid, syscall.SIGKILL)
	}
	return output.buffer.Bytes(), err
}

func consultationProcessEnvironment(inherited []string) []string {
	environment := []string{"PIP_CONFIG_FILE=" + os.DevNull}
	for _, item := range inherited {
		key, _, _ := strings.Cut(item, "=")
		if key == "PATH" || key == "HOME" || key == "LANG" || strings.HasPrefix(key, "LC_") ||
			key == "TMPDIR" || key == "TMP" || key == "TEMP" || key == "SSL_CERT_FILE" || key == "SSL_CERT_DIR" ||
			key == "HTTP_PROXY" || key == "HTTPS_PROXY" || key == "NO_PROXY" || key == "http_proxy" || key == "https_proxy" || key == "no_proxy" {
			environment = append(environment, item)
		}
	}
	return environment
}
