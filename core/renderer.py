"""
Renderiza diagramas en terminal y exporta a PNG.
- Mermaid  → mermaid.ink API (PNG via HTTP)
- PlantUML → plantuml.com server (PNG via HTTP)
"""
import re
import json
import base64
import zlib
import string
import requests
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.syntax import Syntax
from rich.panel import Panel
from config import OUTPUT_DIR, PLANTUML_SERVER, MERMAID_INK_URL, KROKI_URL

console = Console()
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MERMAID_STARTS = (
    "graph",
    "flowchart",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "stateDiagram-v2",
    "erDiagram",
    "journey",
    "gantt",
    "pie",
    "mindmap",
    "timeline",
    "gitGraph",
    "requirementDiagram",
    "quadrantChart",
    "xychart-beta",
    "block-beta",
    "packet-beta",
    "architecture-beta",
    "kanban",
    "sankey-beta",
    "usecaseDiagram",
)


def _ensure_png_bytes(payload: bytes, source: str) -> bytes:
    """Verifica que el contenido recibido realmente sea un PNG."""
    if payload.startswith(PNG_SIGNATURE):
        return payload
    preview = payload[:160].decode("utf-8", errors="replace").strip()
    preview = preview.replace("\n", " ")
    raise ValueError(f"{source} no devolvio un PNG valido: {preview[:100]}")


def _request_png(method: str, url: str, source: str, **kwargs) -> bytes:
    resp = requests.request(method, url, timeout=30, **kwargs)
    resp.raise_for_status()
    return _ensure_png_bytes(resp.content, source)


def _looks_like_mermaid(code: str) -> bool:
    stripped = code.strip()
    if not stripped:
        return False
    first_line = stripped.splitlines()[0].strip()
    return any(first_line.startswith(token) for token in MERMAID_STARTS)


def _looks_like_plantuml(code: str) -> bool:
    stripped = code.strip()
    if not stripped:
        return False
    if stripped.startswith("@startuml") or stripped.startswith("@startmindmap"):
        return True
    first_line = stripped.splitlines()[0].strip().lower()
    return first_line.startswith(("actor ", "participant ", "entity ", "class ")) and (
        "-->" in stripped or "->" in stripped or "--" in stripped
    )


def _infer_diagram_type(code: str) -> str:
    if _looks_like_plantuml(code):
        return "plantuml"
    if _looks_like_mermaid(code):
        return "mermaid"
    return ""


def _strip_fence_label(code: str) -> str:
    stripped = code.strip()
    lines = stripped.splitlines()
    if not lines:
        return stripped
    first = lines[0].strip().lower()
    if first in {"mermaid", "plantuml", "puml", "uml"}:
        return "\n".join(lines[1:]).strip()
    return stripped


def _cleanup_extracted_code(code: str) -> str:
    return code.strip().strip("`").strip()


def _ensure_plantuml_wrapper(code: str) -> str:
    stripped = code.strip()
    if stripped.startswith("@startuml") or stripped.startswith("@startmindmap"):
        return stripped
    return f"@startuml\n{stripped}\n@enduml"


def _extract_plain_diagram(response: str) -> tuple[str, str]:
    text = response.strip()
    if _looks_like_plantuml(text):
        end = re.search(r"@enduml", text, re.IGNORECASE)
        if end:
            return text[:end.end()].strip(), "plantuml"

    lines = text.splitlines()
    for idx, line in enumerate(lines):
        candidate = line.strip()
        if not candidate:
            continue
        if _looks_like_plantuml(candidate):
            tail = "\n".join(lines[idx:]).strip()
            end = re.search(r"@enduml", tail, re.IGNORECASE)
            if end:
                return tail[:end.end()].strip(), "plantuml"
        if _looks_like_mermaid(candidate):
            block = [line]
            for extra in lines[idx + 1:]:
                stripped = extra.strip()
                if stripped.startswith("```"):
                    break
                if block and not stripped and len(block) > 2:
                    break
                if stripped.startswith(("**", "Explic", "Nota:", "Resumen:", "Observa")):
                    break
                if stripped.startswith(("- ", "1.", "2.", "3.")) and len(block) > 2:
                    break
                block.append(extra)
            code = "\n".join(block).strip()
            if _looks_like_mermaid(code):
                return code, "mermaid"
    return "", ""


