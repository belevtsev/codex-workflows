package workflow

import (
	"context"
	"encoding/json/v2"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"gopkg.in/yaml.v3"
)

type consultRoundTripFunc func(*http.Request) (*http.Response, error)

func (roundTrip consultRoundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return roundTrip(request)
}

func consultTestRequest() Object {
	return Object{
		"state": Object{"evidence": "Acknowledgement was observed; recovery was not observed.", "nested": []any{nil, true, 3}},
		"questions": Object{"claim_support": Object{
			"type": "choice", "instructions": "Classify the claim using evidence.",
			"criteria": Object{"supported": "Evidence supports the claim.", "insufficient": "Evidence is incomplete."},
		}},
	}
}

func consultTestResponse() Object {
	return Object{
		"model": "jev-1.13.0",
		"answers": Object{"claim_support": Object{
			"type": "choice", "choice": "insufficient",
			"probabilities": Object{"supported": 0.1, "insufficient": 0.9}, "confidence": 0.8,
		}},
		"usage": Object{"input_tokens": 25, "output_tokens": 8},
	}
}

func consultTestPaths(t *testing.T) (*suiteFixture, string, string) {
	t.Helper()
	fixture := newSuiteFixture(t)
	request := fixture.write(t, "request.json", string(mustSuiteJSON(t, consultTestRequest())))
	return fixture, request, filepath.Join(fixture.root, "record.json")
}

func consultReadRecord(t *testing.T, output string) Object {
	t.Helper()
	data, err := os.ReadFile(output)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "fixture-secret") {
		t.Fatalf("record leaked unknown server fields or credentials: %s", data)
	}
	value, err := suiteJSON(data)
	if err != nil {
		t.Fatal(err)
	}
	return value.(Object)
}

func consultSyntheticTransport(t *testing.T, body string, calls *int) http.RoundTripper {
	t.Helper()
	return consultRoundTripFunc(func(request *http.Request) (*http.Response, error) {
		*calls++
		if request.URL.String() != consultEndpoint || request.Method != http.MethodPost || request.GetBody != nil {
			t.Errorf("unexpected replayable request: %s %s", request.Method, request.URL)
		}
		return &http.Response{StatusCode: 200, Header: http.Header{}, Body: io.NopCloser(strings.NewReader(body)), Request: request}, nil
	})
}

func TestConsultSuccessPreservesExactRequestAndSanitizesRecord(t *testing.T) {
	t.Setenv("TYPESAFE_API_KEY", "fixture-secret-token")
	fixture, requestPath, outputPath := consultTestPaths(t)
	response := consultTestResponse()
	response["unknown"] = "fixture-secret-token"
	response["usage"].(Object)["unknown"] = "fixture-secret-token"
	response["answers"].(Object)["claim_support"].(Object)["unknown"] = "fixture-secret-token"
	var requests atomic.Int64
	receivedRequests := make(chan Object, 1)
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		requests.Add(1)
		if request.Method != http.MethodPost || request.Header.Get("Authorization") != "Bearer fixture-secret-token" || request.Header.Get("Content-Type") != "application/json" {
			t.Error("incorrect HTTP method or required headers")
		}
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.Error(err)
			writer.WriteHeader(http.StatusBadRequest)
			return
		}
		value, err := suiteJSON(body)
		if err != nil {
			t.Error(err)
			writer.WriteHeader(http.StatusBadRequest)
			return
		}
		receivedRequests <- value.(Object)
		writer.Header().Set("Content-Type", "application/json")
		writer.Write(mustSuiteJSON(t, response))
	}))
	defer server.Close()
	serverURL, err := url.Parse(server.URL)
	if err != nil {
		t.Fatal(err)
	}
	transport := consultTransport(time.Second)
	defer transport.CloseIdleConnections()
	roundTrip := consultRoundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.URL.String() != consultEndpoint || request.GetBody != nil {
			t.Error("request endpoint changed or request became replayable")
		}
		copy := request.Clone(request.Context())
		copy.URL = serverURL.Clone()
		return transport.RoundTrip(copy)
	})
	record, err := consultWithOptions(fixture.root, requestPath, outputPath, false, consultOptions{transport: roundTrip, deadline: time.Second})
	if err != nil {
		t.Fatal(err)
	}
	if requests.Load() != 1 || record["status"] != "success" || record["resolved_model"] != "jev-1.13.0" {
		t.Fatalf("requests = %d, record = %#v", requests.Load(), record)
	}
	prepared := consultTestRequest()
	prepared["model"] = "jev-1.13.0"
	received := <-receivedRequests
	if !reflect.DeepEqual(received, prepared) || !reflect.DeepEqual(record["request"], prepared) {
		t.Fatalf("request changed: sent %#v, retained %#v", received, record["request"])
	}
	stored := consultReadRecord(t, outputPath)
	if !reflect.DeepEqual(stored["request"], prepared) || !reflect.DeepEqual(stored["usage"], Object{"input_tokens": 25, "output_tokens": 8}) {
		t.Fatalf("unexpected stored record: %#v", stored)
	}
	info, err := os.Stat(outputPath)
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("record permissions: %v, %v", info, err)
	}
}

