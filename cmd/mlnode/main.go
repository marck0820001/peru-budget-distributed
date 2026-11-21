package main

import (
	"flag"
	"log"
	"net"

	"github.com/marck0820001/peru-budget-distributed.git/internal/ml/massive"
)

func main() {
	listen := flag.String("listen", ":9101", "dirección TCP en la que escucha el nodo")
	metadata := flag.String("metadata", "data/processed/massive_mef/budget_lines_metadata.json", "metadatos de PC3")
	data := flag.String("data", "data/processed/massive_mef/budget_lines.f64", "binario de PC3")
	node := flag.String("id", "ml-node", "identificador único del nodo")
	flag.Parse()
	m, err := massive.OpenPortableMetadata(*metadata, *data)
	if err != nil {
		log.Fatal(err)
	}
	ln, err := net.Listen("tcp", *listen)
	if err != nil {
		log.Fatal(err)
	}
	defer ln.Close()
	log.Printf("Nodo %s escuchando en %s | filas=%d | features=%d", *node, ln.Addr(), m.Rows, m.Dimensions)
	log.Fatal(massive.ServeShardTCP(ln, m, *node))
}