# ══════════════════════════════════════════════════════════════════
#  Extracción de código
# ══════════════════════════════════════════════════════════════════

def extract_diagram(response: str) -> tuple[str, str]:
    """
    Devuelve (código_diagrama, tipo) donde tipo es 'mermaid' o 'plantuml'.
    Busca bloques de código en el response del LLM.
    """
    patterns = [
        (r"```mermaid\s*\r?\n(.*?)```",   "mermaid"),
        (r"```plantuml\s*\r?\n(.*?)```",  "plantuml"),
        (r"```puml\s*\r?\n(.*?)```",      "plantuml"),
        (r"```uml\s*\r?\n(.*?)```",       "plantuml"),
        (r"@startuml(.*?)@enduml",     "plantuml"),
    ]
    for pattern, dtype in patterns:
        m = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
        if m:
            code = _cleanup_extracted_code(m.group(1))
            # Aseguramos envoltura @startuml si es plantuml sin ella
            if dtype == "plantuml" and not code.startswith("@startuml"):
                code = f"@startuml\n{code}\n@enduml"
            return code, dtype

    generic_blocks = re.findall(r"```([^\r\n`]*)\r?\n(.*?)```", response, re.DOTALL)
    for label, block in generic_blocks:
        label = label.strip().lower()
        code = _cleanup_extracted_code(block)
        if label in {"plantuml", "puml", "uml"}:
            dtype = "plantuml"
        elif label == "mermaid":
            dtype = "mermaid"
        else:
            code = _cleanup_extracted_code(_strip_fence_label(code))
            dtype = _infer_diagram_type(code)
        if dtype:
            if dtype == "plantuml" and not code.startswith("@startuml"):
                code = f"@startuml\n{code}\n@enduml"
            return code, dtype

    return _extract_plain_diagram(response)


# ══════════════════════════════════════════════════════════════════
#  Renderizado en terminal
# ══════════════════════════════════════════════════════════════════