func TestConsultDryRunAndMissingCredentials(t *testing.T) {
	t.Setenv("TYPESAFE_API_KEY", "")
	fixture, requestPath, outputPath := consultTestPaths(t)
	var calls int
	transport := consultSyntheticTransport(t, "", &calls)
	before := suiteSnapshot(t, fixture.root)
	record, err := consultWithOptions(fixture.root, requestPath, outputPath, true, consultOptions{transport: transport})
	if err != nil || record["status"] != "dry_run" || calls != 0 {
		t.Fatalf("dry run = %#v, error = %v, calls = %d", record, err, calls)
	}
	if after := suiteSnapshot(t, fixture.root); !reflect.DeepEqual(before, after) {
		t.Fatal("dry run wrote to the source or output")
	}
	record, err = consultWithOptions(fixture.root, requestPath, outputPath, false, consultOptions{transport: transport})
	if err != nil || record["status"] != "unavailable" || !reflect.DeepEqual(record["error"], Object{"category": "missing_credential"}) || calls != 0 {
		t.Fatalf("missing credential = %#v, error = %v, calls = %d", record, err, calls)
	}
	consultReadRecord(t, outputPath)
}

func TestConsultValidationAndOutputConflictsPrecedeNetwork(t *testing.T) {
	t.Setenv("TYPESAFE_API_KEY", "fixture-secret-token")
	for _, mutate := range []func(Object){
		func(request Object) { request["model"] = "jev-1.12.0" },
		func(request Object) { request["extra"] = "fixture-secret-token" },
		func(request Object) { request["questions"] = Object{} },
		func(request Object) { request["questions"].(Object)["claim_support"].(Object)["type"] = "noul" },
		func(request Object) {
			request["questions"].(Object)["claim_support"].(Object)["criteria"] = Object{"one": "Only one"}
		},
		func(request Object) { request["questions"].(Object)["claim_support"].(Object)["instructions"] = " " },
	} {
		fixture, requestPath, outputPath := consultTestPaths(t)
		request := consultTestRequest()
		mutate(request)
		fixture.write(t, "request.json", string(mustSuiteJSON(t, request)))
		var calls int
		_, err := consultWithOptions(fixture.root, requestPath, outputPath, false, consultOptions{transport: consultSyntheticTransport(t, "", &calls)})
		if err == nil || strings.Contains(err.Error(), "fixture-secret") || calls != 0 {
			t.Fatalf("invalid request error = %v, calls = %d", err, calls)
		}
		if _, err := os.Lstat(outputPath); !errors.Is(err, os.ErrNotExist) {
			t.Fatal("invalid request reserved an output file")
		}
	}
	for _, raw := range []string{`{"state":NaN,"questions":{}}`, `{"state":{},"state":{},"questions":{}}`, `{"state":{"nested":[1e309]},"questions":{}}`} {
		fixture, requestPath, outputPath := consultTestPaths(t)
		fixture.write(t, "request.json", raw)
		var calls int
		if _, err := consultWithOptions(fixture.root, requestPath, outputPath, false, consultOptions{transport: consultSyntheticTransport(t, "", &calls)}); err == nil || calls != 0 {
			t.Fatalf("unsafe JSON error = %v, calls = %d", err, calls)
		}
	}
	for _, conflict := range []string{"existing", "symlink", "missing parent"} {
		t.Run(conflict, func(t *testing.T) {
			fixture, requestPath, outputPath := consultTestPaths(t)
			switch conflict {
			case "existing":
				fixture.write(t, "record.json", "previous consultation")
			case "symlink":
				target := fixture.write(t, "unrelated.json", "unrelated data")
				if err := os.Symlink(target, outputPath); err != nil {
					t.Fatal(err)
				}
			case "missing parent":
				outputPath = filepath.Join(fixture.root, "missing", "record.json")
			}
			before := suiteSnapshot(t, fixture.root)
			var calls int
			if _, err := consultWithOptions(fixture.root, requestPath, outputPath, false, consultOptions{transport: consultSyntheticTransport(t, "", &calls)}); err == nil || calls != 0 {
				t.Fatalf("conflict error = %v, calls = %d", err, calls)
			}
			if after := suiteSnapshot(t, fixture.root); !reflect.DeepEqual(before, after) {
				t.Fatal("output conflict changed files")
			}
		})
	}
	t.Run("unsafe policy", func(t *testing.T) {
		fixture, requestPath, outputPath := consultTestPaths(t)
		policyPath := filepath.Join(fixture.root, fixture.manifest["model_policy"].(string))
		data, err := os.ReadFile(policyPath)
		if err != nil {
			t.Fatal(err)
		}
		fixture.write(t, fixture.manifest["model_policy"].(string), strings.ReplaceAll(string(data), "automatic_escalation: false", "automatic_escalation: true"))
		var calls int
		if _, err := consultWithOptions(fixture.root, requestPath, outputPath, false, consultOptions{transport: consultSyntheticTransport(t, "", &calls)}); err == nil || calls != 0 {
			t.Fatalf("unsafe policy error = %v, calls = %d", err, calls)
		}
		if _, err := os.Lstat(outputPath); !errors.Is(err, os.ErrNotExist) {
			t.Fatal("unsafe policy reserved output")
		}
	})
}

