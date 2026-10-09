package workflow

import (
	"bytes"
	"errors"
	"fmt"
	"maps"
	"os"
	"reflect"
	"strconv"
	"unicode/utf8"

	"github.com/pelletier/go-toml/v2"
	"github.com/pelletier/go-toml/v2/unstable"
)

var modelKeys = [...]string{"model", "model_reasoning_effort"}

type modelSpan struct {
	start, end, valueStart, valueEnd int
}

type modelDocument struct {
	data     []byte
	spans    map[string]modelSpan
	firstKey int
}

// modelParse validates the entire TOML document, then retains only the byte
// spans required to change the two owned root values. No user TOML is encoded.
func modelParse(data []byte) (modelDocument, error) {
	doc := modelDocument{data: data, spans: make(map[string]modelSpan), firstKey: -1}
	var values map[string]any
	if !utf8.Valid(data) || toml.Unmarshal(data, &values) != nil {
		return doc, errors.New("Codex config.toml is malformed; refusing to change it")
	}
	for _, key := range modelKeys {
		if value, found := values[key]; found {
			if _, ok := value.(string); !ok {
				return doc, errors.New("Codex root model defaults must be TOML strings")
			}
		}
	}
	var parser unstable.Parser
	parser.Reset(data)
	root := true
	for parser.NextExpression() {
		node := parser.Expression()
		if node.Kind != unstable.KeyValue && node.Kind != unstable.Table && node.Kind != unstable.ArrayTable {
			continue
		}
		keys := node.Key()
		keys.Next()
		keyNode := keys.Node()
		start := int(keyNode.Raw.Offset)
		for start > 0 && data[start-1] != '\n' {
			start--
		}
		if doc.firstKey == -1 {
			doc.firstKey = start
		}
		if node.Kind != unstable.KeyValue {
			root = false
			continue
		}
		key := string(keyNode.Data)
		if !root || keys.Next() || (key != modelKeys[0] && key != modelKeys[1]) {
			continue
		}
		value := node.Value()
		if value.Kind != unstable.String {
			return doc, errors.New("Codex root model defaults must be TOML strings")
		}
		valueStart := int(value.Raw.Offset)
		valueEnd := valueStart + int(value.Raw.Length)
		end := valueEnd
		for end < len(data) && data[end] != '\n' {
			end++
		}
		if end < len(data) {
			end++
		}
		doc.spans[key] = modelSpan{start: start, end: end, valueStart: valueStart, valueEnd: valueEnd}
	}
	if parser.Error() != nil {
		return doc, errors.New("Codex config.toml is malformed; refusing to change it")
	}
	return doc, nil
}

func modelMode(info os.FileInfo) int {
	mode := int(info.Mode().Perm())
	if info.Mode()&os.ModeSetuid != 0 {
		mode |= 0o4000
	}
	if info.Mode()&os.ModeSetgid != 0 {
		mode |= 0o2000
	}
	if info.Mode()&os.ModeSticky != 0 {
		mode |= 0o1000
	}
	return mode
}

func modelFileMode(mode int) os.FileMode {
	result := os.FileMode(mode & 0o777)
	if mode&0o4000 != 0 {
		result |= os.ModeSetuid
	}
	if mode&0o2000 != 0 {
		result |= os.ModeSetgid
	}
	if mode&0o1000 != 0 {
		result |= os.ModeSticky
	}
	return result
}

func modelRead(path string) (modelDocument, bool, int, error) {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		doc, parseErr := modelParse(nil)
		return doc, false, 0o600, parseErr
	}
	if err != nil {
		return modelDocument{}, false, 0, err
	}
	if !info.Mode().IsRegular() {
		return modelDocument{}, false, 0, errors.New("Codex config.toml is occupied or symlinked")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return modelDocument{}, false, 0, err
	}
	doc, err := modelParse(data)
	return doc, true, modelMode(info), err
}

func modelSnapshot(doc modelDocument) Object {
	result := Object{}
	for _, key := range modelKeys {
		if span, present := doc.spans[key]; present {
			result[key] = Object{"present": true, "representation": string(doc.data[span.valueStart:span.valueEnd])}
		} else {
			result[key] = Object{"present": false}
		}
	}
	return result
}

func modelFields(value Object, fields ...string) bool {
	if len(value) != len(fields) {
		return false
	}
	for _, field := range fields {
		if _, ok := value[field]; !ok {
			return false
		}
	}
	return true
}

func modelInteger(value any) (int, bool) {
	switch value := value.(type) {
	case int:
		return value, value >= 0 && value <= 0o7777
	case int64:
		return int(value), value >= 0 && value <= 0o7777
	case float64:
		return int(value), value >= 0 && value <= 0o7777 && value == float64(int(value))
	default:
		return 0, false
	}
}

