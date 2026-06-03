import os
from dotenv import load_dotenv

load_dotenv()

# ── API OpenCode Zen ────────────────────────────────────────────────
OPENCODE_API_KEY  = os.getenv("OPENCODE_API_KEY", "")
OPENCODE_BASE_URL = "https://opencode.ai/zen/v1"

AVAILABLE_MODELS = {
    "hy3":      "hy3-preview-free",      # ← Cambiado
    "nemotron": "nemotron-3-super-free", # ← Cambiado
    "minimax":  "minimax-m2.5-free",     # ← Cambiado
    "default":  "minimax-m2.5-free",     # ← Cambiado
}

FREE_MODEL_MARKERS = ("free", "gratis")

# ── App ────────────────────────────────────────────────────────────
APP_NAME    = "ArquiSysAI"
APP_VERSION = "2.0.0"

# ── Sesión ─────────────────────────────────────────────────────────
MAX_HISTORY = 20
SESSION_DIR = "sessions"

# ── Diagramas ──────────────────────────────────────────────────────
OUTPUT_DIR     = "output_diagrams"
DEFAULT_FORMAT = "mermaid"   # "mermaid" | "plantuml"
MAX_VALIDATION_ITERATIONS = 3

SUPPORTED_DIAGRAM_TYPES = [
    "uml-clase", "uml-secuencia", "uml-caso-uso", "uml-flujo",
    "bpmn", "er", "c4-contexto", "c4-contenedor", "arquitectura",
]

RECOMMENDED_FORMAT_BY_TYPE = {
    "uml-caso-uso": "plantuml",
}

# ── Exportación PNG ────────────────────────────────────────────────
# Servidor público PlantUML para renderizar PNG
PLANTUML_SERVER = "https://www.plantuml.com/plantuml"
# Servidor Mermaid.ink para renderizar PNG
MERMAID_INK_URL = "https://mermaid.ink"
# Kroki como fallback para Mermaid y PlantUML
KROKI_URL = "https://kroki.io"
