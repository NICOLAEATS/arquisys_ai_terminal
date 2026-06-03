"""
Orquestador Sprint 4: ciclo Arquitecto <-> Validador con limite de iteraciones.
"""
from dataclasses import dataclass, field
from typing import Any, TypedDict

from config import MAX_VALIDATION_ITERATIONS
from core.renderer import extract_diagram

try:
    from langgraph.graph import END, StateGraph
except Exception:  # LangGraph puede no estar instalado en entornos de prueba.
    END = None
    StateGraph = None


class GraphState(TypedDict, total=False):
    user_input: str
    prompt: str
    session: Any
    analysis: dict
    architect: Any
    validator: Any
    max_iterations: int
    attempt: int
    response: str
    code: str
    dtype: str
    latest_validated: str
    latest_dtype: str
    latest_reason: str
    was_fixed: bool
    was_corrected: bool
    errors: list[str]
    logger: Any
    error_handler: Any


@dataclass
class OrchestrationResult:
    code: str = ""
    dtype: str = ""
    response: str = ""
    iterations: int = 0
    was_corrected: bool = False
    reason: str = ""
    errors: list[str] = field(default_factory=list)
    backend: str = "loop"


def _emit(logger, level: str, message: str):
    if logger:
        logger(level, message)


def _revision_prompt(
    original_input: str,
    dtype: str,
    validated_code: str,
    reason: str,
) -> str:
    return (
        f"Solicitud original del usuario:\n{original_input}\n\n"
        "El Agente Validador encontro problemas en la version anterior.\n"
        f"Feedback del Validador: {reason}\n\n"
        "Codigo corregido propuesto por el Validador:\n"
        f"```{dtype}\n{validated_code}\n```\n\n"
        "Regenera una version final del diagrama aplicando ese feedback. "
        "Devuelve primero un unico bloque de codigo valido, sin generar otros diagramas."
    )


def _architect_node(state: GraphState) -> GraphState:
    attempt = int(state.get("attempt", 0)) + 1
    state["attempt"] = attempt
    state.pop("code", None)
    state.pop("dtype", None)
    state["was_fixed"] = False
    max_iterations = int(state.get("max_iterations", MAX_VALIDATION_ITERATIONS))
    _emit(
        state.get("logger"),
        "agent",
        f"ARQUITECTO: Generando diagrama (iteracion {attempt}/{max_iterations})...",
    )

    response = state["architect"].generate(
        state.get("prompt") or state["user_input"],
        state["session"],
        state["analysis"],
        error_handler=state.get("error_handler"),
    )
    state["response"] = response

    if not response:
        state.setdefault("errors", []).append("Arquitecto no devolvio respuesta.")
        return state

    code, dtype = extract_diagram(response)
    if not code:
        state.setdefault("errors", []).append(
            "No se detecto bloque de diagrama en la respuesta del Arquitecto."
        )
        state["prompt"] = (
            f"{state['user_input']}\n\nLa respuesta anterior no incluyo un bloque de codigo valido. "
            "Devuelve exclusivamente un bloque Mermaid o PlantUML valido."
        )
        return state

    state["code"] = code
    state["dtype"] = dtype
    state["latest_dtype"] = dtype
    return state


def _validator_node(state: GraphState) -> GraphState:
    max_iterations = int(state.get("max_iterations", MAX_VALIDATION_ITERATIONS))
    attempt = int(state.get("attempt", 1))
    _emit(
        state.get("logger"),
        "agent",
        f"VALIDADOR: Revisando sintaxis (iteracion {attempt}/{max_iterations})...",
    )

    validated, was_fixed, reason = state["validator"].validate(
        state["code"],
        state["dtype"],
        state["session"],
    )
    state["latest_validated"] = validated
    state["latest_reason"] = reason
    state["was_fixed"] = was_fixed
    state["was_corrected"] = bool(state.get("was_corrected")) or was_fixed

    if was_fixed:
        _emit(state.get("logger"), "agent", f"VALIDADOR: CORREGIDO - {reason}")
        state["prompt"] = _revision_prompt(
            state["user_input"],
            state["dtype"],
            validated,
            reason,
        )
    else:
        _emit(state.get("logger"), "agent", f"VALIDADOR: OK - {reason}")
        state["code"] = validated

    return state


def _route_after_architect(state: GraphState):
    max_iterations = int(state.get("max_iterations", MAX_VALIDATION_ITERATIONS))
    if state.get("code") and state.get("dtype"):
        return "validator"
    if int(state.get("attempt", 0)) < max_iterations:
        return "architect"
    return END


def _route_after_validator(state: GraphState):
    max_iterations = int(state.get("max_iterations", MAX_VALIDATION_ITERATIONS))
    if state.get("was_fixed") and int(state.get("attempt", 0)) < max_iterations:
        return "architect"
    return END


