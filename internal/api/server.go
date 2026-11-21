// Package api exposes the existing distributed K-Means TCP engine through a
// small REST API. MongoDB persists jobs; Redis optionally caches job lookups.
package api

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/marck0820001/peru-budget-distributed.git/internal/ml/massive"
)

// Trainer permits fast API unit tests without running millions of observations.
type Trainer func(massive.Metadata, massive.TrainConfig, []string, time.Duration) (massive.TrainResult, error)

// JobStore is the durable persistence boundary. The concrete implementation
// lives in internal/storage to avoid importing database drivers into api.
type JobStore interface {
	Put(context.Context, Job) error
	Get(context.Context, string) (Job, bool, error)
	List(context.Context) ([]Job, error)
	Health(context.Context) map[string]string
}

type Config struct {
	Metadata    massive.Metadata
	Nodes       []string
	OutDir      string
	NodeTimeout time.Duration
	Trainer     Trainer
	Store       JobStore // nil only for isolated tests or stage-2 compatibility
}

type TrainRequest struct {
	K             *int   `json:"k,omitempty"`
	Seed          *int64 `json:"seed,omitempty"`
	MaxIterations *int   `json:"max_iterations,omitempty"`
}

type Job struct {
	ID           string     `json:"id"`
	Status       string     `json:"status"`
	K            int        `json:"k"`
	Seed         int64      `json:"seed"`
	NodeCount    int        `json:"node_count"`
	DatasetRows  int64      `json:"dataset_rows"`
	StartedAt    time.Time  `json:"started_at"`
	FinishedAt   *time.Time `json:"finished_at,omitempty"`
	Report       string     `json:"report,omitempty"`
	Inertia      *float64   `json:"inertia,omitempty"`
	Iterations   *int       `json:"iterations,omitempty"`
	ClusterSizes []int64    `json:"cluster_sizes,omitempty"`
	Converged    *bool      `json:"converged,omitempty"`
	Error        string     `json:"error,omitempty"`
}

type Server struct {
	meta    massive.Metadata
	nodes   []string
	outDir  string
	timeout time.Duration
	trainer Trainer
	store   JobStore
	mux     *http.ServeMux
	mu      sync.RWMutex
	jobs    map[string]Job
	active  bool
}

func NewServer(cfg Config) (*Server, error) {
	if cfg.Metadata.Rows < 1 || len(cfg.Nodes) < 2 {
		return nil, fmt.Errorf("se requieren metadatos con filas y al menos dos nodos TCP")
	}
	if cfg.OutDir == "" {
		return nil, fmt.Errorf("falta directorio de resultados")
	}
	if err := os.MkdirAll(cfg.OutDir, 0755); err != nil {
		return nil, err
	}
	if cfg.NodeTimeout <= 0 {
		cfg.NodeTimeout = 120 * time.Second
	}
	if cfg.Trainer == nil {
		cfg.Trainer = massive.DistributedTrain
	}
	s := &Server{meta: cfg.Metadata, nodes: append([]string(nil), cfg.Nodes...), outDir: cfg.OutDir,
		timeout: cfg.NodeTimeout, trainer: cfg.Trainer, store: cfg.Store, jobs: make(map[string]Job), mux: http.NewServeMux()}
	if s.store != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		existing, err := s.store.List(ctx)
		if err != nil {
			return nil, fmt.Errorf("carga inicial de MongoDB: %w", err)
		}
		for _, old := range existing {
			if old.Status != "running" {
				continue
			}
			old.Status = "failed"
			old.Error = "entrenamiento interrumpido por reinicio de la API; reintentar"
			finished := time.Now().UTC()
			old.FinishedAt = &finished
			if err := s.store.Put(ctx, old); err != nil {
				return nil, fmt.Errorf("recuperacion de trabajo %s: %w", old.ID, err)
			}
		}
	}
	s.mux.HandleFunc("GET /health", s.health)
	s.mux.HandleFunc("GET /api/v1/storage/health", s.storageHealth)
	s.mux.HandleFunc("GET /api/v1/cluster/nodes", s.clusterNodes)
	s.mux.HandleFunc("POST /api/v1/train", s.train)
	s.mux.HandleFunc("GET /api/v1/jobs", s.listJobs)
	s.mux.HandleFunc("GET /api/v1/jobs/{id}", s.getJob)
	s.mux.HandleFunc("GET /api/v1/jobs/{id}/result", s.getJobResult)
	return s, nil
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	started := time.Now()
	s.mux.ServeHTTP(w, r)
	log.Printf("HTTP %s %s duration=%s", r.Method, r.URL.Path, time.Since(started))
}

