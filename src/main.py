"""Entry point for `flet build`: it packages `src` (tool.flet.app.path) and runs this module."""

import flet as ft

from ranobe.ui.app import ASSETS_DIR, main

ft.run(main, assets_dir=str(ASSETS_DIR))