def _build_langgraph_app():
    graph = StateGraph(GraphState)
    graph.add_node("architect", _architect_node)
    graph.add_node("validator", _validator_node)
    graph.set_entry_point("architect")
    graph.add_conditional_edges(
        "architect",
        _route_after_architect,
        {"architect": "architect", "validator": "validator", END: END},
    )
    graph.add_conditional_edges(
        "validator",
        _route_after_validator,
        {"architect": "architect", END: END},
    )
    return graph.compile()


def _state_to_result(state: GraphState, backend: str) -> OrchestrationResult:
    code = state.get("code") or state.get("latest_validated") or ""
    dtype = state.get("dtype") or state.get("latest_dtype") or ""
    if state.get("latest_validated") and state.get("was_fixed"):
        code = state["latest_validated"]
    return OrchestrationResult(
        code=code,
        dtype=dtype,
        response=state.get("response", ""),
        iterations=int(state.get("attempt", 0)),
        was_corrected=bool(state.get("was_corrected")),
        reason=state.get("latest_reason", ""),
        errors=state.get("errors", []),
        backend=backend,
    )


def _generate_with_langgraph(
    user_input: str,
    session,
    analysis: dict,
    architect,
    validator,
    max_iterations: int,
    logger=None,
    error_handler=None,
) -> OrchestrationResult:
    state: GraphState = {
        "user_input": user_input,
        "prompt": user_input,
        "session": session,
        "analysis": analysis,
        "architect": architect,
        "validator": validator,
        "max_iterations": max_iterations,
        "attempt": 0,
        "errors": [],
        "logger": logger,
        "error_handler": error_handler,
        "was_corrected": False,
    }
    final_state = _build_langgraph_app().invoke(state)
    result = _state_to_result(final_state, backend="langgraph")
    if result.code and result.iterations >= max_iterations and result.was_corrected:
        _emit(
            logger,
            "warn",
            f"Se alcanzo el limite de {max_iterations} iteraciones; se usara la ultima version validada.",
        )
    return result


def _generate_with_loop(
    user_input: str,
    session,
    analysis: dict,
    architect,
    validator,
    max_iterations: int,
    logger=None,
    error_handler=None,
) -> OrchestrationResult:
    result = OrchestrationResult(backend="loop")
    prompt = user_input
    latest_validated = ""
    latest_dtype = ""
    latest_reason = "sin validacion"

    for attempt in range(1, max_iterations + 1):
        result.iterations = attempt
        _emit(logger, "agent", f"ARQUITECTO: Generando diagrama (iteracion {attempt}/{max_iterations})...")
        response = architect.generate(
            prompt,
            session,
            analysis,
            error_handler=error_handler,
        )
        result.response = response

        if not response:
            msg = "Arquitecto no devolvio respuesta."
            result.errors.append(msg)
            _emit(logger, "error", msg)
            continue

        code, dtype = extract_diagram(response)
        if not code:
            msg = "No se detecto bloque de diagrama en la respuesta del Arquitecto."
            result.errors.append(msg)
            _emit(logger, "warn", msg)
            prompt = (
                f"{user_input}\n\nLa respuesta anterior no incluyo un bloque de codigo valido. "
                "Devuelve exclusivamente un bloque Mermaid o PlantUML valido."
            )
            continue

        latest_dtype = dtype
        _emit(logger, "agent", f"VALIDADOR: Revisando sintaxis (iteracion {attempt}/{max_iterations})...")
        validated, was_fixed, reason = validator.validate(code, dtype, session)
        latest_validated = validated
        latest_reason = reason
        result.was_corrected = result.was_corrected or was_fixed
        result.reason = reason

        if not was_fixed:
            _emit(logger, "agent", f"VALIDADOR: OK - {reason}")
            result.code = validated
            result.dtype = dtype
            return result

        _emit(logger, "agent", f"VALIDADOR: CORREGIDO - {reason}")
        if attempt < max_iterations:
            prompt = _revision_prompt(user_input, dtype, validated, reason)

    if latest_validated:
        result.code = latest_validated
        result.dtype = latest_dtype
        result.reason = latest_reason or "limite de iteraciones alcanzado"
        _emit(
            logger,
            "warn",
            f"Se alcanzo el limite de {max_iterations} iteraciones; se usara la ultima version validada.",
        )
    elif not result.errors:
        result.errors.append("No se pudo producir un diagrama validado.")

    return result


def generate_validated_diagram(
    user_input: str,
    session,
    analysis: dict,
    architect,
    validator,
    max_iterations: int = MAX_VALIDATION_ITERATIONS,
    logger=None,
    error_handler=None,
) -> OrchestrationResult:
    """Genera, valida y reintenta hasta aprobar o alcanzar el limite."""
    if StateGraph is not None and END is not None:
        return _generate_with_langgraph(
            user_input,
            session,
            analysis,
            architect,
            validator,
            max_iterations,
            logger=logger,
            error_handler=error_handler,
        )

    return _generate_with_loop(
        user_input,
        session,
        analysis,
        architect,
        validator,
        max_iterations,
        logger=logger,
        error_handler=error_handler,
    )