func TestConsultInvalidResponsesAreSanitizedAndNeverRetried(t *testing.T) {
	t.Setenv("TYPESAFE_API_KEY", "fixture-secret-token")
	changes := []func(Object){
		func(response Object) { response["model"] = "jev-1.12.0" },
		func(response Object) { response["answers"] = Object{} },
		func(response Object) { response["answers"].(Object)["extra"] = Object{} },
		func(response Object) { response["answers"].(Object)["claim_support"].(Object)["type"] = "score" },
		func(response Object) { response["answers"].(Object)["claim_support"].(Object)["choice"] = "missing" },
		func(response Object) { response["answers"].(Object)["claim_support"].(Object)["choice"] = "supported" },
		func(response Object) {
			response["answers"].(Object)["claim_support"].(Object)["probabilities"] = Object{"supported": 0.2, "missing": 0.8}
		},
		func(response Object) {
			response["answers"].(Object)["claim_support"].(Object)["probabilities"] = Object{"supported": 0.1, "insufficient": 0.6}
		},
		func(response Object) {
			response["answers"].(Object)["claim_support"].(Object)["probabilities"] = Object{"supported": -0.1, "insufficient": 1.1}
		},
		func(response Object) {
			response["answers"].(Object)["claim_support"].(Object)["probabilities"] = Object{"supported": true, "insufficient": false}
		},
		func(response Object) { response["answers"].(Object)["claim_support"].(Object)["confidence"] = true },
		func(response Object) { response["answers"].(Object)["claim_support"].(Object)["confidence"] = "0.8" },
		func(response Object) { response["usage"].(Object)["input_tokens"] = true },
		func(response Object) { response["usage"].(Object)["output_tokens"] = -1 },
		func(response Object) { response["usage"] = Object{} },
	}
	var bodies []string
	for _, change := range changes {
		response := consultTestResponse()
		change(response)
		bodies = append(bodies, string(mustSuiteJSON(t, response)))
	}
	bodies = append(bodies, "fixture-secret-token", `{"model":"one","model":"two"}`, strings.Repeat("x", consultMaximumResponse+1))
	bodies = append(bodies, strings.ReplaceAll(string(mustSuiteJSON(t, consultTestResponse())), `"confidence":0.8`, `"confidence":NaN`))
	for index, body := range bodies {
		fixture, requestPath, outputPath := consultTestPaths(t)
		var calls int
		record, err := consultWithOptions(fixture.root, requestPath, outputPath, false, consultOptions{transport: consultSyntheticTransport(t, body, &calls)})
		if err != nil || calls != 1 || !reflect.DeepEqual(record["error"], Object{"category": "invalid_response"}) || record["status"] != "unavailable" {
			t.Fatalf("case %d: record = %#v, error = %v, calls = %d", index, record, err, calls)
		}
		if _, present := record["result"]; present {
			t.Fatal("invalid response retained result")
		}
		consultReadRecord(t, outputPath)
	}
}

