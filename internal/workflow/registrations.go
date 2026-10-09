package workflow

import (
	"errors"
	"fmt"
	"path/filepath"
)

// RegistrationChange describes discovery changes without changing the deployed
// ownership or recovery schema. Unchanged registrations are omitted.
type RegistrationChange struct {
	Name       string `json:"name"`
	Action     string `json:"action"`
	BeforeRoot string `json:"before_root,omitempty"`
	AfterRoot  string `json:"after_root,omitempty"`
}

type registrationChangePlan struct {
	Changes    []RegistrationChange
	Records    Object
	Operations []Object
}

func compatibleRegistrationRoot(name, before, after string) bool {
	if before == after {
		return true
	}
	switch name {
	case "cc-skills-golang", "drawio-skill", "db-postgres", "typesafe-ai":
		legacy, modern := "vendor/"+name, "third_party/"+name
		return before == legacy && after == modern || before == modern && after == legacy
	}
	return false
}

// registrationPlan is shared by fresh installation, forward activation, and
// rollback. Typed ownership determines which changes are safe; existing raw
// origins are copied intact to retain historical v1 serialization and seals.
func (i *Installer) registrationPlan(s, manifest Object, rollback bool) (registrationChangePlan, error) {
	plan := registrationChangePlan{Changes: []RegistrationChange{}, Records: Object{}, Operations: []Object{}}
	next := object(manifest["registrations"])
	if len(next) == 0 {
		return plan, errors.New("registrations must be a nonempty mapping")
	}
	if err := realDirectory(i.skills, false); err != nil {
		return plan, err
	}
	var owned OwnershipRecord
	var err error
	if s != nil {
		owned, err = decodeOwnership(s)
		if err != nil {
			return plan, err
		}
	}
	for name, before := range owned.ManifestRegistrations {
		after, present := next[name]
		if !present {
			if !rollback {
				return plan, errors.New("registration names or roots changed; explicit uninstall and install are required")
			}
			item := owned.Registrations[name]
			if item.Original == nil || item.Original.Kind != "absent" {
				return plan, fmt.Errorf("rollback cannot remove adopted registration: %s", name)
			}
			continue
		}
		if !compatibleRegistrationRoot(name, before, text(after)) {
			return plan, errors.New("registration names or roots changed; explicit uninstall and install are required")
		}
	}
	additions := Object{}
	for _, name := range keys(next) {
		root, ok := next[name].(string)
		if !ok || !registrationName(name) || !registrationRoot(root) {
			return plan, errors.New("unsafe registration name or root")
		}
		if _, exists := owned.ManifestRegistrations[name]; !exists {
			if rollback {
				return plan, fmt.Errorf("rollback target is not a registration subset: %s", name)
			}
			additions[name] = root
		}
	}
	if err = i.duplicates(additions, s == nil); err != nil {
		return plan, err
	}
	migration := ""
	if s == nil && i.MigrateFrom != "" {
		migration = Normalize(i.MigrateFrom)
		if err = realDirectory(migration, false); err != nil {
			return plan, err
		}
	}
	for _, name := range keys(next) {
		root := text(next[name])
		beforeRoot, exists := owned.ManifestRegistrations[name]
		path, target := filepath.Join(i.skills, name), i.target(root)
		if !exists {
			before, err := observe(path)
			if err != nil {
				return plan, err
			}
			if before["kind"] != "absent" && (s != nil || before["kind"] != "symlink" || migration == "" || normalizeAlias(text(before["target"])) != normalizeAlias(filepath.Join(migration, root))) {
				return plan, fmt.Errorf("unrelated occupied registration: %s", path)
			}
			plan.Records[name] = Object{"target": target, "original": before}
			plan.Operations = append(plan.Operations, pathOperation(path, before, Object{"kind": "symlink", "target": target}, "registration:"+name))
			plan.Changes = append(plan.Changes, RegistrationChange{Name: name, Action: "add", AfterRoot: root})
			continue
		}
		item := clone(object(object(s["registrations"])[name]))
		if beforeRoot != root {
			plan.Operations = append(plan.Operations, pathOperation(path, Object{"kind": "symlink", "target": item["target"]}, Object{"kind": "symlink", "target": target}, "registration:"+name))
			plan.Changes = append(plan.Changes, RegistrationChange{Name: name, Action: "move", BeforeRoot: beforeRoot, AfterRoot: root})
		}
		item["target"] = target
		plan.Records[name] = item
	}
	for _, name := range keys(object(s["registrations"])) {
		if _, present := next[name]; present {
			continue
		}
		item := owned.Registrations[name]
		before := Object{"kind": "symlink", "target": item.Target}
		actual, err := observe(filepath.Join(i.skills, name))
		if err != nil {
			return plan, err
		}
		if !equal(actual, before) {
			return plan, fmt.Errorf("owned registration changed: %s", name)
		}
		plan.Operations = append(plan.Operations, pathOperation(filepath.Join(i.skills, name), before, Object{"kind": "absent"}, "registration:"+name))
		plan.Changes = append(plan.Changes, RegistrationChange{Name: name, Action: "remove", BeforeRoot: owned.ManifestRegistrations[name]})
	}
	return plan, nil
}

// Recheck discovery conflicts immediately before journaling and each creation.
// Other discovery roots are external to the manager's installation lock.
func (i *Installer) registrationAdditionCheck(ops []Object) error {
	additions := Object{}
	legacy := false
	for _, op := range ops {
		path := text(op["path"])
		if op["kind"] == "rename" && path == i.legacyPath() && op["destination"] == filepath.Join(i.State, "backups", "typesafe-ai") {
			legacy = true
		}
		if op["kind"] == "path" && filepath.Dir(path) == i.skills && object(op["before"])["kind"] == "absent" && object(op["after"])["kind"] == "symlink" {
			actual, err := observe(path)
			if err != nil {
				return err
			}
			if !equal(actual, op["before"]) {
				return fmt.Errorf("unrelated occupied registration: %s", path)
			}
			additions[filepath.Base(path)] = true
		}
	}
	if len(additions) == 0 {
		return nil
	}
	return i.duplicates(additions, legacy)
}
