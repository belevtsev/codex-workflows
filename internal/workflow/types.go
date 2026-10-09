package workflow

// Object retains the deployed version-one ownership and recovery JSON schema.
type Object = map[string]any

type Paths struct {
	Source string
	Home   string
	Codex  string
	State  string
}
