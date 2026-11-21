package main

import (
	"context"
	"embed"
	"flag"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/marck0820001/peru-budget-distributed.git/internal/api"
	"github.com/marck0820001/peru-budget-distributed.git/internal/ml/massive"
	"github.com/marck0820001/peru-budget-distributed.git/internal/storage"
)

//go:embed openapi.yaml
var documentation embed.FS

func main() {
	listen := flag.String("listen", ":8080", "dirección para HTTP; usar localhost si no está dentro de Docker")
	metadataPath := flag.String("metadata", "data/processed/massive_mef/budget_lines_metadata.json", "metadatos de PC3")
	dataPath := flag.String("data", "data/processed/massive_mef/budget_lines.f64", "binario de PC3")
	nodes := flag.String("nodes", "127.0.0.1:9101,127.0.0.1:9102", "nodos TCP separados por coma")
	outDir := flag.String("out-dir", "data/processed/pc4_api", "directorio de resultados exclusivos de API")
	nodeTimeout := flag.Duration("node-timeout", 120*time.Second, "timeout máximo por nodo/iteración")
	mongoURI := flag.String("mongo-uri", "", "URI MongoDB; requerido para persistencia en PC4")
	mongoDB := flag.String("mongo-db", "perubudget_pc4", "base MongoDB")
	redisAddr := flag.String("redis-addr", "", "Redis host:port para cache; requerido junto con MongoDB")
	flag.Parse()
	meta, err := massive.OpenPortableMetadata(*metadataPath, *dataPath)
	if err != nil {
		log.Fatal(err)
	}
	addrs := []string{}
	for _, raw := range strings.Split(*nodes, ",") {
		if a := strings.TrimSpace(raw); a != "" {
			addrs = append(addrs, a)
		}
	}
	var jobStore api.JobStore
	if *mongoURI != "" || *redisAddr != "" {
		if *mongoURI == "" || *redisAddr == "" {
			log.Fatal("MongoDB y Redis deben configurarse juntos")
		}
		ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
		db, err := storage.NewMongoRedis(ctx, *mongoURI, *mongoDB, *redisAddr)
		cancel()
		if err != nil {
			log.Fatalf("error de persistencia: %v", err)
		}
		defer db.Close()
		jobStore = db
	}
	srv, err := api.NewServer(api.Config{Metadata: meta, Nodes: addrs, OutDir: *outDir, NodeTimeout: *nodeTimeout, Store: jobStore})
	if err != nil {
		log.Fatal(err)
	}
	mux := http.NewServeMux()
	mux.Handle("/", srv)
	mux.HandleFunc("GET /openapi.yaml", func(w http.ResponseWriter, r *http.Request) {
		b, err := documentation.ReadFile("openapi.yaml")
		if err != nil {
			http.Error(w, "documentación no disponible", 500)
			return
		}
		w.Header().Set("Content-Type", "application/yaml; charset=utf-8")
		_, _ = w.Write(b)
	})
	mux.HandleFunc("GET /docs", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = fmt.Fprint(w, swaggerHTML)
	})
	log.Printf("PC4 API escuchando en %s | filas=%d | nodos=%v | docs=/docs", *listen, meta.Rows, addrs)
	server := &http.Server{Addr: *listen, Handler: mux, ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 30 * time.Second}
	log.Fatal(server.ListenAndServe())
}

const swaggerHTML = `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PeruBudget PC4 API — Swagger</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css"></head><body><div id="swagger-ui"></div><script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script><script>window.onload=function(){if(window.SwaggerUIBundle){window.ui=SwaggerUIBundle({url:'/openapi.yaml',dom_id:'#swagger-ui',deepLinking:true})}else{document.getElementById('swagger-ui').textContent='No se pudo cargar Swagger UI desde CDN. Especificación: /openapi.yaml'}}</script></body></html>`
