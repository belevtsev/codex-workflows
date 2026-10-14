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
		if op["kind"] == "personal_skill" || op["kind"] == sharedConfigOperationKind {
			return 2
		}
		if op["path"] == i.statePath {
			for _, side := range []string{"after", "before"} {
				state, err := stateFromObservation(object(op[side]))
				if err == nil && (integer(state["version"]) == 2 || sharedConfigStateRequired(state)) {
					return 2
				}
			}
		}
	}
	return 1
}

func (i *Installer) sharedConfigRuntimeRequiredForOperations(ops []Object) (bool, error) {
	required := false
	for _, op := range ops {
		if op["kind"] == sharedConfigOperationKind {
			required = true
		}
		if op["path"] != i.statePath {
			continue
		}
		for _, side := range []string{"before", "after"} {
			state, err := stateFromObservation(object(op[side]))
			if err != nil {
				return false, err
			}
			required = required || sharedConfigStateRequired(state)
		}
	}
	return required, nil
}

func (i *Installer) verifySharedConfigRecoveryRuntime(identity RuntimeIdentity) error {
	if err := i.verifyRecoveryRuntime(identity); err != nil {
		return err
	}
	return i.verifySharedConfigRuntime(filepath.Join(i.runtimeDir(identity.Revision), "cw"))
}

// verifySharedConfigJournalRuntime checks both the forward transaction and any
// saved reversals before recovery starts changing owned paths.
func (i *Installer) verifySharedConfigJournalRuntime(journal Object) error {
	var operations []Object
	for _, field := range []string{"operations", "recovery_operations"} {
		for _, raw := range sequence(journal[field]) {
			operations = append(operations, object(raw))
		}
	}
	required, err := i.sharedConfigRuntimeRequiredForOperations(operations)
	if err != nil || !required {
		return err
	}
	if integer(journal["version"]) != 2 {
		return errors.New("shared Codex config requires a version-two recovery journal")
	}
	var identity RuntimeIdentity
	if err := json.Unmarshal(legacyJSON(journal["recovery_runtime"]), &identity, json.RejectUnknownMembers(true)); err != nil {
		return err
	}
	return i.verifySharedConfigRecoveryRuntime(identity)
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
	sharedConfig, err := i.sharedConfigRuntimeRequiredForOperations(ops)
	if err != nil {
		return RuntimeIdentity{}, err
	}
	verify := i.verifyRecoveryRuntime
	if sharedConfig {
		verify = i.verifySharedConfigRecoveryRuntime
	}
	if i.runtimeProtocol == "cw-manager-v6" && validRuntimeIdentity(i.RuntimeIdentity) {
		return i.RuntimeIdentity, verify(i.RuntimeIdentity)
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
			return identity, verify(identity)
		}
	}
	return RuntimeIdentity{}, errors.New("version-two journal has no verified staged recovery runtime")
}