func modelValidateSnapshot(value any) (Object, error) {
	values, ok := value.(map[string]any)
	if !ok || !modelFields(values, modelKeys[:]...) {
		return nil, errors.New("Corrupt model config ownership keys")
	}
	for _, key := range modelKeys {
		item, ok := values[key].(map[string]any)
		if !ok {
			return nil, errors.New("Corrupt model config ownership value")
		}
		present, ok := item["present"].(bool)
		if !ok {
			return nil, errors.New("Corrupt model config ownership value")
		}
		if !present {
			if !modelFields(item, "present") {
				return nil, errors.New("Corrupt absent model config ownership value")
			}
			continue
		}
		representation, ok := item["representation"].(string)
		if !ok || !modelFields(item, "present", "representation") {
			return nil, errors.New("Corrupt model config ownership representation")
		}
		doc, err := modelParse([]byte(key + " = " + representation + "\n"))
		if err != nil || len(doc.spans) != 1 || doc.firstKey != 0 {
			return nil, errors.New("Corrupt model config value representation")
		}
		var parsed map[string]any
		if toml.Unmarshal(doc.data, &parsed) != nil || len(parsed) != 1 {
			return nil, errors.New("Corrupt model config value representation")
		}
		// A representation is the value token alone, without comments or trivia.
		span := doc.spans[key]
		if string(doc.data[span.valueStart:span.valueEnd]) != representation {
			return nil, errors.New("Corrupt model config value representation")
		}
	}
	return values, nil
}

func ModelValidateMetadata(metadata Object) error {
	if !modelFields(metadata, "original", "expected", "original_exists") {
		return errors.New("Corrupt model config ownership metadata")
	}
	exists, ok := metadata["original_exists"].(bool)
	if !ok {
		return errors.New("Corrupt model config ownership metadata")
	}
	original, err := modelValidateSnapshot(metadata["original"])
	if err != nil {
		return err
	}
	expected, err := modelValidateSnapshot(metadata["expected"])
	if err != nil {
		return err
	}
	for _, key := range modelKeys {
		if !exists && original[key].(Object)["present"].(bool) {
			return errors.New("Corrupt absent model config origin")
		}
		if !expected[key].(Object)["present"].(bool) {
			return errors.New("Corrupt managed model defaults")
		}
	}
	return nil
}

func ModelVerify(path string, metadata Object) error {
	if err := ModelValidateMetadata(metadata); err != nil {
		return err
	}
	doc, exists, _, err := modelRead(path)
	if err != nil {
		return err
	}
	if !exists || !reflect.DeepEqual(modelSnapshot(doc), metadata["expected"]) {
		return errors.New("Owned model defaults changed; refusing to overwrite them")
	}
	return nil
}

func modelOperation(path string, before, after Object, beforeExists, afterExists bool, beforeMode, afterMode int, label string) Object {
	return Object{"kind": "model_config", "path": path, "before_keys": before, "after_keys": after,
		"before_exists": beforeExists, "after_exists": afterExists, "before_mode": beforeMode, "after_mode": afterMode, "label": label}
}

func ModelValidateOperation(value Object) error {
	if !modelFields(value, "kind", "path", "before_keys", "after_keys", "before_exists", "after_exists", "before_mode", "after_mode", "label") || value["kind"] != "model_config" {
		return errors.New("Corrupt keyed model config operation")
	}
	if _, ok := value["path"].(string); !ok {
		return errors.New("Corrupt model config operation path or label")
	}
	if value["label"] != "model-config" && value["label"] != "recover-model-config" {
		return errors.New("Corrupt model config operation path or label")
	}
	for _, field := range []string{"before_mode", "after_mode"} {
		if _, ok := modelInteger(value[field]); !ok {
			return errors.New("Corrupt model config operation mode")
		}
	}
	for _, side := range []string{"before", "after"} {
		exists, ok := value[side+"_exists"].(bool)
		if !ok {
			return errors.New("Corrupt keyed model config operation")
		}
		keys, err := modelValidateSnapshot(value[side+"_keys"])
		if err != nil {
			return err
		}
		for _, key := range modelKeys {
			if !exists && keys[key].(Object)["present"].(bool) {
				return errors.New("Corrupt absent model config operation")
			}
		}
	}
	return nil
}

func ModelPrepare(path string, defaults map[string]string, metadata Object) (Object, Object, error) {
	doc, exists, mode, err := modelRead(path)
	if err != nil {
		return nil, nil, err
	}
	if metadata != nil {
		if err := ModelVerify(path, metadata); err != nil {
			return nil, nil, err
		}
	}
	before := modelSnapshot(doc)
	after := Object{}
	for _, key := range modelKeys {
		value, ok := defaults[key]
		if !ok {
			return nil, nil, fmt.Errorf("Missing coordinator model default %s", key)
		}
		// TOML basic strings share the JSON escapes used by strconv.Quote,
		// except Go's hexadecimal escapes, which TOML requires as Unicode.
		representation := modelQuote(value)
		after[key] = Object{"present": true, "representation": representation}
	}
	owned := Object{"original": before, "original_exists": exists, "expected": after}
	if metadata != nil {
		owned = maps.Clone(metadata)
		owned["expected"] = after
	}
	if reflect.DeepEqual(before, after) && exists {
		return owned, nil, nil
	}
	return owned, modelOperation(path, before, after, exists, true, mode, mode, "model-config"), nil
}

