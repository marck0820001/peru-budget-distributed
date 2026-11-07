"""Adapt Go imports to the ACTUAL module name already set in the repository.

Usage (from repository root): py scripts/setup_go_imports.py
Does not overwrite existing go.mod or source files unrelated to the package.
"""
from pathlib import Path
import re
import sys


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    go_mod = root / "go.mod"
    if not go_mod.exists():
        print("ERROR: no se encontró go.mod. Inicializa primero tu módulo con go mod init <ruta-repo>.", file=sys.stderr)
        raise SystemExit(2)
    match = re.search(r"^module\s+(\S+)\s*$", go_mod.read_text(encoding="utf-8"), flags=re.M)
    if not match:
        raise SystemExit("ERROR: go.mod no contiene una línea module válida")
    module = match.group(1)
    for relative in ("cmd/trainer/main.go", "cmd/etl/main.go"):
        f = root / relative
        s = f.read_text(encoding="utf-8")
        if "__PROJECT_MODULE__" in s:
            f.write_text(s.replace("__PROJECT_MODULE__", module), encoding="utf-8")
            print("Import actualizado:", relative, "=>", module)
        else:
            print("Sin cambios:", relative)


if __name__ == "__main__":
    main()