func TestConsultAcceptsTiesAndRoundingAndEditedPolicyPin(t *testing.T) {
	t.Setenv("TYPESAFE_API_KEY", "fixture-secret-token")
	for _, distribution := range []Object{{"supported": 0.5, "insufficient": 0.5}, {"supported": 0.4, "insufficient": 0.5999999}} {
		fixture, requestPath, outputPath := consultTestPaths(t)
		response := consultTestResponse()
		response["answers"].(Object)["claim_support"].(Object)["probabilities"] = distribution
		var calls int
		record, err := consultWithOptions(fixture.root, requestPath, outputPath, false, consultOptions{transport: consultSyntheticTransport(t, string(mustSuiteJSON(t, response)), &calls)})
		if err != nil || record["status"] != "success" || calls != 1 {
			t.Fatalf("record = %#v, error = %v", record, err)
		}
	}
	fixture, requestPath, outputPath := consultTestPaths(t)
	policyPath := filepath.Join(fixture.root, fixture.manifest["model_policy"].(string))
	data, err := os.ReadFile(policyPath)
	if err != nil {
		t.Fatal(err)
	}
	var policy Object
	if err := yaml.Unmarshal(data, &policy); err != nil {
		t.Fatal(err)
	}
	policy["consultation"].(Object)["model"] = "jev-2.4.0"
	data, err = yaml.Marshal(policy)
	if err != nil {
		t.Fatal(err)
	}
	fixture.write(t, fixture.manifest["model_policy"].(string), string(data))
	response := consultTestResponse()
	response["model"] = "jev-2.4.0"
	var calls int
	record, err := consultWithOptions(fixture.root, requestPath, outputPath, false, consultOptions{transport: consultSyntheticTransport(t, string(mustSuiteJSON(t, response)), &calls)})
	if err != nil || record["status"] != "success" || record["requested_model"] != "jev-2.4.0" {
		t.Fatalf("edited pin record = %#v, error = %v", record, err)
	}
}

