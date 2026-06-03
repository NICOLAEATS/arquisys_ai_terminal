#!/usr/bin/env python3
"""
ArquiSysAI — IA Agéntica para generación de diagramas técnicos
Punto de entrada. Lanza la TUI interactiva.
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import OPENCODE_API_KEY
from ui.tui import ArquiSysAI_TUI


def _ensure_api_key():
    env_path = Path.home() / ".arquisys-ai.env"
    current = OPENCODE_API_KEY.strip()

    if current and current != "sk-placeholder-requires-setup":
        return

    print("\n" + "=" * 55)
    print("  Bienvenido a ArquiSysAI")
    print("=" * 55)
    print("\nNecesitas una API key de OpenCode Zen para usar el sistema.")
    print("Obtén una gratis en: https://opencode.ai\n")

    key = input("Pega tu API key aquí: ").strip()
    while not key:
        key = input("La API key no puede estar vacía. Intenta de nuevo: ").strip()

    os.makedirs(env_path.parent, exist_ok=True)
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(f"# ArquiSysAI Configuration\nOPENCODE_API_KEY={key}\n")

    os.environ["OPENCODE_API_KEY"] = key
    print("\nAPI key guardada en ~/.arquisys-ai.env\n")


def main():
    _ensure_api_key()
    tui = ArquiSysAI_TUI()
    tui.run()


if __name__ == "__main__":
    main()