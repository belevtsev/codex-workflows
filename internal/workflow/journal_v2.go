package workflow

import (
	json "encoding/json/v2"
	"errors"
	"fmt"
	"path/filepath"
	"slices"
)

func (i *Installer) mutationPaths(op Object) ([]string, error) {
	if op["kind"] == "personal_skill" {
		record, err := i.validatePersonalOperation(op)
		if err != nil {
			return nil, err
		}
		paths := []string{record.OriginPath, record.BackupPath, record.RegistrationPath}
		for a, left := range paths {
			for b := a + 1; b < len(paths); b++ {
				right := paths[b]
				if a == 0 && b == 2 && left == right {
					continue
				}
				if pathsOverlap(left, right) {
					return nil, errors.New("personal operation mutation paths overlap")
				}
			}
		}
		if record.OriginPath == record.RegistrationPath {
			paths = paths[:2]
		}
		return paths, nil
	}
	paths := []string{text(op["path"])}
	if op["kind"] == "rename" {
		paths = append(paths, text(op["destination"]))
	}
	return paths, nil
}

func pathsOverlap(a, b string) bool {
	return suiteWithin(a, b) || suiteWithin(b, a)
}

func (i *Installer) validateMutationPaths(ops []any, field string) error {
	var previous []string
	for _, raw := range ops {
		paths, err := i.mutationPaths(object(raw))
		if err != nil {
			return err
		}
		for _, target := range paths {
			if target == "" || Normalize(target) != target {
				return errors.New("unsafe journal mutation path")
			}
			if err := realDirectory(filepath.Dir(target), false); err != nil {
				return err
			}
			if slices.ContainsFunc(previous, func(other string) bool { return pathsOverlap(target, other) }) {
				return fmt.Errorf("overlapping mutation paths in %s: %s", field, target)
			}
		}
		previous = append(previous, paths...)
	}
	return nil
}

func stateFromObservation(ob Object) (Object, error) {
	if ob["kind"] != "file" {
		return nil, nil
	}
	data, err := decode(ob["data"])
	if err != nil {
		return nil, err
	}
	var state Object
	if err = json.Unmarshal(data, &state); err != nil {
		return nil, err
	}
	return state, nil
}

func (i *Installer) transactionVersion(ops []Object) int {
	if i.runtimeProtocol == "cw-manager-v6" || i.AdoptPersonalSkills {
		return 2
	}
	for _, op := range ops {
		if op["kind"] == "personal_skill" {
			return 2
		}
		if op["path"] == i.statePath {
			for _, side := range []string{"after", "before"} {
				state, err := stateFromObservation(object(op[side]))
				if err == nil && integer(state["version"]) == 2 {
					return 2
				}
			}
		}
	}
	return 1
}

func (i *Installer) verifyRecoveryRuntime(identity RuntimeIdentity) error {
	verified, err := i.runtimeRelease(identity.Revision)
	if err != nil {
		return err
	}
	if verified != identity {
		return errors.New("recovery runtime identity differs from its immutable receipt")
	}
	receipt, err := readJSON(filepath.Join(i.runtimeDir(identity.Revision), "receipt.json"))
	if err != nil || integer(receipt["version"]) != 2 || receipt["manager_protocol"] != "cw-manager-v6" {
		return errors.New("version-two journal requires a staged native v6 recovery runtime")
	}
	protocol, err := i.inspectRuntimeProtocol(filepath.Join(i.runtimeDir(identity.Revision), "cw"))
	if err != nil || protocol != "cw-manager-v6" {
		return errors.New("staged recovery runtime does not support the v6 manager protocol")
	}
	return nil
}

func (i *Installer) recoveryRuntimeFor(ops []Object) (RuntimeIdentity, error) {
	if i.runtimeProtocol == "cw-manager-v6" && validRuntimeIdentity(i.RuntimeIdentity) {
		return i.RuntimeIdentity, i.verifyRecoveryRuntime(i.RuntimeIdentity)
	}
	for _, op := range ops {
		if op["path"] != i.statePath {
			continue
		}
		for _, side := range []string{"after", "before"} {
			state, err := stateFromObservation(object(op[side]))
			if err != nil {
				return RuntimeIdentity{}, err
			}
			manager := object(state["manager"])
			if manager == nil {
				continue
			}
			var identity RuntimeIdentity
			if err = json.Unmarshal(legacyJSON(manager["runtime"]), &identity, json.RejectUnknownMembers(true)); err != nil {
				return identity, err
			}
			return identity, i.verifyRecoveryRuntime(identity)
		}
	}
	return RuntimeIdentity{}, errors.New("version-two journal has no verified staged recovery runtime")
}
