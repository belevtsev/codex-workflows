package workflow

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json/jsontext"
	"encoding/json/v2"
	"errors"
	"io"
	"math"
	"math/big"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const consultEndpoint = "https://api.typesafe.ai/v1/systemone"
const consultMaximumResponse = 1024 * 1024
const consultSumTolerance = 1e-6

type consultOptions struct {
	transport http.RoundTripper
	deadline  time.Duration
}

func consultChoice(value any) error {
	question, err := suiteMapping(value, "question", "type", "instructions", "criteria")
	if err != nil {
		return err
	}
	if question["type"] != "choice" {
		return errors.New("only Choice questions are supported")
	}
	if !policyDescription(question["instructions"]) {
		return errors.New("empty or invalid description")
	}
	criteria, err := suiteMapping(question["criteria"], "criteria")
	if err != nil || len(criteria) < 2 {
		return errors.New("Choice needs at least two options")
	}
	for name, value := range criteria {
		if strings.TrimSpace(name) == "" {
			return errors.New("invalid option ID")
		}
		if !policyDescription(value) {
			return errors.New("empty or invalid description")
		}
	}
	return nil
}

func consultPrepare(value any, model string) (Object, error) {
	request, err := suiteMapping(value, "request")
	if err != nil {
		return nil, err
	}
	if len(request) != 2 && len(request) != 3 {
		return nil, errors.New("invalid request fields")
	}
	if _, ok := request["state"]; !ok {
		return nil, errors.New("invalid request fields")
	}
	if _, ok := request["questions"]; !ok {
		return nil, errors.New("invalid request fields")
	}
	if requested, present := request["model"]; present {
		if requested != model {
			return nil, errors.New("request conflicts with pinned model")
		}
	} else if len(request) != 2 {
		return nil, errors.New("invalid request fields")
	}
	if !policyJSONValue(request["state"]) {
		return nil, errors.New("unsupported JSON state")
	}
	questions, err := suiteMapping(request["questions"], "questions")
	if err != nil || len(questions) == 0 {
		return nil, errors.New("questions must be a nonempty mapping")
	}
	for name, value := range questions {
		if strings.TrimSpace(name) == "" {
			return nil, errors.New("invalid question ID")
		}
		if err := consultChoice(value); err != nil {
			return nil, err
		}
	}
	return Object{"model": model, "state": request["state"], "questions": questions}, nil
}

func consultProbability(value any) (float64, bool) {
	var number float64
	switch value := value.(type) {
	case int:
		number = float64(value)
	case int64:
		number = float64(value)
	case uint64:
		number = float64(value)
	case float64:
		number = value
	case *big.Int:
		if !value.IsInt64() {
			return 0, false
		}
		number = float64(value.Int64())
	default:
		return 0, false
	}
	return number, !math.IsNaN(number) && !math.IsInf(number, 0) && number >= 0 && number <= 1
}

func consultTokens(value any) bool {
	switch value := value.(type) {
	case int:
		return value >= 0
	case int64:
		return value >= 0
	case uint64:
		return true
	case *big.Int:
		return value.Sign() >= 0
	default:
		return false
	}
}

