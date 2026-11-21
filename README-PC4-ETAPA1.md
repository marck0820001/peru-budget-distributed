# PC4 — Etapa 1: clúster TCP real sobre PeruBudget Distributed

**Este ZIP es un parche de archivos NUEVOS, no un repositorio completo.**

1. Extraer el ZIP en la raíz de `peru-budget-distributed` (rama nueva desde `develop`).
2. Reutilizar los dos archivos de PC3: `data/processed/massive_mef/budget_lines.f64` y `budget_lines_metadata.json`.
3. Probar compilación: `go test ./...`.
4. Verificar Compose: `docker compose -f compose.pc4.cluster.yaml config`.
5. Ejecutar:

   ```powershell
   docker compose -f compose.pc4.cluster.yaml up --build --abort-on-container-exit --exit-code-from coordinator
   ```

6. Ver evidencias: `docker compose -f compose.pc4.cluster.yaml logs node-a node-b coordinator`.
7. El resultado aparecerá en `data/processed/massive_mef/training_distributed_k3_nodes2_seed42.json`.
8. Ver guía detallada en `docs/pc4/01-cluster-distribuido.md`.

No incluye API REST, Swagger, MongoDB ni Redis. Ese es el siguiente bloque PC4.
