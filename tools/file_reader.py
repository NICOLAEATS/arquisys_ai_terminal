import os
from pathlib import Path
from rich.console import Console

console = Console()

IGNORED_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".idea", ".vscode", "dist", "build", "output_diagrams",
}
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".java", ".cs", ".cpp", ".c", ".h",
    ".go", ".rb", ".php", ".kt", ".swift", ".rs", ".scala",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".sql",
    ".md", ".txt",
}


def read_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"[ERROR] No existe: {path}"
    if p.suffix not in CODE_EXTENSIONS:
        return f"[AVISO] Extensión no reconocida: {p.suffix} — leyendo igual..."
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        return f"# Archivo: {path}\n```{p.suffix.lstrip('.')}\n{content}\n```"
    except Exception as e:
        return f"[ERROR] {e}"


def read_folder(folder: str, max_files: int = 35) -> str:
    p = Path(folder)
    if not p.exists() or not p.is_dir():
        return f"[ERROR] Carpeta no encontrada: {folder}"

    files_read, skipped, parts = 0, [], []

    for root, dirs, files in os.walk(p):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for fname in sorted(files):
            fp = Path(root) / fname
            if fp.suffix not in CODE_EXTENSIONS:
                continue
            if files_read >= max_files:
                skipped.append(str(fp))
                continue
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
                rel = fp.relative_to(p)
                parts.append(
                    f"## {rel}\n```{fp.suffix.lstrip('.')}\n{content}\n```"
                )
                files_read += 1
            except Exception as e:
                parts.append(f"## {fp.relative_to(p)}\n[ERROR: {e}]")

    if not parts:
        return f"[AVISO] No se encontraron archivos de código en: {folder}"

    result = f"# Código fuente — {folder} ({files_read} archivos)\n\n"
    result += "\n\n---\n\n".join(parts)
    if skipped:
        result += f"\n\n[AVISO] {len(skipped)} archivos omitidos por límite."
    return result


def get_tree(folder: str) -> str:
    p = Path(folder)
    if not p.exists():
        return f"[ERROR] No existe: {folder}"
    lines = [f"📁 {p.name}/"]

    def _walk(d: Path, prefix: str = ""):
        entries = sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name))
        entries = [e for e in entries if e.name not in IGNORED_DIRS]
        for i, e in enumerate(entries):
            last = i == len(entries) - 1
            conn = "└── " if last else "├── "
            icon = "📁 " if e.is_dir() else "📄 "
            lines.append(f"{prefix}{conn}{icon}{e.name}")
            if e.is_dir():
                _walk(e, prefix + ("    " if last else "│   "))

    _walk(p)
    return "\n".join(lines)