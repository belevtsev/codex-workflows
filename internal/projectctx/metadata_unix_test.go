//go:build unix

package projectctx

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

func TestMetadataDoctorRejectsFIFOConfigWithoutOpeningIt(t *testing.T) {
	root, codex := t.TempDir(), t.TempDir()
	if err := syscall.Mkfifo(filepath.Join(codex, "config.toml"), 0600); err != nil {
		t.Fatal(err)
	}
	type result struct {
		report DoctorReport
		err    error
	}
	done := make(chan result, 1)
	go func() {
		report, err := Doctor(t.Context(), DoctorOptions{Repo: root, Home: t.TempDir(), CodexHome: codex, Timeout: 200 * time.Millisecond, LookPath: func(string) (string, error) { return "", os.ErrNotExist }})
		done <- result{report, err}
	}()
	select {
	case got := <-done:
		if got.err != nil || got.report.Checks["codex_config"].Status != "degraded" {
			t.Fatalf("FIFO was not rejected with qualified metadata: %+v %v", got.report.Checks["codex_config"], got.err)
		}
	case <-time.After(time.Second):
		t.Fatal("doctor blocked opening a non-regular configuration path")
	}
}
