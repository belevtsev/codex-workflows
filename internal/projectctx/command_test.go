package projectctx

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"
)

func TestDoctorProbeHelper(t *testing.T) {
	switch os.Getenv("CW_DOCTOR_TEST_PROBE") {
	case "oversized":
		_, _ = os.Stdout.Write(bytes.Repeat([]byte("sensitive-output"), 10000))
		os.Exit(0)
	case "wait":
		time.Sleep(10 * time.Second)
		os.Exit(0)
	case "mcp":
		fmt.Println(`{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05"}}`)
		time.Sleep(10 * time.Second)
		os.Exit(0)
	case "mcp-delayed-open":
		reader := bufio.NewReader(os.Stdin)
		line, err := reader.ReadString('\n')
		if err != nil || !strings.Contains(line, `"method":"initialize"`) {
			os.Exit(16)
		}
		inputClosed := make(chan struct{}, 1)
		go func() {
			_, _ = reader.ReadByte()
			inputClosed <- struct{}{}
		}()
		select {
		case <-inputClosed:
			// Real asynchronous MCP servers stop when their input reaches EOF.
			os.Exit(17)
		case <-time.After(75 * time.Millisecond):
		}
		fmt.Println(`{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05"}}`)
		time.Sleep(10 * time.Second)
		os.Exit(0)
	}
}

func TestMCPProbeKeepsInputOpenUntilDelayedResponse(t *testing.T) {
	command := helperCommand("mcp-delayed-open")
	command.StopAfterJSONID = 1
	command.Stdin = "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\"}\n"
	ctx, cancel := context.WithTimeout(t.Context(), 2*time.Second)
	defer cancel()
	started := time.Now()
	result, err := executeBounded(ctx, command, 1024)
	if err != nil || !validMCPInitialization(result.Stdout) || time.Since(started) > time.Second {
		t.Fatalf("delayed MCP initialization did not retain its input stream or stop promptly: %v", err)
	}
	ctx, cancel = context.WithTimeout(t.Context(), 30*time.Millisecond)
	defer cancel()
	started = time.Now()
	_, err = executeBounded(ctx, command, 1024)
	if !errors.Is(err, context.DeadlineExceeded) || time.Since(started) > time.Second {
		t.Fatalf("waiting MCP input did not close on its deadline: %v", err)
	}
}

func helperCommand(mode string) Command {
	return Command{Executable: os.Args[0], Args: []string{"-test.run=^TestDoctorProbeHelper$"}, Env: []string{"CW_DOCTOR_TEST_PROBE=" + mode}}
}

func TestProbeOutputAndProcessLifetimeAreBounded(t *testing.T) {
	result, err := executeBounded(context.Background(), helperCommand("oversized"), 1234)
	if err != nil || !result.Truncated || len(result.Stdout) != 1234 {
		t.Fatalf("output was not bounded: len=%d truncated=%v err=%v", len(result.Stdout), result.Truncated, err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Millisecond)
	defer cancel()
	start := time.Now()
	_, err = executeBounded(ctx, helperCommand("wait"), 1024)
	if !errors.Is(err, context.DeadlineExceeded) || time.Since(start) > time.Second {
		t.Fatalf("probe cancellation did not stop and reap its process: %v", err)
	}
	command := helperCommand("mcp")
	command.StopAfterJSONID = 1
	ctx, cancel = context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	start = time.Now()
	result, err = executeBounded(ctx, command, 1024)
	if err != nil || !validMCPInitialization(result.Stdout) || time.Since(start) > time.Second {
		t.Fatalf("MCP initialization did not close its probe process: %v", err)
	}
}
