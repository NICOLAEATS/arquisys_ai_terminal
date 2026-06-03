"""
Genera un paquete completo de diagramas (multi-diagrama)
a partir del contexto actual de la sesión.
Tipos: Casos de Uso, Secuencia, BPMN, ER.
Cada uno pasa por el pipeline completo Analista→Arquitecto→Validador.
"""
from rich.console import Console
from core.renderer import save_diagram, render_terminal
from core.orchestrator import generate_validated_diagram
from config import RECOMMENDED_FORMAT_BY_TYPE

console = Console()

PACKAGE_TYPES = [
    ("uml-caso-uso",  "Diagrama de Casos de Uso"),
    ("uml-secuencia", "Diagrama de Secuencia"),
    ("bpmn",          "Diagrama BPMN de Proceso"),
    ("er",            "Modelo Entidad-Relación"),
]


def _emit(logger, level: str, message: str):
    if logger:
        logger(level, message)
        return

    if level == "section":
        console.rule(f"[cyan]{message}[/cyan]")
    elif level == "ok":
        console.print(f"[green]{message}[/green]")
    elif level == "warn":
        console.print(f"[yellow]{message}[/yellow]")
    elif level == "error":
        console.print(f"[red]{message}[/red]")
    else:
        console.print(message)


def _run_package(session, architect, validator, package_types, logger=None, code_logger=None):
    if not session.code_context:
        _emit(
            logger,
            "error",
            "No hay contexto cargado. Usa /ctx para ingresar texto o /read para cargar archivos.",
        )
        return []

    results = []
    total = len(package_types)
    original_forced = session.forced_type

    _emit(logger, "system", f"Generando paquete de {total} diagramas...")

    try:
        for i, (tipo, label) in enumerate(package_types, 1):
            _emit(logger, "section", f"({i}/{total}) {label}")

            session.forced_type = tipo
            prompt = (
                f"Basándote UNICAMENTE en el contexto ya cargado, "
                f"genera el {label} completo y detallado. "
                f"Aplica mejores prácticas de arquitectura. "
                f"La respuesta debe comenzar con un unico bloque de codigo valido del diagrama."
            )
            if getattr(session, "pending_request", ""):
                prompt += f"\nSolicitud adicional del usuario: {session.pending_request}"
            diagram_format = RECOMMENDED_FORMAT_BY_TYPE.get(tipo, session.export_format)
            if diagram_format != session.export_format:
                _emit(logger, "warn", f"{tipo} se generara en {diagram_format} por compatibilidad.")
            analysis = {
                "tipo_diagrama":         tipo,
                "tiene_suficiente_info": True,
                "pregunta_faltante":     None,
                "formato_sugerido":      diagram_format,
                "confianza":             "alta",
                "solicitud_enriquecida": prompt,
            }

            result = generate_validated_diagram(
                prompt,
                session,
                analysis,
                architect,
                validator,
                logger=logger,
                error_handler=lambda msg: _emit(logger, "error", f"Error Arquitecto: {msg}"),
            )
            if not result.code:
                _emit(logger, "error", f"No se pudo generar {label}.")
                for err in result.errors:
                    _emit(logger, "error", err)
                continue

            validated = result.code
            dtype = result.dtype
            _emit(
                logger,
                "agent",
                f"SUPERVISOR: {label}: orquestacion {result.backend} en {result.iterations} iteracion(es)",
            )

            if code_logger:
                code_logger(label, validated, dtype)
            else:
                render_terminal(validated, dtype)

            saved = save_diagram(validated, dtype, tipo, output_dir=session.output_dir)
            _emit(logger, "ok", f"Texto: {saved['text']}")
            if saved["png"]:
                _emit(logger, "ok", f"PNG  : {saved['png']}")
            else:
                _emit(logger, "warn", f"PNG  : {saved['error']}")

            results.append({
                "tipo": tipo,
                "label": label,
                "text": saved["text"],
                "png": saved.get("png"),
                "error": saved.get("error"),
            })

            session.last_diagram_code = validated
            session.last_diagram_type = dtype
            session.last_diagram_kind = tipo
    finally:
        session.forced_type = original_forced

    if not results:
        _emit(logger, "warn", "No se generaron diagramas en el paquete.")
        return results

    _emit(logger, "section", "Resumen del paquete")
    for r in results:
        status = "OK" if r.get("png") else "WARN"
        _emit(logger, "system", f"[{status}] {r['label']}")
        _emit(logger, "system", f"    Texto: {r['text']}")
        if r.get("png"):
            _emit(logger, "system", f"    PNG  : {r['png']}")
        elif r.get("error"):
            _emit(logger, "system", f"    PNG  : {r['error']}")

    return results


def generate_package(session, architect, validator, logger=None, code_logger=None):
    """
    Itera sobre PACKAGE_TYPES y genera cada diagrama.
    Usa el contexto de sesión ya cargado.
    """
    return _run_package(
        session,
        architect,
        validator,
        PACKAGE_TYPES,
        logger=logger,
        code_logger=code_logger,
    )

def generate_custom_package(session, architect, validator, selected_types: list, logger=None, code_logger=None):
    """Genera solo los tipos de diagrama seleccionados."""
    package_filtered = [(t, l) for t, l in PACKAGE_TYPES if t in selected_types]

    if not package_filtered:
        _emit(logger, "error", "No se encontraron tipos válidos.")
        return []

    return _run_package(
        session,
        architect,
        validator,
        package_filtered,
        logger=logger,
        code_logger=code_logger,
    )