func respond(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func bad(w http.ResponseWriter, status int, msg string) {
	respond(w, status, map[string]string{"error": msg})
}
func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	respond(w, http.StatusOK, map[string]any{"status": "ok", "service": "perubudget-pc4-api",
		"dataset_rows": s.meta.Rows, "features": s.meta.Features, "node_count": len(s.nodes)})
}
func (s *Server) storageHealth(w http.ResponseWriter, r *http.Request) {
	if s.store == nil {
		bad(w, http.StatusServiceUnavailable, "persistencia no configurada")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	state := s.store.Health(ctx)
	status := http.StatusOK
	if state["mongodb"] != "ok" || state["redis"] != "ok" {
		status = http.StatusServiceUnavailable
	}
	respond(w, status, state)
}
func (s *Server) clusterNodes(w http.ResponseWriter, r *http.Request) {
	type node struct {
		Address   string `json:"address"`
		Reachable bool   `json:"reachable"`
	}
	result := make([]node, len(s.nodes))
	var wg sync.WaitGroup
	for i, addr := range s.nodes {
		result[i] = node{Address: addr}
		wg.Add(1)
		go func(i int, a string) {
			defer wg.Done()
			c, e := net.DialTimeout("tcp", a, 80*time.Millisecond)
			if e == nil {
				result[i].Reachable = true
				_ = c.Close()
			}
		}(i, addr)
	}
	wg.Wait()
	respond(w, http.StatusOK, map[string]any{"nodes": result, "note": "Reachable indica conexión TCP posible, no garantiza la ejecución del entrenamiento"})
}
func (s *Server) train(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 4096)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	var req *TrainRequest
	if err := decoder.Decode(&req); err != nil {
		bad(w, 400, "JSON inválido: "+err.Error())
		return
	}
	if req == nil {
		bad(w, 400, "el cuerpo debe ser un objeto JSON")
		return
	}
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		bad(w, 400, "se espera exactamente un objeto JSON")
		return
	}
	k := 3
	if req.K != nil {
		k = *req.K
	}
	seed := int64(42)
	if req.Seed != nil {
		seed = *req.Seed
	}
	maxIter := 25
	if req.MaxIterations != nil {
		maxIter = *req.MaxIterations
	}
	if k < 2 || k > 16 || int64(k) > s.meta.Rows || maxIter < 1 || maxIter > 100 {
		bad(w, 400, "k debe estar entre 2 y 16 y max_iterations entre 1 y 100")
		return
	}
	cfg := massive.TrainConfig{K: k, Workers: len(s.nodes), MaxIterations: maxIter, Tolerance: 1e-4,
		Seed: seed, InitSample: 10000, BatchRows: 8192, ClipZ: 5}
	s.mu.Lock()
	if s.active {
		s.mu.Unlock()
		bad(w, http.StatusConflict, "ya hay un entrenamiento activo; consulta su estado")
		return
	}
	// Fail closed: avoid keeping unbounded job state in this PC4 milestone.
	if len(s.jobs) >= 100 {
		s.mu.Unlock()
		bad(w, http.StatusServiceUnavailable, "límite de 100 trabajos; reiniciar el servicio de demostración")
		return
	}
	var random [12]byte
	if _, err := rand.Read(random[:]); err != nil {
		s.mu.Unlock()
		bad(w, 500, "no se pudo generar id seguro")
		return
	}
	id := hex.EncodeToString(random[:])
	job := Job{ID: id, Status: "running", K: k, Seed: seed, NodeCount: len(s.nodes), DatasetRows: s.meta.Rows, StartedAt: time.Now().UTC()}
	s.jobs[id] = job
	s.active = true
	s.mu.Unlock()
	if s.store != nil {
		ctx, cancel := context.WithTimeout(r.Context(), 4*time.Second)
		err := s.store.Put(ctx, job)
		cancel()
		if err != nil {
			s.mu.Lock()
			delete(s.jobs, id)
			s.active = false
			s.mu.Unlock()
			log.Printf("MongoDB no disponible al crear job %s: %v", id, err)
			bad(w, http.StatusServiceUnavailable, "no se pudo persistir el trabajo en MongoDB")
			return
		}
	}
	go s.run(job, cfg)
	w.Header().Set("Location", "/api/v1/jobs/"+id)
	respond(w, http.StatusAccepted, map[string]any{"job_id": id, "status": "running", "status_url": "/api/v1/jobs/" + id})
}
func (s *Server) run(job Job, cfg massive.TrainConfig) {
	result, err := s.trainer(s.meta, cfg, s.nodes, s.timeout)
	path := ""
	if err == nil {
		path = filepath.Join(s.outDir, "api_training_"+job.ID+".json")
		// SaveReport is the same JSON format used for PC3/PC4 comparison.
		err = massive.SaveReport(path, result)
	}
	ended := time.Now().UTC()
	s.mu.Lock()
	j := s.jobs[job.ID]
	j.FinishedAt = &ended
	if err != nil {
		j.Status = "failed"
		j.Error = err.Error()
	} else {
		j.Status = "succeeded"
		j.Report = filepath.Base(path)
		inertia := result.Inertia
		iterations := result.Iterations
		converged := result.Converged
		j.Inertia = &inertia
		j.Iterations = &iterations
		j.Converged = &converged
		j.ClusterSizes = append([]int64(nil), result.ClusterSizes...)
	}
	s.mu.Unlock()
	if s.store != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		saveErr := s.store.Put(ctx, j)
		cancel()
		if saveErr != nil {
			log.Printf("ERROR: no se persistio fin de trabajo %s: %v", j.ID, saveErr)
			j.Status = "failed"
			j.Error = "error al guardar estado final en MongoDB: " + saveErr.Error()
		}
	}
	s.mu.Lock()
	s.jobs[job.ID] = j
	s.active = false
	s.mu.Unlock()
}

