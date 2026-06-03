"""
TUI interactiva para ArquiSysAI.
Usa prompt_toolkit para paneles, mouse, autocompletado y barra de estado.
"""
import sys
import os
import shutil
import subprocess
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.layout.containers import HSplit, VSplit, Window, FloatContainer, Float
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.widgets import TextArea, Frame
from prompt_toolkit.shortcuts import checkboxlist_dialog, input_dialog, radiolist_dialog
from prompt_toolkit.application.current import get_app
from prompt_toolkit.lexers import PygmentsLexer

from rich.console import Console

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    APP_NAME,
    APP_VERSION,
    AVAILABLE_MODELS,
    OPENCODE_BASE_URL,
    SUPPORTED_DIAGRAM_TYPES,
    RECOMMENDED_FORMAT_BY_TYPE,
)
from core.session import DiagramSession
from core.renderer import save_diagram
from core.orchestrator import generate_validated_diagram
from agents.analyst import AnalystAgent
from agents.architect import ArchitectAgent
from agents.validator import ValidatorAgent
from tools.file_reader import read_file, read_folder, get_tree
from tools.context_input import ingest_text_context
from tools.multi_diagram import generate_package, generate_custom_package, PACKAGE_TYPES

console = Console()

# ══════════════════════════════════════════════════════════════════
#  Estilo visual
# ══════════════════════════════════════════════════════════════════

STYLE = Style.from_dict({
    "frame.border":                       "#444444",
    "frame.label":                        "#00d7ff bold",
    "output-field":                       "bg:#010409 #c9d1d9",
    "input-field":                        "bg:#0d1117 #e6edf3",
    "topbar":                             "bg:#161b22 #00d7ff bold",
    "statusbar":                          "bg:#161b22 #8b949e",
    "statusbar.key":                      "bg:#21262d #58a6ff bold",
    "sidebar":                            "bg:#0d1117 #8b949e",
    "completion-menu":                    "bg:#21262d #e6edf3",
    "completion-menu.completion.current": "bg:#58a6ff #0d1117 bold",
    "scrollbar.background":               "bg:#21262d",
    "scrollbar.button":                   "bg:#58a6ff",
})

# ══════════════════════════════════════════════════════════════════
#  Autocompletado
# ══════════════════════════════════════════════════════════════════

COMMANDS = [
    "/help", "/read", "/read -f", "/tree", "/ctx",
    "/multidiagrama", "/tipo", "/formato", "/modelo", "/modelos",
    "/paquete", "/copy", "/save", "/clear", "/contexto", "/contextos",
    "/carpeta", "/api", "/exit",
]

def build_completer(model_keys=None):
    keys = [k for k in (model_keys or AVAILABLE_MODELS) if k != "default"]
    words = COMMANDS + SUPPORTED_DIAGRAM_TYPES + ["mermaid", "plantuml", "all", "todo", "auto"] + keys
    words += [f"/modelo {k}" for k in keys]
    words += [f"/tipo {t}" for t in SUPPORTED_DIAGRAM_TYPES]
    words += ["/tipo auto"]
    return WordCompleter(words, ignore_case=True, sentence=True)


CMD_COMPLETER = build_completer()

TYPE_ALIASES = {
    "caso de uso": "uml-caso-uso",
    "casos de uso": "uml-caso-uso",
    "use case": "uml-caso-uso",
    "use cases": "uml-caso-uso",
    "clase": "uml-clase",
    "clases": "uml-clase",
    "secuencia": "uml-secuencia",
    "secuencias": "uml-secuencia",
    "flujo": "uml-flujo",
    "actividad": "uml-flujo",
    "proceso": "bpmn",
    "procesos": "bpmn",
    "entidad relacion": "er",
    "entidad-relacion": "er",
    "entidad relación": "er",
    "relacional": "er",
    "contexto": "c4-contexto",
    "contenedor": "c4-contenedor",
    "contenedores": "c4-contenedor",
}


def resolve_diagram_type(value: str) -> str:
    normalized = value.lower().strip().replace("_", "-")
    normalized = " ".join(normalized.split())
    dashed = normalized.replace(" ", "-")
    if dashed in SUPPORTED_DIAGRAM_TYPES:
        return dashed
    if normalized in TYPE_ALIASES:
        return TYPE_ALIASES[normalized]
    if dashed in TYPE_ALIASES:
        return TYPE_ALIASES[dashed]
    return ""


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.replace("_", "-")
    return " ".join(normalized.split())


def infer_package_types_from_text(text: str) -> list[str]:
    """Detecta si el contexto pide explicitamente solo ciertos diagramas."""
    normalized = _normalize_text(text)
    if not normalized:
        return []
    if any(token in normalized for token in ("paquete completo", "todos los diagramas", "todo el paquete")):
        return []

    restrictive = any(
        token in normalized
        for token in ("solo", "solamente", "unicamente", "unicamente", "quiero solo")
    )

    detected: list[str] = []
    for phrase, dtype in TYPE_ALIASES.items():
        phrase_norm = _normalize_text(phrase)
        if phrase_norm in normalized and dtype not in detected:
            detected.append(dtype)

    for dtype in SUPPORTED_DIAGRAM_TYPES:
        if dtype in normalized and dtype not in detected:
            detected.append(dtype)

    valid_package_types = {tipo for tipo, _ in PACKAGE_TYPES}
    detected = [dtype for dtype in detected if dtype in valid_package_types]

    if restrictive and detected:
        return detected
    if len(detected) == 1 and "diagrama" in normalized:
        return detected
    return []