def render_terminal(code: str, dtype: str):
    """Muestra el diagrama con syntax highlighting en la terminal."""
    lang = "yaml" if dtype == "mermaid" else "text"
    syn = Syntax(code, lang, theme="monokai", line_numbers=True)
    console.print(Panel(
        syn,
        title=f"[bold cyan]📊 Diagrama ({dtype.upper()})[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    ))


# ══════════════════════════════════════════════════════════════════
#  Exportación PNG — Mermaid
# ══════════════════════════════════════════════════════════════════

def _mermaid_to_png_bytes(mermaid_code: str) -> bytes:
    """
    Obtiene el PNG de mermaid.ink usando POST (soporta diagramas grandes).
    Si falla, intenta con el método GET tradicional.
    """
    errors = []

    # Método 1: Kroki acepta el código Mermaid como texto plano.
    try:
        return _request_png(
            "POST",
            f"{KROKI_URL}/mermaid/png",
            "Kroki Mermaid",
            data=mermaid_code.encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
    except Exception as e:
        errors.append(f"Kroki Mermaid: {e}")

    # Método 2: mermaid.ink con codificación pako compatible con Mermaid Live.
    try:
        encoded = _encode_mermaid_ink(mermaid_code)
        url = f"{MERMAID_INK_URL}/img/{encoded}?type=png&bgColor=!white"
        return _request_png("GET", url, "mermaid.ink (pako)")
    except Exception as e:
        errors.append(f"mermaid.ink pako: {e}")

    # Método 3: codificación base64 antigua para compatibilidad.
    try:
        encoded = base64.urlsafe_b64encode(
            mermaid_code.encode("utf-8")
        ).decode("utf-8").rstrip("=")
        url = f"{MERMAID_INK_URL}/img/{encoded}?type=png&bgColor=!white"
        return _request_png("GET", url, "mermaid.ink (base64)")
    except Exception as e:
        errors.append(f"mermaid.ink base64: {e}")

    raise RuntimeError(" | ".join(errors))


def _encode_mermaid_ink(mermaid_code: str) -> str:
    payload = json.dumps(
        {"code": mermaid_code, "mermaid": {"theme": "default"}},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    compressed = zlib.compress(payload, level=9)[2:-4]
    encoded = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
    return f"pako:{encoded}"

# ══════════════════════════════════════════════════════════════════
#  Exportación PNG — PlantUML
# ══════════════════════════════════════════════════════════════════

# Tabla de codificación PlantUML (no es Base64 estándar)
_PLANTUML_CHARS = (
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
)

def _encode_plantuml(puml_code: str) -> str:
    """Comprime y codifica el código PlantUML para la URL del servidor."""
    data = zlib.compress(puml_code.encode("utf-8"))[2:-4]  # sin cabecera zlib
    result = []
    i = 0
    while i < len(data):
        b0 = data[i]
        b1 = data[i + 1] if i + 1 < len(data) else 0
        b2 = data[i + 2] if i + 2 < len(data) else 0
        result.append(_PLANTUML_CHARS[(b0 >> 2) & 0x3F])
        result.append(_PLANTUML_CHARS[((b0 & 0x3) << 4) | ((b1 >> 4) & 0xF)])
        result.append(_PLANTUML_CHARS[((b1 & 0xF) << 2) | ((b2 >> 6) & 0x3)])
        result.append(_PLANTUML_CHARS[b2 & 0x3F])
        i += 3
    return "".join(result)

def _plantuml_to_png_bytes(puml_code: str) -> bytes:
    """Convierte PlantUML a PNG usando el servidor PlantUML y Kroki como fallback."""
    puml_code = _ensure_plantuml_wrapper(puml_code)
    encoded = _encode_plantuml(puml_code)
    errors = []

    try:
        return _request_png(
            "POST",
            f"{KROKI_URL}/plantuml/png",
            "Kroki PlantUML",
            data=puml_code.encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
    except Exception as e:
        errors.append(f"Kroki PlantUML: {e}")

    for server in (PLANTUML_SERVER, "https://plantuml.io/plantuml"):
        try:
            return _request_png(
                "GET",
                f"{server}/png/{encoded}",
                f"PlantUML server ({server})",
            )
        except Exception as e:
            errors.append(f"{server}: {e}")

    raise RuntimeError(" | ".join(errors))

# ══════════════════════════════════════════════════════════════════
#  Guardado de archivos
# ══════════════════════════════════════════════════════════════════

def save_diagram(code: str, dtype: str, kind: str = "", output_dir: str | None = None) -> dict:
    """
    Guarda el diagrama en texto y exporta PNG.
    Devuelve {'text': ruta_texto, 'png': ruta_png | None, 'error': msg | None}
    """
    out = Path(output_dir or OUTPUT_DIR).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = kind.replace("-", "_") if kind else "diagram"
    ext  = "mmd" if dtype == "mermaid" else "puml"

    # ── Archivo de texto ────────────────────────────────────────────
    text_path = out / f"{slug}_{ts}.{ext}"
    text_path.write_text(code, encoding="utf-8")

    # ── PNG ─────────────────────────────────────────────────────────
    png_path = out / f"{slug}_{ts}.png"
    png_error = None
    try:
        if dtype == "mermaid":
            png_bytes = _mermaid_to_png_bytes(code)
        else:
            png_bytes = _plantuml_to_png_bytes(code)
        png_path.write_bytes(png_bytes)
    except Exception as e:
        png_path  = None
        png_error = str(e)

    return {
        "text":  str(text_path),
        "png":   str(png_path) if png_path else None,
        "error": png_error,
    }
