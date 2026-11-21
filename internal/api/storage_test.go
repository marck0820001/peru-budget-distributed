package api

import (
	"context"
	"encoding/json"
	"errors"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/marck0820001/peru-budget-distributed.git/internal/ml/massive"
)

type fakeStore struct {
	mu      sync.Mutex
	jobs    map[string]Job
	failPut bool
}

func (s *fakeStore) Put(_ context.Context, j Job) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.failPut {
		return errors.New("mongo offline")
	}
	s.jobs[j.ID] = j
	return nil
}
func (s *fakeStore) Get(_ context.Context, id string) (Job, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	j, ok := s.jobs[id]
	return j, ok, nil
}
func (s *fakeStore) List(_ context.Context) ([]Job, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]Job, 0, len(s.jobs))
	for _, j := range s.jobs {
		out = append(out, j)
	}
	return out, nil
}
func (s *fakeStore) Health(context.Context) map[string]string {
	return map[string]string{"mongodb": "ok", "redis": "ok"}
}

func TestPersistentJobsSurviveAPIRestart(t *testing.T) {
	st := &fakeStore{jobs: make(map[string]Job)}
	temp := t.TempDir()
	trainer := func(m massive.Metadata, c massive.TrainConfig, n []string, d time.Duration) (massive.TrainResult, error) {
		return massive.TrainResult{
			Rows: m.Rows, K: c.K, Workers: len(n), Seed: c.Seed, Inertia: 321, Iterations: 2, Converged: true, ClusterSizes: []int64{500, 1000, 48500},
		}, nil
	}
	config := Config{Metadata: massive.Metadata{Rows: 50000, Features: append([]string(nil), massive.Names...)}, Nodes: []string{"127.0.0.1:1", "127.0.0.1:2"}, OutDir: temp, Trainer: trainer, Store: st}
	s, err := NewServer(config)
	if err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRecorder()
	s.ServeHTTP(r, httptest.NewRequest("POST", "/api/v1/train", nil))
	if r.Code != 400 {
		t.Fatalf("expected validation 400, got %d", r.Code)
	}
	resp := call(s, "POST", "/api/v1/train", `{"k":3}`)
	if resp.Code != 202 {
		t.Fatalf("post=%d %s", resp.Code, resp.Body)
	}
	var created struct {
		JobID string `json:"job_id"`
	}
	_ = json.Unmarshal(resp.Body.Bytes(), &created)
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		job, ok, _ := st.Get(context.Background(), created.JobID)
		if ok && job.Status == "succeeded" {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	s2, err := NewServer(config)
	if err != nil {
		t.Fatal(err)
	}
	check := call(s2, "GET", "/api/v1/jobs/"+created.JobID, "")
	if check.Code != 200 {
		t.Fatalf("restart GET=%d %s", check.Code, check.Body)
	}
	report := call(s2, "GET", "/api/v1/jobs/"+created.JobID+"/result", "")
	if report.Code != 200 {
		t.Fatalf("restart result=%d %s", report.Code, report.Body)
	}
	jobs := call(s2, "GET", "/api/v1/jobs", "")
	if jobs.Code != 200 {
		t.Fatalf("restart list=%d", jobs.Code)
	}
	storageHealth := call(s2, "GET", "/api/v1/storage/health", "")
	if storageHealth.Code != 200 {
		t.Fatalf("storage health=%d", storageHealth.Code)
	}
}
func TestRecoverInterruptedJob(t *testing.T) {
	st := &fakeStore{jobs: map[string]Job{"old": {ID: "old", Status: "running", StartedAt: time.Now().UTC()}}}
	_, err := NewServer(Config{Metadata: massive.Metadata{Rows: 50000, Features: append([]string(nil), massive.Names...)}, Nodes: []string{"n1:1", "n2:1"}, OutDir: t.TempDir(), Store: st})
	if err != nil {
		t.Fatal(err)
	}
	j, _, _ := st.Get(context.Background(), "old")
	if j.Status != "failed" || j.FinishedAt == nil {
		t.Fatalf("recovery status=%s", j.Status)
	}
}
func TestMongoFailClosed(t *testing.T) {
	st := &fakeStore{jobs: map[string]Job{}, failPut: true}
	s, err := NewServer(Config{Metadata: massive.Metadata{Rows: 50000, Features: append([]string(nil), massive.Names...)}, Nodes: []string{"n1:1", "n2:1"}, OutDir: t.TempDir(), Store: st})
	if err != nil {
		t.Fatal(err)
	}
	r := call(s, "POST", "/api/v1/train", `{}`)
	if r.Code != 503 {
		t.Fatalf("Mongo offline should be 503 not %d: %s", r.Code, r.Body)
	}
}
