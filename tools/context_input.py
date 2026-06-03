"""
Módulo de ingreso de contexto textual enriquecido.
Permite al usuario escribir o pegar bloques de texto largos
que se incorporan al contexto de la sesión sin necesidad
de leer archivos del disco.
"""
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

console = Console()

_STYLE = Style.from_dict({"prompt": "#ffaf00 bold"})


def collect_multiline_text(header: str = "") -> str:
    """
    Abre un editor de líneas múltiples en la terminal.
    El usuario escribe o pega texto. Termina con una línea que solo contiene
    '###' o presionando Ctrl+D.
    Devuelve el texto acumulado.
    """
    if header:
        console.print(Panel(
            header,
            title="[bold yellow]📝 Ingreso de Contexto Textual[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
        ))

    console.print(
        "[dim yellow]Escribe o pega tu contexto. "
        "Cuando termines escribe [bold]###[/bold] en una línea nueva "
        "o presiona [bold]Ctrl+D[/bold].[/dim yellow]\n"
    )

    ps = PromptSession(style=_STYLE)
    lines: list[str] = []

    while True:
        try:
            line = ps.prompt(HTML('<span style="color:#ffaf00">  … </span>'))
            if line.strip() == "###":
                break
            lines.append(line)
        except EOFError:
            break
        except KeyboardInterrupt:
            console.print("[yellow]Ingreso cancelado.[/yellow]")
            return ""

    return "\n".join(lines).strip()


def ingest_text_context(session, label: str = "texto-manual") -> bool:
    """
    Orquesta la captura y carga del contexto textual en la sesión.
    Devuelve True si se cargó algo.
    """
    header = (
        "Puedes pegar una descripción detallada de tu sistema, módulo o proceso.\n"
        "Ejemplo:\n"
        "  'Genera el paquete completo (Casos de Uso, Secuencia, BPMN, ER)\n"
        "   para el módulo de Asignación de Repartidores de una App de Delivery…'"
    )
    text = collect_multiline_text(header)

    if not text:
        console.print("[yellow]⚠ No se ingresó ningún texto.[/yellow]")
        return False

    lines = text.count("\n") + 1
    preview = text[:200] + ("…" if len(text) > 200 else "")

    console.print(Panel(
        Syntax(preview, "text", theme="monokai"),
        title=f"[green]✓ Contexto cargado ({lines} líneas)[/green]",
        border_style="green",
    ))

    session.add_code_context(
        f"# Contexto textual — {label}\n{text}",
        source=f"texto:{label}",
    )
    console.print(
        "[dim]Ahora escribe tu solicitud, usa /tipo <tipo> + F5 para un diagrama, "
        "o /multidiagrama all para el paquete completo.[/dim]\n"
    )
    return True