func TestConsultSanitizesNetworkAndHTTPFailures(t *testing.T) {
	t.Setenv("TYPESAFE_API_KEY", "fixture-secret-token")
	for _, status := range []int{302, 401, 429, 529} {
		fixture, requestPath, outputPath := consultTestPaths(t)
		calls := 0
		transport := consultRoundTripFunc(func(request *http.Request) (*http.Response, error) {
			calls++
			return &http.Response{StatusCode: status, Header: http.Header{"Location": []string{"https://untrusted.example/collect"}}, Body: io.NopCloser(strings.NewReader("fixture-secret-token")), Request: request}, nil
		})
		record, err := consultWithOptions(fixture.root, requestPath, outputPath, false, consultOptions{transport: transport})
		if err != nil || calls != 1 || !reflect.DeepEqual(record["error"], Object{"category": "http_error", "http_status": status}) {
			t.Fatalf("HTTP %d record = %#v, error = %v, calls = %d", status, record, err, calls)
		}
		consultReadRecord(t, outputPath)
	}
	for _, failure := range []error{errors.New("fixture-secret-token"), context.DeadlineExceeded} {
		fixture, requestPath, outputPath := consultTestPaths(t)
		calls := 0
		transport := consultRoundTripFunc(func(_ *http.Request) (*http.Response, error) { calls++; return nil, failure })
		record, err := consultWithOptions(fixture.root, requestPath, outputPath, false, consultOptions{transport: transport})
		want := "network_error"
		if errors.Is(failure, context.DeadlineExceeded) {
			want = "timeout"
		}
		if err != nil || calls != 1 || !reflect.DeepEqual(record["error"], Object{"category": want}) {
			t.Fatalf("failure record = %#v, error = %v, calls = %d", record, err, calls)
		}
		consultReadRecord(t, outputPath)
	}
}

func TestConsultTotalDeadlineCoversSlowResponseStream(t *testing.T) {
	t.Setenv("TYPESAFE_API_KEY", "fixture-secret-token")
	fixture, requestPath, outputPath := consultTestPaths(t)
	var calls atomic.Int64
	finished := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		calls.Add(1)
		io.Copy(io.Discard, request.Body)
		writer.Header().Set("Content-Type", "application/json")
		writer.WriteHeader(200)
		writer.Write([]byte(`{"model":`))
		writer.(http.Flusher).Flush()
		select {
		case <-request.Context().Done():
		case <-finished:
		}
	}))
	defer func() {
		close(finished)
		server.Close()
	}()
	serverURL, err := url.Parse(server.URL)
	if err != nil {
		t.Fatal(err)
	}
	transport := consultTransport(time.Second)
	defer transport.CloseIdleConnections()
	roundTrip := consultRoundTripFunc(func(request *http.Request) (*http.Response, error) {
		copy := request.Clone(request.Context())
		copy.URL = serverURL.Clone()
		return transport.RoundTrip(copy)
	})
	started := time.Now()
	record, err := consultWithOptions(fixture.root, requestPath, outputPath, false, consultOptions{transport: roundTrip, deadline: 100 * time.Millisecond})
	if err != nil || calls.Load() != 1 || !reflect.DeepEqual(record["error"], Object{"category": "timeout"}) || time.Since(started) > 2*time.Second {
		t.Fatalf("slow stream record = %#v, error = %v, calls = %d", record, err, calls.Load())
	}
	consultReadRecord(t, outputPath)
}

func TestConsultPublicDryRunDoesNotWrite(t *testing.T) {
	fixture, requestPath, outputPath := consultTestPaths(t)
	record, err := Consult(fixture.root, requestPath, outputPath, true)
	if err != nil || record["status"] != "dry_run" {
		t.Fatalf("record = %#v, error = %v", record, err)
	}
	if _, err := os.Lstat(outputPath); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("public dry run created output")
	}
}

func TestConsultStrictTokenUsageRejectsFractionalSyntax(t *testing.T) {
	t.Setenv("TYPESAFE_API_KEY", "fixture-secret-token")
	fixture, requestPath, outputPath := consultTestPaths(t)
	data, err := json.Marshal(consultTestResponse())
	if err != nil {
		t.Fatal(err)
	}
	body := strings.ReplaceAll(string(data), `"input_tokens":25`, `"input_tokens":25.0`)
	var calls int
	record, err := consultWithOptions(fixture.root, requestPath, outputPath, false, consultOptions{transport: consultSyntheticTransport(t, body, &calls)})
	if err != nil || calls != 1 || !reflect.DeepEqual(record["error"], Object{"category": "invalid_response"}) {
		t.Fatalf("record = %#v, error = %v", record, err)
	}
}