HELP_COMMANDS = [
    ("/help", "Muestra esta ayuda"),
    ("/read <archivo>", "Carga un archivo al contexto"),
    ("/read -f <carpeta>", "Carga una carpeta completa"),
    ("/tree <carpeta>", "Muestra el arbol de directorios"),
    ("/ctx", "Abre el editor de contexto textual"),
    ("/contextos", "Lista/borra contextos cargados"),
    ("/contextos borrar <id>", "Borra un contexto"),
    ("/contextos usar <id>", "Deja activo solo ese contexto"),
    ("/contextos limpiar", "Borra todos los contextos"),
    ("/tipo <tipo|auto>", "Fuerza o libera el tipo"),
    ("/formato mermaid|plantuml", "Cambia el formato de salida"),
    ("/modelo", "Abre selector de modelos"),
    ("/modelo <alias|numero>", "Cambia el modelo activo"),
    ("/modelos", "Actualiza/lista modelos gratis"),
    ("/multidiagrama [all]", "Genera paquete o tipo forzado"),
    ("/paquete <tipos...>", "Genera solo tipos concretos"),
    ("/copy [salida|codigo|errores|respuesta|contexto]", "Copia al portapapeles"),
    ("/carpeta [ruta]", "Ver/cambiar carpeta de exportacion"),
    ("/api [status|set|base|clear]", "Ver/cambiar API OpenCode Zen"),
    ("/save", "Guarda el ultimo diagrama y su PNG"),
    ("/clear", "Limpia la sesion y la pantalla"),
    ("/exit", "Sale de la aplicacion"),
]

HELP_SHORTCUTS = [
    ("Tab", "Autocompletar"),
    ("Enter", "Enviar"),
    ("F1", "Abrir ayuda"),
    ("F2", "Editor ctx-texto"),
    ("F3", "Selector modelo"),
    ("F5", "Paquete/tipo forzado"),
    ("F6", "Copiar codigo"),
    ("F7", "Copiar salida"),
    ("Ctrl+S", "Guardar diagrama"),
    ("Ctrl+L", "Limpiar salida"),
    ("PgUp/Dn", "Scroll del area de trabajo"),
    ("Home/End", "Ir arriba/abajo"),
    ("Ctrl+Q", "Salir"),
]


def _build_help_text() -> str:
    lines = ["Comandos disponibles:", ""]
    for cmd, desc in HELP_COMMANDS:
        lines.append(f"  {cmd:<28} {desc}")

    lines.extend([
        "",
        "Tipos para /tipo:",
        "  uml-clase, uml-secuencia, uml-caso-uso, uml-flujo,",
        "  bpmn, er, c4-contexto, c4-contenedor, arquitectura",
        "",
        "Tipos para /paquete:",
        "  uml-caso-uso, uml-secuencia, bpmn, er",
        "",
        "Atajos:",
    ])

    for key, desc in HELP_SHORTCUTS:
        lines.append(f"  {key:<10} {desc}")
    return "\n".join(lines)


HELP_TEXT = _build_help_text()


# ══════════════════════════════════════════════════════════════════
#  TUI principal
# ══════════════════════════════════════════════════════════════════

