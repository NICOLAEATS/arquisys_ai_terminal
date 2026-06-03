#!/usr/bin/env python3
"""
ArquiSysAI — IA Agéntica para generación de diagramas técnicos
Punto de entrada. Lanza la TUI interactiva.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ui.tui import ArquiSysAI_TUI


def main():
    tui = ArquiSysAI_TUI()
    tui.run()


if __name__ == "__main__":
    main()