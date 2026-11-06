import csv
from pathlib import Path
from collections import Counter

path = Path("data/processed/preprocessing_mef/municipality_year_features.csv")

reasons = Counter()
excluded = []
total = 0

with path.open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        total += 1

        if row["apto_candidato"] == "1":
            continue

        excluded.append(row)

        # Diagnosticar las condiciones de exclusion
        for field in ["pia_soles", "pim_soles", "devengado_soles"]:
            if float(row[field]) <= 0:
                reasons[f"{field}_no_positivo"] += 1

        if int(row["n_codigos_proyecto_faltantes"]) > 0:
            reasons["proyectos_sin_codigo"] += 1

        if int(row["n_lineas_excluidas"]) > 0:
            reasons["lineas_excluidas"] += 1

        if "metadatos_inconsistentes" in row["advertencias"]:
            reasons["metadatos_inconsistentes"] += 1

print("Perfiles totales:", total)
print("Perfiles no candidatos:", len(excluded))
print("\nMotivos detectados:")

for reason, count in reasons.most_common():
    print(f"- {reason}: {count}")

print("\nPrimeros 10 perfiles no candidatos:")

for row in excluded[:10]:
    print(row["ano_eje"], row["sec_ejec"], row["ejecutora_nombre"], row["advertencias"])