class ArquiSysAI_TUI:

    
    def __init__(self):
        self.session    = DiagramSession()
        self.analyst    = AnalystAgent()
        self.architect  = ArchitectAgent()
        self.validator  = ValidatorAgent()

        self.log_lines: list[str] = []
        self.status_msg   = ("ok", "Listo")
        self.available_models = dict(AVAILABLE_MODELS)
        self.current_model_key = "default"
        self.current_model = self.available_models["default"]
        self.cmd_completer = build_completer(self.available_models.keys())
        self.processing    = False

        self._refresh_models(silent=True)

        # ── Buffers ──────────────────────────────────────────────
        self.output_buffer = Buffer(name="output", read_only=True)

        self.input_buffer = Buffer(
            name="input",
            completer=self.cmd_completer,
            complete_while_typing=True,
        )

        self._build_layout()
        self._build_keybindings()
        self._build_app()

        self._log_system(
            f"ArquiSysAI v{APP_VERSION} iniciado  |  modelo: {self.current_model}\n"
            "Escribe tu solicitud en lenguaje natural o usa /help para ver comandos.\n"
            "F2 = editor de contexto textual  |  F3 = modelos  |  F5 = paquete/tipo forzado  |  Tab = autocompletar"
        )

    def _cmd_paquete(self, args):
        """Genera paquete con tipos específicos o todos por defecto."""
        validos = dict(PACKAGE_TYPES)
        force_all = args and args[0].lower() in {"all", "todo", "todos", "full"}
        if force_all:
            self._start_thread(lambda: self._cmd_multidiagrama(["all"]))
            return

        if not args:
            try:
                get_app().exit(result="__f5__")
            except Exception:
                self._log_warn("Usa /paquete <tipo...> o F5 para seleccionar diagramas.")
            return

        joined = " ".join(args)
        resolved = resolve_diagram_type(joined)
        tipos = [t for t in args if t in validos]
        if not tipos and resolved in validos:
            tipos = [resolved]
        if tipos:
            self._log_system(f"Generando paquete personalizado: {', '.join(tipos)}")
            self._start_thread(lambda: self._run_custom_package(tipos))
        else:
            self._log_err(f"Tipos no validos. Opciones: {', '.join(validos.keys())}")

                
    # ══════════════════════════════════════════════════════════════
    #  Log
    # ══════════════════════════════════════════════════════════════

    def _log(self, text: str, prefix: str = ""):
        ts = datetime.now().strftime("%H:%M:%S")
        for line in (text.splitlines() or [""]):
            self.log_lines.append(f"[{ts}] {prefix}{line}")
        self._flush_output()

    def _log_block(self, title: str, text: str, prefix: str = ""):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_lines.append(f"[{ts}] {prefix}{title}")
        if text:
            for line in text.splitlines():
                self.log_lines.append(f"    {line}" if line else "    ")
        self._flush_output()

    def _log_code(self, title: str, code: str):
        numbered = "\n".join(
            f"{idx:>3} | {line}" for idx, line in enumerate(code.splitlines(), 1)
        )
        self._log_block(title, numbered)

    def _log_system(self, t): self._log(t, "[INFO] ")
    def _log_user(self, t):   self._log(t, "> ")
    def _log_agent(self, a, t): self._log(t, f"[{a}] ")
    def _log_ok(self, t):     self._log(t, "[OK] ")
    def _log_warn(self, t):   self._log(t, "[WARN] ")
    def _log_err(self, t):    self._log(t, "[ERR] ")

    def _show_help(self):
        self._log_block("Ayuda", HELP_TEXT, "[INFO] ")

    def _flush_output(self):
        content = "\n".join(self.log_lines[-800:])
        doc = Document(content, cursor_position=len(content))
        try:
            self.output_buffer.set_document(doc, bypass_readonly=True)
            get_app().invalidate()
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    #  Textos dinámicos de barras y sidebar
    # ══════════════════════════════════════════════════════════════

    def _topbar_text(self):
        ctx   = len(self.session.context_files)
        proc  = "  ⟳ PROCESANDO …" if self.processing else ""
        fmt   = self.session.export_format
        tipo  = self.session.forced_type or "auto"
        model = self.current_model_key or self.current_model
        return HTML(
            f'<topbar>  ArquiSysAI v{APP_VERSION}'
            f'  │  modelo:{model}'
            f'  │  ctx:{ctx}  fmt:{fmt}  tipo:{tipo}'
            f'{proc}  </topbar>'
        )

    def _statusbar_text(self):
        _, msg = self.status_msg
        keys = [
            ("Tab","completar"), ("F1","ayuda"), ("F2","ctx-texto"), ("F3","modelo"),
            ("F5","multi"), ("F6","copiar cod"), ("F7","copiar salida"), ("Ctrl+S","guardar"),
            ("PgUp/Dn","scroll"), ("Home/End","top/bot"), ("Ctrl+Q","salir"),
        ]
        parts = "  ".join(
            f'<statusbar.key> {k} </statusbar.key> {v}' for k, v in keys
        )
        return HTML(f'  {parts}    {msg}')

    def _sidebar_text(self):
        lines = []

        def add(text, cls="sidebar"):
            lines.append((f"class:{cls}", text))

        add("  ╔═ CONTEXTO ═══════════╗\n", "frame.label")
        if self.session.context_files:
            for f in self.session.context_files[-6:]:
                short = ("…" + f[-24:]) if len(f) > 26 else f
                add(f"  │ {short}\n")
        else:
            add("  │ (sin archivos)\n")
        add("  ╠═ TIPO ══════════════╣\n", "frame.label")
        add(f"  │ {self.session.forced_type or 'auto-detect'}\n")
        add("  ╠═ FORMATO ═══════════╣\n", "frame.label")
        add(f"  │ {self.session.export_format}\n")
        add("  ╠═ PAQUETE ════════════╣\n", "frame.label")
        for _, label in PACKAGE_TYPES:
            add(f"  │ · {label}\n")
        add("  ╠═ COMANDOS ═══════════╣\n", "frame.label")
        for cmd in COMMANDS:
            add(f"  │ {cmd}\n")
        add("  ╚══════════════════════╝\n", "frame.label")
        return lines

    # ══════════════════════════════════════════════════════════════
    #  Layout
    # ══════════════════════════════════════════════════════════════

    def _build_layout(self):
        # Área de salida — Window con BufferControl (sin buffer= en TextArea)
        output_window = Window(
            content=BufferControl(
                buffer=self.output_buffer,
                focusable=False,
            ),
            style="class:output-field",
            wrap_lines=True,
            always_hide_cursor=True,
            right_margins=[ScrollbarMargin(display_arrows=True)],
        )

        # Área de entrada — TextArea sin pasar buffer=
        self.input_area = TextArea(
            height=3,
            prompt="> ",
            style="class:input-field",
            multiline=False,
            wrap_lines=False,
            completer=self.cmd_completer,
            complete_while_typing=True,
            accept_handler=self._on_accept,
        )
        # Vinculamos el buffer interno del TextArea al nuestro
        # (prompt_toolkit crea su propio buffer internamente)
        self.input_area.buffer.completer = self.cmd_completer

        sidebar = Window(
            content=FormattedTextControl(
                self._sidebar_text,
                focusable=False,
            ),
            style="class:sidebar",
            width=30,
        )

        body = VSplit([
            sidebar,
            Window(width=1, char="│", style="class:frame.border"),
            HSplit([
                Frame(
                    output_window,
                    title="Area de trabajo  (salida, codigo y comandos)",
                ),
                Frame(
                    self.input_area,
                    title="Consola de entrada  (Tab=autocompletar)",
                ),
            ]),
        ])

        # FloatContainer para menú de autocompletado
        body_with_float = FloatContainer(
            content=body,
            floats=[
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=12, scroll_offset=1),
                )
            ],
        )

        root = HSplit([
            Window(
                content=FormattedTextControl(self._topbar_text),
                height=1,
                style="class:topbar",
            ),
            body_with_float,
            Window(
                content=FormattedTextControl(self._statusbar_text),
                height=1,
                style="class:statusbar",
            ),
        ])

        self.layout = Layout(root, focused_element=self.input_area)

    # ══════════════════════════════════════════════════════════════
    #  Key bindings
    # ══════════════════════════════════════════════════════════════

    def _build_keybindings(self):
        kb = KeyBindings()

        @kb.add("c-q")
        @kb.add("c-c")
        def _quit(event):
            event.app.exit()

        @kb.add("c-s")
        def _save(event):
            self._cmd_save()

        @kb.add("c-l")
        def _clear_screen(event):
            self.log_lines.clear()
            self._flush_output()

        @kb.add("f1")
        def _help(event):
            self._show_help()

        @kb.add("f2")
        def _ctx(event):
            if not self.processing:
                event.app.exit(result="__ctx__")

        @kb.add("f3")
        def _model_selector(event):
            if not self.processing:
                event.app.exit(result="__model__")

        @kb.add("f5")
        def _multi(event):
            if not self.processing:
                event.app.exit(result="__f5__")

        @kb.add("f6")
        def _copy_code(event):
            self._cmd_copy(["codigo"])

        @kb.add("f7")
        def _copy_output(event):
            self._cmd_copy(["salida"])

        @kb.add("f10")
        def _sidebar(event):
            get_app().invalidate()  # simple refresh (sidebar siempre visible en este layout)

        @kb.add("pageup")
        def _pgup(event):
            buf = self.output_buffer
            text = buf.text
            line = text[:buf.cursor_position].count('\n')
            target = max(0, line - 20)
            if target == 0:
                new_pos = 0
            else:
                idx = -1
                for _ in range(target):
                    idx = text.index('\n', idx + 1)
                new_pos = idx + 1
            buf.set_document(Document(text, new_pos), bypass_readonly=True)

        @kb.add("pagedown")
        def _pgdn(event):
            buf = self.output_buffer
            text = buf.text
            total = text.count('\n')
            line = text[:buf.cursor_position].count('\n')
            target = min(total, line + 20)
            idx = -1
            for _ in range(target):
                idx = text.index('\n', idx + 1)
            new_pos = idx + 1 if target < total else len(text)
            buf.set_document(Document(text, new_pos), bypass_readonly=True)

        @kb.add("home")
        def _home(event):
            text = self.output_buffer.text
            self.output_buffer.set_document(Document(text, 0), bypass_readonly=True)

        @kb.add("end")
        def _end(event):
            text = self.output_buffer.text
            self.output_buffer.set_document(Document(text, len(text)), bypass_readonly=True)

        self.kb = kb

    def _on_accept(self, buff):
        """Handler cuando el usuario presiona Enter en el TextArea."""
        text = buff.text.strip()
        if text and not self.processing:
            buff.set_document(Document("", 0), bypass_readonly=True)
            logged_text = text
            lower = text.lower()
            if lower.startswith("/api set") or lower.startswith("/api key") or lower.startswith("/api token"):
                logged_text = " ".join(text.split()[:2]) + " ********"
            elif lower.startswith("/api ") and lower not in {"/api", "/api status", "/api ver", "/api show"}:
                logged_text = text.split()[0] + " ********"
            self._log_user(logged_text)
            if text.startswith("/"):
                self._handle_command(text)
            else:
                self.session.pending_request = text
                self._log_ok("Solicitud registrada. Presiona F5 para seleccionar/generar diagramas.")

    # ══════════════════════════════════════════════════════════════
    #  App
    # ══════════════════════════════════════════════════════════════

    def _build_app(self):
        self.app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            style=STYLE,
            mouse_support=True,
            full_screen=True,
        )

    # ══════════════════════════════════════════════════════════════
    #  Comandos
    # ══════════════════════════════════════════════════════════════

    def _handle_command(self, text: str):
        parts = text.strip().lstrip("/").split()
        if not parts:
            return
        cmd, args = parts[0].lower(), parts[1:]

        dispatch = {
            "exit":          lambda: get_app().exit(),
            "quit":          lambda: get_app().exit(),
            "q":             lambda: get_app().exit(),
            "help":          self._show_help,
            "clear":         self._cmd_clear,
            "save":          self._cmd_save,
            "contexto":      lambda: self._cmd_contextos([]),
            "contextos":     lambda: self._cmd_contextos(args),
            "ctx":           lambda: get_app().exit(result="__ctx__"),
            "multidiagrama": lambda: self._cmd_multidiagrama_command(args),
            "copy":          lambda: self._cmd_copy(args),
            "read":          lambda: self._cmd_read(args),
            "tree":          lambda: self._cmd_tree(args),
            "tipo":          lambda: self._cmd_tipo(args),
            "formato":       lambda: self._cmd_formato(args),
            "modelo":        lambda: self._cmd_modelo(args),
            "modelos":       self._cmd_modelos,
            "paquete":       lambda: self._cmd_paquete(args),
            "carpeta":       lambda: self._cmd_carpeta(args),
            "api":           lambda: self._cmd_api(args),
        }

        fn = dispatch.get(cmd)
        if fn:
            fn()
        else:
            self._log_err(f"Comando desconocido: /{cmd}  —  F1 para ayuda")

    def _cmd_clear(self):
        self.session.clear()
        self.log_lines.clear()
        self._flush_output()
        self._log_ok("Sesión y pantalla limpiadas.")

    def _generation_text(self) -> str:
        parts = []
        if self.session.pending_request:
            parts.append(self.session.pending_request)
        latest = self.session.latest_context_text()
        if latest:
            parts.append(latest)
        return "\n\n".join(parts)

    def _set_output_dir(self, folder: str, confirmed: bool = True) -> bool:
        folder = (folder or self.session.output_dir).strip().strip('"')
        if not folder:
            folder = self.session.output_dir
        try:
            path = Path(folder).expanduser()
            path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self._log_err(f"No se pudo preparar la carpeta de exportacion: {e}")
            return False

        self.session.output_dir = str(path)
        self.session.output_dir_confirmed = confirmed
        self._log_ok(f"Carpeta de exportacion: {self.session.output_dir}")
        return True

    def _prompt_output_dir(self) -> bool:
        current = self.session.output_dir
        value = input_dialog(
            title="Carpeta de exportacion",
            text=(
                "Ingresa la carpeta donde se guardaran los diagramas (.mmd/.puml y .png).\n"
                f"Actual: {current}\n"
                "Deja vacio para usar la actual."
            ),
        ).run()
        if value is None:
            self._log_warn("Seleccion de carpeta cancelada.")
            return False
        return self._set_output_dir(value or current, confirmed=True)

    def _ensure_output_dir_selected(self) -> bool:
        if self.session.output_dir_confirmed:
            return True
        return self._prompt_output_dir()

    def _select_f5_types(self) -> list[str] | None:
        validos = dict(PACKAGE_TYPES)
        if self.session.forced_type in validos:
            forced = self.session.forced_type
            values = [
                ("__auto__", f"Detectar automaticamente (actual: {forced})"),
                (forced, validos[forced]),
                ("__all__", "Paquete completo (4 diagramas)"),
            ]
        else:
            values = [("__auto__", "Detectar automaticamente desde solicitud/contexto")]
            values += [(tipo, label) for tipo, label in PACKAGE_TYPES]
            values += [("__all__", "Paquete completo (4 diagramas)")]

        selected = checkboxlist_dialog(
            title="Generar diagramas",
            text=(
                "Selecciona uno o varios diagramas. "
                "Si eliges deteccion automatica se usara la solicitud pendiente y el ultimo contexto."
            ),
            values=values,
        ).run()

        if selected is None:
            return None
        if "__all__" in selected:
            return [tipo for tipo, _ in PACKAGE_TYPES]

        explicit = [tipo for tipo in selected if tipo in validos]
        if explicit:
            return explicit

        inferred = []
        if "__auto__" in selected or not selected:
            if self.session.forced_type in validos:
                inferred = [self.session.forced_type]
            else:
                inferred = infer_package_types_from_text(self._generation_text())
        return inferred

    def _handle_f5_generation(self):
        if not self._ensure_output_dir_selected():
            return

        tipos = self._select_f5_types()
        if tipos is None:
            self._log_warn("Generacion cancelada.")
            return
        if not tipos:
            self._log_warn(
                "No se detecto un tipo de diagrama. Presiona F5 y selecciona BPMN, casos de uso, secuencia o ER."
            )
            return

        self._log_system(f"F5: generando {', '.join(tipos)} en {self.session.output_dir}")
        self._start_thread(lambda: self._run_custom_package(tipos))

    def _mask_api_key(self, api_key: str) -> str:
        if not api_key:
            return "(no configurada)"
        if len(api_key) <= 8:
            return "*" * len(api_key)
        return f"{api_key[:4]}...{api_key[-4:]}"

    def _configure_api(self, api_key: str | None = None, base_url: str | None = None):
        for ag in (self.analyst, self.architect, self.validator):
            ag.client.configure(api_key=api_key, base_url=base_url)
        self._refresh_models(silent=True)

    def _copy_to_clipboard(self, text: str) -> tuple[bool, str | None]:
        if not text.strip():
            return False, "No hay contenido para copiar."
        candidates = [
            (["wl-copy"], "wl-copy"),
            (["xclip", "-selection", "clipboard"], "xclip"),
            (["xsel", "--clipboard", "--input"], "xsel"),
            (["pbcopy"], "pbcopy"),
            (["clip.exe"], "clip.exe"),
            ([
                "powershell.exe", "-NoProfile", "-Command",
                "Set-Clipboard -Value ([Console]::In.ReadToEnd())",
            ], "powershell.exe"),
            ([
                "powershell", "-NoProfile", "-Command",
                "Set-Clipboard -Value ([Console]::In.ReadToEnd())",
            ], "powershell"),
        ]

        errors = []
        for cmd, label in candidates:
            if not shutil.which(cmd[0]):
                continue
            try:
                subprocess.run(
                    cmd,
                    input=text,
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    check=True,
                )
                return True, None
            except Exception as e:
                errors.append(f"{label}: {e}")

        hint = "Instala wl-clipboard (Wayland) o xclip/xsel (X11)."
        if errors:
            return False, "; ".join(errors) + f". {hint}"
        return False, f"No se encontro herramienta de portapapeles. {hint}"

    def _cmd_copy(self, args):
        mode = args[0].lower() if args else "trabajo"

        if mode in {"codigo", "code", "ultimo"}:
            label = "codigo generado"
            payload = self.session.last_diagram_code
        elif mode in {"trabajo", "log", "salida"}:
            label = "area de trabajo"
            payload = self.output_buffer.text
        elif mode in {"errores", "error", "warn", "warnings"}:
            label = "errores y advertencias"
            payload = "\n".join(
                line for line in self.log_lines
                if "[ERR]" in line or "[WARN]" in line
            )
        elif mode in {"respuesta", "raw"}:
            label = "ultima respuesta del arquitecto"
            payload = self.session.last_response_text
        elif mode in {"contexto", "ctx"}:
            label = "contexto cargado"
            payload = self.session.code_context
        else:
            self._log_err("Uso: /copy [salida|codigo|errores|respuesta|contexto]")
            return

        ok, err = self._copy_to_clipboard(payload)
        if ok:
            self._log_ok(f"Copiado al portapapeles: {label}")
        else:
            self._log_warn(f"No se pudo copiar {label}: {err}")

    def _cmd_save(self):
        if not self.session.last_diagram_code:
            self._log_warn("No hay diagrama generado aún.")
            return
        result = save_diagram(
            self.session.last_diagram_code,
            self.session.last_diagram_type,
            self.session.last_diagram_kind,
            output_dir=self.session.output_dir,
        )
        self._log_ok(f"Texto : {result['text']}")
        if result["png"]:
            self._log_ok(f"PNG   : {result['png']}")
        else:
            self._log_warn(f"PNG no disponible: {result['error']}")

    def _cmd_show_context(self):
        self._cmd_contextos([])

    def _cmd_contextos(self, args):
        if args:
            action = args[0].lower()
            if action in {"borrar", "del", "delete", "rm", "eliminar"}:
                if len(args) < 2 or not args[1].isdigit():
                    self._log_err("Uso: /contextos borrar <id>")
                    return
                context_id = int(args[1])
                if self.session.remove_context(context_id):
                    self._log_ok(f"Contexto #{context_id} eliminado.")
                else:
                    self._log_warn(f"No existe contexto #{context_id}.")
                return
            if action in {"limpiar", "clear", "vaciar"}:
                self.session.clear_contexts()
                self._log_ok("Todos los contextos fueron eliminados.")
                return
            if action in {"usar", "use", "solo", "only"}:
                if len(args) < 2 or not args[1].isdigit():
                    self._log_err("Uso: /contextos usar <id>")
                    return
                context_id = int(args[1])
                selected = [
                    entry for entry in self.session.context_entries
                    if int(entry.get("id", -1)) == context_id
                ]
                if not selected:
                    self._log_warn(f"No existe contexto #{context_id}.")
                    return
                self.session.context_entries = selected
                self.session._rebuild_context()
                self._log_ok(f"Contexto #{context_id} seleccionado como unico contexto activo.")
                return
            self._log_err("Uso: /contextos | /contextos borrar <id> | /contextos usar <id> | /contextos limpiar")
            return

        if not self.session.context_entries:
            self._log_warn("Sin contextos cargados. Usa F2 o /read para agregar uno.")
            return

        lines = []
        for entry in self.session.context_entries:
            content = entry.get("content", "")
            preview = " ".join(content.strip().split())[:120]
            if len(content.strip()) > 120:
                preview += "..."
            lines.append(
                f"#{entry['id']} | {entry['source']} | {content.count(chr(10)) + 1} lineas | {preview}"
            )
        lines.append("")
        lines.append("Comandos: /contextos borrar <id> | /contextos usar <id> | /contextos limpiar | F2 para agregar otro")
        self._log_block("Contextos cargados", "\n".join(lines), "[INFO] ")

    def _cmd_carpeta(self, args):
        if not args:
            try:
                get_app().exit(result="__folder__")
            except Exception:
                self._log_system(f"Carpeta actual: {self.session.output_dir}")
            return

        folder = " ".join(args)
        self._set_output_dir(folder, confirmed=True)

    def _cmd_api(self, args):
        client = self.analyst.client
        if not args or args[0].lower() in {"status", "ver", "show"}:
            self._log_block(
                "API OpenCode Zen",
                "\n".join([
                    f"Base URL: {client.base_url}",
                    f"API key : {self._mask_api_key(client.api_key)}",
                    "Comandos: /api set <api_key> | /api base <url> | /api clear",
                ]),
                "[INFO] ",
            )
            return

        action = args[0].lower()
        if action in {"set", "key", "token"}:
            if len(args) < 2:
                self._log_err("Uso: /api set <api_key>")
                return
            api_key = " ".join(args[1:]).strip()
            self._configure_api(api_key=api_key)
            self._log_ok("API key actualizada para esta sesion.")
            return

        if action in {"base", "url"}:
            if len(args) < 2:
                self._log_err("Uso: /api base <url>")
                return
            base_url = " ".join(args[1:]).strip()
            self._configure_api(base_url=base_url)
            self._log_ok(f"Base URL actualizada: {base_url}")
            return

        if action in {"clear", "limpiar", "borrar"}:
            self._configure_api(api_key="")
            self._log_ok("API key eliminada para esta sesion.")
            return

        self._configure_api(api_key=" ".join(args).strip())
        self._log_ok("API key actualizada para esta sesion.")

    def _package_logger(self, level: str, message: str):
        if level == "agent":
            if ": " in message:
                agent, detail = message.split(": ", 1)
                self._log_agent(agent, detail)
            else:
                self._log_system(message)
        elif level == "section":
            self._log_block(message, "")
        elif level == "ok":
            self._log_ok(message)
        elif level == "warn":
            self._log_warn(message)
        elif level == "error":
            self._log_err(message)
        else:
            self._log_system(message)

    def _package_code_logger(self, title: str, code: str, dtype: str):
        self._log_code(f"{title} [{dtype}]", code)

    def _cmd_multidiagrama_command(self, args):
        if not args:
            try:
                get_app().exit(result="__f5__")
            except Exception:
                self._log_warn("Usa F5 para seleccionar diagramas o /multidiagrama all para paquete completo.")
            return
        self._start_thread(lambda: self._cmd_multidiagrama(args))

    def _cmd_multidiagrama(self, args=None):
        args = args or []
        validos = dict(PACKAGE_TYPES)
        force_all = args and args[0].lower() in {"all", "todo", "todos", "full"}
        if self.session.forced_type in validos and not force_all:
            self._log_system(
                f"Tipo forzado activo ({self.session.forced_type}); F5 generara solo ese diagrama. "
                "Usa /multidiagrama all para el paquete completo."
            )
            self._run_custom_package([self.session.forced_type])
            return

        if not force_all:
            inferred = infer_package_types_from_text(self._generation_text())
            if inferred:
                self._log_system(
                    f"Restriccion detectada en el contexto: se generara solo {', '.join(inferred)}. "
                    "Usa /multidiagrama all para forzar el paquete completo."
                )
                self._run_custom_package(inferred)
                return

        self.processing = True
        self._set_status("warn", "Generando paquete multi-diagrama…")
        try:
            self._log_system("Iniciando paquete de 4 diagramas…")
            results = generate_package(
                self.session,
                self.architect,
                self.validator,
                logger=self._package_logger,
                code_logger=self._package_code_logger,
            )
            if results:
                self._log_ok("Paquete completo generado y guardado.")
                self._set_status("ok", "Paquete listo ✓")
            else:
                self._set_status("warn", "No se genero el paquete")
        except Exception as e:
            self._log_err(f"Error multi-diagrama: {e}")
            self._set_status("warn", "Error en paquete")
        finally:
            self.processing = False

    def _run_custom_package(self, tipos):
        self.processing = True
        self._set_status("warn", "Generando paquete personalizado…")
        try:
            results = generate_custom_package(
                self.session,
                self.architect,
                self.validator,
                tipos,
                logger=self._package_logger,
                code_logger=self._package_code_logger,
            )
            if results:
                self._log_ok("Paquete personalizado generado y guardado.")
                self._set_status("ok", "Paquete personalizado listo ✓")
            else:
                self._set_status("warn", "No se genero el paquete personalizado")
        except Exception as e:
            self._log_err(f"Error en paquete personalizado: {e}")
            self._set_status("warn", "Error en paquete personalizado")
        finally:
            self.processing = False

    def _cmd_read(self, args):
        if not args:
            self._log_err("Uso: /read <archivo>  o  /read -f <carpeta>")
            return
        if args[0] == "-f":
            if len(args) < 2:
                self._log_err("Especifica la carpeta: /read -f <carpeta>")
                return
            folder = " ".join(args[1:])
            self._log_system(f"Cargando carpeta: {folder} …")
            content = read_folder(folder)
            self.session.add_code_context(content, f"carpeta:{folder}")
            self._log_ok(f"Carpeta cargada — {content.count(chr(10))} líneas")
        else:
            fp = " ".join(args)
            content = read_file(fp)
            self.session.add_code_context(content, f"archivo:{fp}")
            self._log_ok(f"Archivo cargado: {fp}")

    def _cmd_tree(self, args):
        if not args:
            self._log_err("Uso: /tree <carpeta>")
            return
        tree = get_tree(" ".join(args))
        self._log_block("Arbol de directorios", tree, "[INFO] ")

    def _cmd_tipo(self, args):
        if not args:
            self._log_system("Tipos: " + ", ".join(SUPPORTED_DIAGRAM_TYPES))
            return
        if args[0].lower() in {"auto", "automatico", "automatic", "none", "limpiar"}:
            self.session.forced_type = None
            self._log_ok("Tipo forzado desactivado: deteccion automatica.")
            return

        tipo = resolve_diagram_type(" ".join(args)) or args[0].lower()
        if tipo not in SUPPORTED_DIAGRAM_TYPES:
            self._log_err("Tipo no valido. Usa /help para ver opciones.")
            return
        self.session.forced_type = tipo
        self._log_ok(f"Tipo forzado: {self.session.forced_type}")

    def _cmd_formato(self, args):
        if args and args[0] in ("mermaid", "plantuml"):
            self.session.export_format = args[0]
            self._log_ok(f"Formato: {args[0]}")
        else:
            self._log_err("Uso: /formato mermaid  o  /formato plantuml")

    def _sync_completer(self):
        self.cmd_completer = build_completer(self.available_models.keys())
        if hasattr(self, "input_area"):
            self.input_area.completer = self.cmd_completer
            self.input_area.buffer.completer = self.cmd_completer
        if hasattr(self, "input_buffer"):
            self.input_buffer.completer = self.cmd_completer

    def _sync_agents_model(self, key: str):
        for ag in (self.analyst, self.architect, self.validator):
            ag.client.models = dict(self.available_models)
            ag.client.switch_model(key, self.available_models)
        self.current_model_key = key if key in self.available_models else "default"
        self.current_model = self.available_models.get(
            self.current_model_key,
            self.available_models.get("default", AVAILABLE_MODELS["default"]),
        )

    def _refresh_models(self, silent: bool = False) -> dict[str, str]:
        models = self.analyst.client.refresh_free_models()
        self.available_models = dict(models or AVAILABLE_MODELS)
        if "default" not in self.available_models:
            self.available_models["default"] = next(iter(self.available_models.values()))

        key = self.current_model_key if self.current_model_key in self.available_models else "default"
        self._sync_agents_model(key)
        self._sync_completer()

        if not silent:
            count = len([k for k in self.available_models if k != "default"])
            self._log_ok(f"Modelos gratuitos actualizados: {count} disponibles.")
        return self.available_models

    def _model_options(self) -> list[tuple[str, str]]:
        keys = [k for k in self.available_models if k != "default"]
        return [
            (key, f"{idx}. {key}  ->  {self.available_models[key]}")
            for idx, key in enumerate(keys, 1)
        ]

    def _cmd_modelos(self):
        self._refresh_models(silent=False)
        options = self._model_options()
        if not options:
            self._log_warn("No se detectaron modelos gratuitos; usando fallback local.")
            return
        body = "\n".join(label for _, label in options)
        self._log_block(
            "Modelos gratuitos disponibles",
            body + "\n\nUsa F3, /modelo o /modelo <numero|alias>.",
            "[INFO] ",
        )

    def _cmd_modelo(self, args):
        if not args:
            try:
                get_app().exit(result="__model__")
            except Exception:
                self._cmd_modelos()
            return

        if args[0].lower() in {"refresh", "actualizar", "update"}:
            self._cmd_modelos()
            return

        key = args[0].lower()
        keys = [k for k in self.available_models if k != "default"]
        if key.isdigit():
            idx = int(key) - 1
            if 0 <= idx < len(keys):
                key = keys[idx]

        if key in self.available_models:
            self._sync_agents_model(key)
            self._log_ok(f"Modelo activo: {self.current_model_key} -> {self.current_model}")
            self._set_status("ok", f"Modelo: {self.current_model_key}")
        else:
            opts = ", ".join(keys) or "sin modelos"
            self._log_err(f"Modelo no valido. Opciones: {opts}. Usa /modelos o F3.")

    def _select_model_dialog(self):
        self._refresh_models(silent=True)
        values = self._model_options()
        if not values:
            self._log_warn("No hay modelos gratuitos detectados.")
            return

        selected = radiolist_dialog(
            title="Seleccionar modelo gratuito",
            text="Elige el modelo OpenCode Zen disponible para esta sesion:",
            values=values,
        ).run()
        if selected:
            self._sync_agents_model(selected)
            self._log_ok(f"Modelo activo: {self.current_model_key} -> {self.current_model}")

    def _set_status(self, style: str, msg: str):
        self.status_msg = (style, msg)
        try:
            get_app().invalidate()
        except Exception:
            pass

    def _resolve_format(self, diagram_type: str, requested_format: str, notify: bool = False) -> str:
        recommended = RECOMMENDED_FORMAT_BY_TYPE.get(diagram_type)
        if recommended and requested_format != recommended:
            if notify:
                self._log_warn(
                    f"{diagram_type} se generara en {recommended} para evitar incompatibilidades de renderizado."
                )
            return recommended
        return requested_format

    def _start_thread(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    # ══════════════════════════════════════════════════════════════
    #  Pipeline agéntico
    # ══════════════════════════════════════════════════════════════

    def _run_pipeline(self, user_input: str):
        self.processing = True
        self._set_status("warn", "Procesando…")
        try:
            # Agente 1 — Analista
            self._log_agent("ANALISTA", "Analizando solicitud…")
            analysis = self.analyst.analyze(user_input, self.session)

            if (not analysis.get("tiene_suficiente_info")
                    and analysis.get("pregunta_faltante")):
                q = analysis["pregunta_faltante"]
                self._log_agent("ANALISTA", f"❓ {q}")
                self.session.messages += [
                    {"role": "user",      "content": user_input},
                    {"role": "assistant", "content": q},
                ]
                self._set_status("warn", "Esperando info del usuario…")
                return

            tipo   = self.session.forced_type or analysis.get("tipo_diagrama", "?")
            fmt    = self._resolve_format(
                tipo,
                analysis.get("formato_sugerido", self.session.export_format),
                notify=True,
            )
            analysis["formato_sugerido"] = fmt
            conf   = analysis.get("confianza", "?")
            self._log_agent("ANALISTA",
                f"Tipo: {tipo}  |  Formato: {fmt}  |  Confianza: {conf}")
            self.session.last_diagram_kind = tipo

            orchestration = generate_validated_diagram(
                user_input,
                self.session,
                analysis,
                self.architect,
                self.validator,
                logger=self._package_logger,
                error_handler=lambda msg: self._log_err(f"Error Arquitecto: {msg}"),
            )

            if not orchestration.code:
                self._log_err("No se pudo producir un diagrama validado.")
                for err in orchestration.errors:
                    self._log_err(err)
                if orchestration.response:
                    self._log_block("Respuesta del arquitecto", orchestration.response[:1200], "[ARQUITECTO] ")
                return

            validated = orchestration.code
            dtype = orchestration.dtype
            self._log_agent(
                "SUPERVISOR",
                f"Orquestacion: {orchestration.backend} | iteraciones: {orchestration.iterations}",
            )

            # Guardar en sesión
            self.session.last_diagram_code = validated
            self.session.last_diagram_type = dtype
            self.session.last_diagram_kind = tipo

            # Mostrar código en el área de trabajo
            self._log_code(f"Codigo validado [{dtype}]", validated)

            # Guardar automáticamente
            saved = save_diagram(validated, dtype, tipo, output_dir=self.session.output_dir)
            self._log_ok(f"Texto : {saved['text']}")
            if saved["png"]:
                self._log_ok(f"PNG   : {saved['png']}")
            else:
                self._log_warn(f"PNG   : {saved['error']}")

            self._set_status("ok", f"✓ {tipo} ({dtype}) guardado en {orchestration.iterations} iteracion(es)")

        except Exception as e:
            import traceback
            self._log_err(f"Error en pipeline: {e}")
            self._log(traceback.format_exc())
            self._set_status("warn", "Error")
        finally:
            self.processing = False

    # ══════════════════════════════════════════════════════════════
    #  Run principal — maneja salida temporal para /ctx
    # ══════════════════════════════════════════════════════════════

    def run(self):
        while True:
            result = self.app.run()

            if result == "__ctx__":
                # Salir del full-screen temporalmente para el editor multilínea
                os.system("cls" if os.name == "nt" else "clear")
                ok = ingest_text_context(self.session, label="texto-manual")
                if ok:
                    n = self.session.code_context.count("\n")
                    self._log_ok(
                        f"Contexto textual cargado ({n} líneas). "
                        "Escribe tu solicitud o usa F5 para el tipo forzado/paquete."
                    )
                # Reconstruir app y volver al full-screen
                self._build_layout()
                self._build_keybindings()
                self._build_app()
            elif result == "__model__":
                self._select_model_dialog()
                self._build_layout()
                self._build_keybindings()
                self._build_app()
            elif result == "__folder__":
                self._prompt_output_dir()
                self._build_layout()
                self._build_keybindings()
                self._build_app()
            elif result == "__f5__":
                self._handle_f5_generation()
                self._build_layout()
                self._build_keybindings()
                self._build_app()
            else:
                break
    
    
