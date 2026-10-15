//go:build linux || darwin

package taskflow

import (
	"errors"
	"os"
	"os/exec"
	"syscall"
)

func configureCheckProcess(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	command.Cancel = func() error {
		if command.Process == nil {
			return os.ErrProcessDone
		}
		err := syscall.Kill(-command.Process.Pid, syscall.SIGKILL)
		if errors.Is(err, syscall.ESRCH) {
			return os.ErrProcessDone
		}
		return err
	}
}

func cleanupCheckProcess(command *exec.Cmd) {
	// A normally exiting wrapper can leave redirected descendants in its owned
	// process group. Stop that group before recording a terminal check result.
	if command.Process != nil {
		_ = syscall.Kill(-command.Process.Pid, syscall.SIGKILL)
	}
}
