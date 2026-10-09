package main

import (
	"testing"
)

func TestDeveloperArgumentsRejectIncompleteOrUnknownCommands(t *testing.T) {
	for _, arguments := range [][]string{{"unknown"}, {"release"}, {"release", "unknown"}, {"release", "build"}, {"check", "unexpected"}, {"release", "build", "--version", "v1.0.1", "--revision", "0000000000000000000000000000000000000000", "--race"}} {
		if err := run(t.Context(), arguments); err == nil {
			t.Fatalf("incomplete developer command accepted: %v", arguments)
		}
	}
}