func consultResponse(value any, prepared Object) (Object, error) {
	response, err := suiteMapping(value, "response")
	if err != nil {
		return nil, err
	}
	if response["model"] != prepared["model"] {
		return nil, errors.New("resolved model differs from pinned model")
	}
	questions := prepared["questions"].(Object)
	answers, err := suiteMapping(response["answers"], "answers")
	if err != nil || len(answers) != len(questions) {
		return nil, errors.New("invalid answer IDs")
	}
	validated := Object{}
	for questionID, value := range questions {
		answer, err := suiteMapping(answers[questionID], "answer")
		if err != nil || answer["type"] != "choice" {
			return nil, errors.New("invalid answer type")
		}
		options := value.(Object)["criteria"].(Object)
		choice, ok := answer["choice"].(string)
		if _, present := options[choice]; !ok || !present {
			return nil, errors.New("invalid chosen option")
		}
		probabilities, err := suiteMapping(answer["probabilities"], "probabilities")
		if err != nil || len(probabilities) != len(options) {
			return nil, errors.New("invalid probability option IDs")
		}
		var sum, compensation, maximum float64
		for option := range options {
			probability, ok := consultProbability(probabilities[option])
			if !ok {
				return nil, errors.New("invalid probability or confidence")
			}
			adjusted := probability - compensation
			next := sum + adjusted
			compensation = (next - sum) - adjusted
			sum = next
			maximum = max(maximum, probability)
		}
		if math.Abs(sum-1) > consultSumTolerance {
			return nil, errors.New("invalid probability distribution")
		}
		selected, _ := consultProbability(probabilities[choice])
		if selected != maximum {
			return nil, errors.New("chosen option is not a maximum")
		}
		if _, ok := consultProbability(answer["confidence"]); !ok {
			return nil, errors.New("invalid probability or confidence")
		}
		validated[questionID] = Object{
			"type": "choice", "choice": choice, "probabilities": probabilities, "confidence": answer["confidence"],
		}
	}
	usage, err := suiteMapping(response["usage"], "usage")
	if err != nil {
		return nil, errors.New("invalid response usage")
	}
	safeUsage := Object{}
	for _, field := range []string{"input_tokens", "output_tokens"} {
		if !consultTokens(usage[field]) {
			return nil, errors.New("invalid token usage")
		}
		safeUsage[field] = usage[field]
	}
	return Object{"model": response["model"], "answers": validated, "usage": safeUsage}, nil
}

func consultOutputEligible(outputPath string) error {
	if outputPath == "" {
		return errors.New("cannot create a new output file")
	}
	if _, err := os.Lstat(outputPath); !errors.Is(err, os.ErrNotExist) {
		return errors.New("cannot create a new output file")
	}
	info, err := os.Stat(filepath.Dir(outputPath))
	if err != nil || !info.IsDir() {
		return errors.New("cannot create a new output file")
	}
	return nil
}

func consultFailure(record Object, category string) {
	record["status"] = "unavailable"
	record["error"] = Object{"category": category}
}

func consultTimeout(ctx context.Context, err error) bool {
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return true
	}
	if timeout, ok := errors.AsType[net.Error](err); ok {
		return timeout.Timeout()
	}
	return false
}

func consultTransport(deadline time.Duration) *http.Transport {
	return &http.Transport{
		Proxy: http.ProxyFromEnvironment,
		DialContext: (&net.Dialer{
			Timeout: deadline,
		}).DialContext,
		DisableKeepAlives:     true,
		TLSHandshakeTimeout:   deadline,
		ResponseHeaderTimeout: deadline,
		// One nonreplayable HTTP/1 POST avoids automatic HTTP/2 stream retries.
		TLSNextProto: map[string]func(string, *tls.Conn) http.RoundTripper{},
	}
}

