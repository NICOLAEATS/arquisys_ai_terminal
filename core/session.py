from dataclasses import dataclass, field
from typing import Optional

from config import OUTPUT_DIR


@dataclass
class DiagramSession:
    """Estado completo de la sesión actual."""

    messages:          list[dict]  = field(default_factory=list)
    code_context:      str         = ""
    context_files:     list[str]   = field(default_factory=list)
    context_entries:   list[dict]  = field(default_factory=list)
    next_context_id:   int         = 1
    last_diagram_code: str         = ""
    last_diagram_type: str         = ""   # "mermaid" | "plantuml"
    last_diagram_kind: str         = ""   # "uml-clase", "bpmn", etc.
    last_response_text: str        = ""
    forced_type:       Optional[str] = None
    export_format:     str         = "mermaid"   # preferencia del usuario
    output_dir:         str         = OUTPUT_DIR
    output_dir_confirmed: bool      = False
    pending_request:    str         = ""

    # ── Contexto ────────────────────────────────────────────────────
    def add_code_context(self, content: str, source: str):
        self.context_entries.append({
            "id": self.next_context_id,
            "source": source,
            "content": content,
        })
        self.next_context_id += 1
        self._rebuild_context()

    def _rebuild_context(self):
        self.context_files = [entry["source"] for entry in self.context_entries]
        self.code_context = "\n\n".join(entry["content"] for entry in self.context_entries)

    def remove_context(self, context_id: int) -> bool:
        before = len(self.context_entries)
        self.context_entries = [
            entry for entry in self.context_entries
            if int(entry.get("id", -1)) != context_id
        ]
        changed = len(self.context_entries) != before
        if changed:
            self._rebuild_context()
        return changed

    def clear_contexts(self):
        self.context_entries.clear()
        self._rebuild_context()

    def latest_context_text(self) -> str:
        if not self.context_entries:
            return ""
        return self.context_entries[-1]["content"]

    def clear(self):
        output_dir = self.output_dir
        output_dir_confirmed = self.output_dir_confirmed
        self.__init__()
        self.output_dir = output_dir
        self.output_dir_confirmed = output_dir_confirmed

    def context_summary(self) -> str:
        if not self.context_files:
            return ""
        return " | ".join(self.context_files)[:40]

    # ── System prompt para el Arquitecto ────────────────────────────
    def build_architect_prompt(self) -> str:
        base = (
            "Eres ArquiSysAI, arquitecto experto en software. "
            "Genera diagramas técnicos precisos y válidos.\n\n"
            "TIPOS SOPORTADOS: UML (clases, secuencia, casos de uso, flujo/actividad), "
            "BPMN, ER, C4 (contexto, contenedores), Arquitectura general.\n\n"
            "REGLAS DE FORMATO:\n"
            "- Para Mermaid usa bloques ```mermaid ... ```\n"
            "- Para PlantUML usa bloques ```plantuml ... ``` o @startuml/@enduml\n"
            "- La respuesta DEBE comenzar con el bloque de codigo del diagrama.\n"
            "- Nunca reemplaces el diagrama por pseudocodigo, listas o descripciones.\n"
            "- El código DEBE ser sintácticamente correcto y completo.\n"
            "- Si el usuario pide un solo tipo de diagrama, genera SOLO ese tipo.\n"
            "- No generes paquetes ni multiples diagramas salvo que el usuario lo pida explicitamente.\n"
            "- Después del bloque de código explica brevemente los elementos clave.\n"
            "- Si falta información crítica, haz UNA sola pregunta concreta.\n"
        )
        if self.forced_type:
            base += (
                f"\nTIPO FORZADO: genera SOLO diagrama tipo '{self.forced_type}'. "
                "No agregues otros diagramas ni un paquete completo.\n"
            )
        if self.export_format:
            base += f"FORMATO PREFERIDO: {self.export_format}.\n"
        if self.code_context:
            ctx = self.code_context[:9000]
            if len(self.code_context) > 9000:
                ctx += "\n[...contexto truncado...]"
            base += f"\nCÓDIGO FUENTE DEL PROYECTO:\n{ctx}\n"
        return base

    # ── System prompt para el Validador ─────────────────────────────
    def build_validator_prompt(self) -> str:
        return (
            "Eres un validador experto en sintaxis de diagramas Mermaid y PlantUML.\n"
            "Tu única tarea es revisar el código de un diagrama y:\n"
            "1. Detectar errores de sintaxis, relaciones inválidas o elementos faltantes.\n"
            "2. Detectar errores conceptuales básicos de UML/BPMN/ER cuando apliquen.\n"
            "3. Si hay errores: CORREGIR el diagrama completo y devolverlo corregido.\n"
            "4. Si está correcto: devolver el bloque exactamente igual, sin cambios.\n\n"
            "RESPONDE SIEMPRE con el bloque de código corregido (o sin cambios si era correcto), "
            "seguido de una línea: 'VALIDACIÓN: OK' o 'VALIDACIÓN: CORREGIDO — <razón breve>'."
        )