func (s *Server) listJobs(w http.ResponseWriter, r *http.Request) {
	if s.store != nil {
		ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
		defer cancel()
		rows, err := s.store.List(ctx)
		if err != nil {
			log.Printf("error MongoDB al listar: %v", err)
			bad(w, http.StatusServiceUnavailable, "base de datos temporalmente no disponible")
			return
		}
		sort.Slice(rows, func(i, j int) bool { return rows[i].StartedAt.After(rows[j].StartedAt) })
		respond(w, 200, map[string]any{"jobs": rows})
		return
	}
	s.mu.RLock()
	rows := make([]Job, 0, len(s.jobs))
	for _, job := range s.jobs {
		rows = append(rows, job)
	}
	s.mu.RUnlock()
	sort.Slice(rows, func(i, j int) bool { return rows[i].StartedAt.After(rows[j].StartedAt) })
	respond(w, 200, map[string]any{"jobs": rows})
}
func (s *Server) lookup(ctx context.Context, id string) (Job, bool, error) {
	if s.store != nil {
		c, cancel := context.WithTimeout(ctx, 3*time.Second)
		defer cancel()
		return s.store.Get(c, id)
	}
	s.mu.RLock()
	defer s.mu.RUnlock()
	j, ok := s.jobs[id]
	return j, ok, nil
}
func (s *Server) getJob(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	j, ok, err := s.lookup(r.Context(), id)
	if err != nil {
		log.Printf("error de consulta MongoDB job=%s: %v", id, err)
		bad(w, http.StatusServiceUnavailable, "base de datos temporalmente no disponible")
		return
	}
	if !ok {
		bad(w, 404, "trabajo no encontrado")
		return
	}
	respond(w, 200, j)
}
func (s *Server) getJobResult(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	j, ok, err := s.lookup(r.Context(), id)
	if err != nil {
		log.Printf("error de consulta MongoDB job=%s: %v", id, err)
		bad(w, http.StatusServiceUnavailable, "base de datos temporalmente no disponible")
		return
	}
	if !ok {
		bad(w, 404, "trabajo no encontrado")
		return
	}
	if j.Status != "succeeded" {
		bad(w, 409, "el resultado no está disponible; estado="+j.Status)
		return
	}
	if !strings.HasPrefix(j.Report, "api_training_") || !strings.HasSuffix(j.Report, ".json") || strings.ContainsAny(j.Report, "/\\") {
		bad(w, 500, "ruta de reporte inválida")
		return
	}
	b, err := os.ReadFile(filepath.Join(s.outDir, j.Report))
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			bad(w, 404, "reporte no disponible en disco")
			return
		}
		bad(w, 500, "no se pudo abrir reporte")
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(200)
	_, _ = w.Write(b)
}