func consultSend(prepared Object, credential string, options consultOptions) Object {
	started := time.Now()
	record := Object{"request": prepared, "requested_model": prepared["model"], "duration_seconds": 0.0}
	if credential == "" {
		consultFailure(record, "missing_credential")
		return record
	}
	ctx, cancel := context.WithTimeout(context.Background(), options.deadline)
	defer cancel()
	defer func() { record["duration_seconds"] = math.Round(time.Since(started).Seconds()*1e6) / 1e6 }()
	payload, err := json.Marshal(prepared)
	if err != nil {
		consultFailure(record, "invalid_response")
		return record
	}
	outgoing, err := http.NewRequestWithContext(ctx, http.MethodPost, consultEndpoint, io.NopCloser(bytes.NewReader(payload)))
	if err != nil {
		consultFailure(record, "network_error")
		return record
	}
	outgoing.ContentLength = int64(len(payload))
	outgoing.Header.Set("Content-Type", "application/json")
	outgoing.Header.Set("Authorization", "Bearer "+credential)
	client := &http.Client{
		Transport: options.transport, Timeout: options.deadline,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse },
	}
	response, err := client.Do(outgoing)
	if err != nil {
		category := "network_error"
		if consultTimeout(ctx, err) {
			category = "timeout"
		}
		consultFailure(record, category)
		return record
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode > 299 {
		consultFailure(record, "http_error")
		if response.StatusCode >= 100 && response.StatusCode <= 599 {
			record["error"].(Object)["http_status"] = response.StatusCode
		}
		return record
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, consultMaximumResponse+1))
	if err != nil {
		category := "network_error"
		if consultTimeout(ctx, err) {
			category = "timeout"
		}
		consultFailure(record, category)
		return record
	}
	if len(body) > consultMaximumResponse {
		consultFailure(record, "invalid_response")
		return record
	}
	value, err := suiteJSON(body)
	if err != nil {
		consultFailure(record, "invalid_response")
		return record
	}
	result, err := consultResponse(value, prepared)
	if err != nil {
		consultFailure(record, "invalid_response")
		return record
	}
	record["status"], record["resolved_model"], record["result"], record["usage"] = "success", result["model"], result, result["usage"]
	return record
}

func consultWithOptions(policyRoot, requestPath, outputPath string, dryRun bool, options consultOptions) (Object, error) {
	root, err := suiteRoot(policyRoot, false)
	if err != nil {
		return nil, err
	}
	manifest, err := LoadManifest(root)
	if err != nil {
		return nil, err
	}
	policyPath, err := suiteRelativePath(root, manifest["model_policy"], "model_policy")
	if err != nil {
		return nil, err
	}
	policy, err := suiteModelPolicy(policyPath)
	if err != nil {
		return nil, err
	}
	consultation := policy["consultation"].(Object)
	data, err := suiteRead(requestPath, "consultation request")
	if err != nil {
		return nil, err
	}
	value, err := suiteJSON(data)
	if err != nil {
		return nil, err
	}
	prepared, err := consultPrepare(value, consultation["model"].(string))
	if err != nil {
		return nil, err
	}
	if err := consultOutputEligible(outputPath); err != nil {
		return nil, err
	}
	if dryRun {
		return Object{"status": "dry_run", "request": prepared, "requested_model": prepared["model"], "duration_seconds": 0.0}, nil
	}
	// Reserve the record before obtaining credentials or making a network call.
	// O_EXCL rejects an existing file or symlink and preserves earlier evidence.
	output, err := os.OpenFile(outputPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, errors.New("cannot create a new output file")
	}
	if options.deadline == 0 {
		options.deadline = 30 * time.Second
	}
	if options.transport == nil {
		transport := consultTransport(options.deadline)
		defer transport.CloseIdleConnections()
		options.transport = transport
	}
	record := consultSend(prepared, os.Getenv("TYPESAFE_API_KEY"), options)
	encoded, err := json.Marshal(record, jsontext.WithIndent("  "))
	if err != nil {
		output.Close()
		return nil, errors.New("cannot encode consultation record")
	}
	encoded = append(encoded, '\n')
	if _, err := output.Write(encoded); err != nil {
		output.Close()
		return nil, errors.New("cannot write consultation record")
	}
	if err := output.Close(); err != nil {
		return nil, errors.New("cannot close consultation record")
	}
	return record, nil
}

// Consult validates the maintained policy and a Choice-only request, performs
// one pinned consultation, and records only its sanitized response. An
// unavailable service yields an unavailable record; malformed inputs or output
// conflicts yield an error. Dry runs validate without creating output files.
func Consult(policyRoot, requestPath, outputPath string, dryRun bool) (Object, error) {
	return consultWithOptions(policyRoot, requestPath, outputPath, dryRun, consultOptions{})
}