func modelQuote(value string) string {
	quoted := strconv.Quote(value)
	var result bytes.Buffer
	for i := 0; i < len(quoted); i++ {
		if quoted[i] == '\\' && i+1 < len(quoted) {
			if quoted[i+1] == 'x' {
				result.WriteString("\\u00")
				result.WriteString(quoted[i+2 : i+4])
				i += 3
				continue
			}
			if quoted[i+1] == 'a' {
				result.WriteString("\\u0007")
				i++
				continue
			}
			if quoted[i+1] == 'v' {
				result.WriteString("\\u000b")
				i++
				continue
			}
			result.WriteByte(quoted[i])
			i++
			result.WriteByte(quoted[i])
			continue
		}
		result.WriteByte(quoted[i])
	}
	return result.String()
}

func ModelRemoval(path string, metadata Object) (Object, error) {
	if err := ModelVerify(path, metadata); err != nil {
		return nil, err
	}
	doc, exists, mode, err := modelRead(path)
	if err != nil {
		return nil, err
	}
	return modelOperation(path, modelSnapshot(doc), metadata["original"].(Object), exists, metadata["original_exists"].(bool), mode, mode, "model-config"), nil
}

func modelReplace(doc modelDocument, target Object) ([]byte, error) {
	if _, err := modelValidateSnapshot(target); err != nil {
		return nil, err
	}
	data := bytes.Clone(doc.data)
	for i := len(modelKeys) - 1; i >= 0; i-- {
		key := modelKeys[i]
		current, err := modelParse(data)
		if err != nil {
			return nil, err
		}
		item := target[key].(Object)
		span, present := current.spans[key]
		if item["present"].(bool) {
			representation := []byte(item["representation"].(string))
			if present {
				data = append(append(bytes.Clone(data[:span.valueStart]), representation...), data[span.valueEnd:]...)
			} else {
				position := max(current.firstKey, 0)
				line := []byte(key + " = " + string(representation) + "\n")
				data = append(append(bytes.Clone(data[:position]), line...), data[position:]...)
			}
		} else if present {
			replacement := []byte(nil)
			if commentAt := bytes.IndexByte(data[span.valueEnd:span.end], '#'); commentAt >= 0 {
				indentEnd := span.start
				for indentEnd < span.valueStart && (data[indentEnd] == ' ' || data[indentEnd] == '\t') {
					indentEnd++
				}
				replacement = append(bytes.Clone(data[span.start:indentEnd]), data[span.valueEnd+commentAt:span.end]...)
			}
			data = append(append(bytes.Clone(data[:span.start]), replacement...), data[span.end:]...)
		}
	}
	if _, err := modelParse(data); err != nil {
		return nil, err
	}
	return data, nil
}

func ModelRender(path string, value Object) ([]byte, os.FileMode, bool, error) {
	if err := ModelValidateOperation(value); err != nil {
		return nil, 0, false, err
	}
	doc, exists, mode, err := modelRead(path)
	if err != nil {
		return nil, 0, false, err
	}
	if !reflect.DeepEqual(modelSnapshot(doc), value["before_keys"]) {
		return nil, 0, false, errors.New("Owned model defaults changed during mutation; refusing to overwrite them")
	}
	data, err := modelReplace(doc, value["after_keys"].(Object))
	if err != nil {
		return nil, 0, false, err
	}
	remove := !value["after_exists"].(bool) && len(data) == 0
	beforeMode, _ := modelInteger(value["before_mode"])
	if remove && exists && mode != beforeMode {
		return nil, 0, false, errors.New("Codex config.toml mode changed before removal; refusing to delete it")
	}
	if !exists {
		mode, _ = modelInteger(value["after_mode"])
	}
	if remove {
		data = nil
	}
	return data, modelFileMode(mode), remove, nil
}

func ModelReversal(path string, value Object) (Object, error) {
	if err := ModelValidateOperation(value); err != nil {
		return nil, err
	}
	doc, exists, mode, err := modelRead(path)
	if err != nil {
		return nil, err
	}
	current := modelSnapshot(doc)
	if reflect.DeepEqual(current, value["before_keys"]) {
		return nil, nil
	}
	if !reflect.DeepEqual(current, value["after_keys"]) {
		return nil, errors.New("Owned model defaults changed; recovery refuses to overwrite them")
	}
	beforeMode, _ := modelInteger(value["before_mode"])
	return modelOperation(path, value["after_keys"].(Object), value["before_keys"].(Object), exists, value["before_exists"].(bool), mode, beforeMode, "recover-model-config"), nil
}

func ModelPending(path string, value Object) (Object, error) {
	if err := ModelValidateOperation(value); err != nil {
		return nil, err
	}
	doc, _, _, err := modelRead(path)
	if err != nil {
		return nil, err
	}
	current := modelSnapshot(doc)
	if reflect.DeepEqual(current, value["after_keys"]) {
		return nil, nil
	}
	if !reflect.DeepEqual(current, value["before_keys"]) {
		return nil, errors.New("Owned model defaults changed during interrupted recovery")
	}
	return value, nil
}
