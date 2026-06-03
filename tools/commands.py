import shlex
from dataclasses import dataclass

HELP_TEXT = """
╔═══════════════════════════════════════════════════════════════╗
║           ArquiSysAI — Comandos de Terminal                   ║
╠═══════════════════════════════════════════════════════════════╣
║  /read <archivo>        → Carga un archivo al contexto        ║
║  /read -f <carpeta>     → Carga toda una carpeta de código    ║
║  /tree <carpeta>        → Muestra árbol de directorios        ║
║  /tipo <tipo>           → Fuerza tipo de diagrama             ║
║     uml-clase  uml-secuencia  uml-caso-uso  uml-flujo         ║
║     bpmn  er  c4-contexto  c4-contenedor  arquitectura        ║
║  /formato <mermaid|plantuml>  → Cambia formato de salida      ║
║  /modelo <hy3|nemotron|minimax>  → Cambia modelo LLM          ║
║  /save                  → Guarda último diagrama + PNG        ║
║  /clear                 → Limpia contexto y conversación      ║
║  /contexto              → Muestra archivos cargados           ║
║  /help                  → Muestra esta ayuda                  ║
║  /exit                  → Sale de la aplicación               ║
╠═══════════════════════════════════════════════════════════════╣
║  O escribe tu solicitud directo en lenguaje natural:          ║
║  "Genera un diagrama ER para un sistema de ventas"            ║
║  "Analiza este código y crea un diagrama de clases"           ║
╚═══════════════════════════════════════════════════════════════╝
"""


@dataclass
class Cmd:
    command: str
    args: list[str]


def parse(text: str):
    """Devuelve Cmd si el texto empieza con '/', None si no."""
    text = text.strip()
    if not text.startswith("/"):
        return None
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    return Cmd(command=parts[0].lstrip("/").lower(), args=parts[1:])