package api

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/marck0820001/peru-budget-distributed.git/internal/ml/massive"
)

func setup(t *testing.T, trainer Trainer) *Server {
	t.Helper()
	s, err := NewServer(Config{Metadata: massive.Metadata{Rows: 50000, Features: append([]string(nil), massive.Names...)},
		Nodes: []string{"127.0.0.1:1", "127.0.0.1:2"}, OutDir: t.TempDir(), Trainer: trainer})
	if err != nil {
		t.Fatal(err)
	}
	return s
}
func call(s *Server, method, path, body string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	resp := httptest.NewRecorder()
	s.ServeHTTP(resp, req)
	return resp
}
func TestHealth(t *testing.T) {
	s := setup(t, func(m massive.Metadata, c massive.TrainConfig, n []string, d time.Duration) (massive.TrainResult, error) {
		return massive.TrainResult{}, nil
	})
	got := call(s, "GET", "/health", "")
	if got.Code != 200 || !strings.Contains(got.Body.String(), "50000") {
		t.Fatalf("health: %d %s", got.Code, got.Body)
	}
	if got := call(s, "GET", "/api/v1/jobs/no-such-job", ""); got.Code != 404 {
		t.Fatalf("notfound: %d", got.Code)
	}
}
func TestTrainAsyncAndResult(t *testing.T) {
	block := make(chan struct{})
	s := setup(t, func(m massive.Metadata, c massive.TrainConfig, n []string, d time.Duration) (massive.TrainResult, error) {
		<-block
		if m.Rows != 50000 || c.K != 3 || c.Seed != 42 || len(n) != 2 {
			t.Errorf("config incorrectly forwarded")
		}
		return massive.TrainResult{Rows: m.Rows, K: c.K, Seed: c.Seed, Workers: len(n), Inertia: 123.456, Iterations: 4, Converged: true, ClusterSizes: []int64{25000, 10000, 15000}}, nil
	})
	resp := call(s, "POST", "/api/v1/train", `{"k":3,"seed":42}`)
	if resp.Code != 202 {
		t.Fatalf("post: %d %s", resp.Code, resp.Body)
	}
	var post struct {
		JobID string `json:"job_id"`
	}
	if e := json.Unmarshal(resp.Body.Bytes(), &post); e != nil || len(post.JobID) != 24 {
		t.Fatalf("job id: %v %+v", e, post)
	}
	if resp := call(s, "POST", "/api/v1/train", `{}`); resp.Code != 409 {
		t.Fatalf("concurrency: %d", resp.Code)
	}
	if resp := call(s, "GET", "/api/v1/jobs/"+post.JobID+"/result", ""); resp.Code != 409 {
		t.Fatalf("premature result: %d", resp.Code)
	}
	close(block)
	deadline := time.Now().Add(2 * time.Second)
	var job Job
	for time.Now().Before(deadline) {
		r := call(s, "GET", "/api/v1/jobs/"+post.JobID, "")
		if e := json.Unmarshal(r.Body.Bytes(), &job); e != nil {
			t.Fatal(e)
		}
		if job.Status == "succeeded" {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if job.Status != "succeeded" || job.Inertia == nil || *job.Inertia != 123.456 {
		t.Fatalf("job: %+v", job)
	}
	r := call(s, "GET", "/api/v1/jobs/"+post.JobID+"/result", "")
	if r.Code != 200 || !bytes.Contains(r.Body.Bytes(), []byte(`"inertia": 123.456`)) {
		t.Fatalf("result %d: %s", r.Code, r.Body.String())
	}
	if _, e := os.Stat(filepath.Join(s.outDir, "api_training_"+post.JobID+".json")); e != nil {
		t.Fatal(e)
	}
	r = call(s, "GET", "/api/v1/jobs", "")
	if r.Code != 200 || !strings.Contains(r.Body.String(), post.JobID) {
		t.Fatalf("list %d: %s", r.Code, r.Body)
	}
}
func TestTrainRejectsBadJSON(t *testing.T) {
	s := setup(t, func(m massive.Metadata, c massive.TrainConfig, n []string, d time.Duration) (massive.TrainResult, error) {
		return massive.TrainResult{}, nil
	})
	for _, body := range []string{`{"k":1}`, `{"k":17}`, `{"max_iterations":0}`, `{"unexpected":1}`, `null`, `{`, ""} {
		if r := call(s, "POST", "/api/v1/train", body); r.Code != 400 {
			t.Errorf("body %q returned %d: %s", body, r.Code, r.Body)
		}
	}
}
func TestJobError(t *testing.T) {
	s := setup(t, func(m massive.Metadata, c massive.TrainConfig, n []string, d time.Duration) (massive.TrainResult, error) {
		return massive.TrainResult{}, errors.New("nodo TCP no disponible")
	})
	r := call(s, "POST", "/api/v1/train", `{}`)
	if r.Code != 202 {
		t.Fatal(r.Code)
	}
	var post struct {
		JobID string `json:"job_id"`
	}
	_ = json.Unmarshal(r.Body.Bytes(), &post)
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		r = call(s, "GET", "/api/v1/jobs/"+post.JobID, "")
		var job Job
		_ = json.Unmarshal(r.Body.Bytes(), &job)
		if job.Status == "failed" {
			if job.Error == "" {
				t.Fatal("missing error")
			}
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("job did not fail")
}
func TestNodeHealthEndpoint(t *testing.T) {
	s := setup(t, func(m massive.Metadata, c massive.TrainConfig, n []string, d time.Duration) (massive.TrainResult, error) {
		return massive.TrainResult{}, nil
	})
	r := call(s, "GET", "/api/v1/cluster/nodes", "")
	if r.Code != 200 || !strings.Contains(r.Body.String(), `"reachable":false`) {
		t.Fatalf("nodes: %d %s", r.Code, r.Body)
	}
}
func TestAllowOnlyExpectedMethods(t *testing.T) {
	s := setup(t, func(m massive.Metadata, c massive.TrainConfig, n []string, d time.Duration) (massive.TrainResult, error) {
		return massive.TrainResult{}, nil
	})
	if r := call(s, http.MethodGet, "/api/v1/train", ""); r.Code != 405 {
		t.Fatalf("method: %d", r.Code)
	}
}
