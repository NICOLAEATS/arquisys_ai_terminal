"""
Agente 2 — Arquitecto
Genera el código del diagrama usando el contexto de sesión.
"""
from core.api_client import OpenCodeClient
from core.session import DiagramSession


class ArchitectAgent:

    def __init__(self):
        self.client = OpenCodeClient(model_key="default")

    def generate(
        self,
        user_input: str,
        session: DiagramSession,
        analysis: dict,
        stream_handler=None,
        error_handler=None,
    ) -> str:
        """Genera el diagrama y devuelve el texto completo."""

        # Enriquecer el mensaje con el análisis del Analista
        enriched = analysis.get("solicitud_enriquecida", user_input)
        tipo      = session.forced_type or analysis.get("tipo_diagrama", "")
        formato   = analysis.get("formato_sugerido", session.export_format)

        user_msg = enriched
        if tipo and tipo != "desconocido":
            user_msg += f"\n[Tipo: {tipo}]"
        if formato:
            user_msg += f"\n[Formato obligatorio: {formato}]"

        session.messages.append({"role": "user", "content": user_msg})

        messages = [
            {"role": "system", "content": session.build_architect_prompt()}
        ] + session.messages[-MAX_CTX:]

        full = ""
        try:
            if stream_handler:
                stream = self.client.chat(
                    messages,
                    temperature=0.3,
                    max_tokens=2500,
                    stream=True,
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content or ""
                    if not delta:
                        continue
                    full += delta
                    stream_handler(delta)
            else:
                full = self.client.chat_text(
                    messages=messages,
                    temperature=0.3,
                    max_tokens=2500,
                )
        except Exception as e:
            if error_handler:
                error_handler(str(e))
            return ""

        session.last_response_text = full
        session.messages.append({"role": "assistant", "content": full})
        return full


MAX_CTX = 12   # Últimos N mensajes que se envían al LLM
