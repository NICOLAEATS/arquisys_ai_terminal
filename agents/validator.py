"""
Agente 3 — Validador
Recibe el código del diagrama generado por el Arquitecto,
detecta errores de sintaxis y los corrige automáticamente.
Devuelve (código_validado, fue_corregido: bool, razón: str).
"""
import re
from rich.console import Console
from core.api_client import OpenCodeClient
from core.session import DiagramSession
from core.renderer import extract_diagram

console = Console()


class ValidatorAgent:

    def __init__(self):
        self.client = OpenCodeClient(model_key="default")

    def validate(
        self,
        diagram_code: str,
        diagram_type: str,   # "mermaid" | "plantuml"
        session: DiagramSession,
    ) -> tuple[str, bool, str]:
        """
        Valida y, si es necesario, corrige el diagrama.
        Retorna (código_final, fue_corregido, razón).
        """
        user_msg = (
            f"Valida y corrige si es necesario el siguiente diagrama {diagram_type}:\n\n"
            f"Tipo funcional esperado: {session.forced_type or session.last_diagram_kind or 'auto'}\n"
            "Mantén el mismo tipo funcional del diagrama; no generes un paquete ni diagramas adicionales.\n\n"
            f"```{diagram_type}\n{diagram_code}\n```"
        )

        try:
            response = self.client.chat_text(
                messages=[
                    {"role": "system", "content": session.build_validator_prompt()},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=0.1,
                max_tokens=2000,
            )
        except Exception as e:
            return diagram_code, False, f"validador no disponible: {e}"

        # ── Extraer código validado ──────────────────────────────────
        validated_code, _ = extract_diagram(response)
        if not validated_code:
            # Si no encontró bloque, buscar @startuml/@enduml inline
            m = re.search(r"@startuml(.*?)@enduml", response, re.DOTALL)
            validated_code = m.group(0).strip() if m else diagram_code

        # ── Determinar si fue corregido ──────────────────────────────
        corrected = False
        reason    = "sin cambios"
        m2 = re.search(r"VALIDACIÓN:\s*(.*)", response, re.IGNORECASE)
        if m2:
            val_line = m2.group(1).strip()
            if "CORREGIDO" in val_line.upper():
                corrected = True
                reason = val_line
            else:
                reason = "OK"

        return validated_code, corrected, reason

    def _print_status(self, corrected: bool, reason: str):
        if corrected:
            console.print(f"[yellow]🔧 Validador corrigió: {reason}[/yellow]")
        else:
            console.print(f"[green]✔ Validador: {reason}[/green]")
