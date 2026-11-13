"""Entry point for `flet build` (it packages the `src` folder and runs this module)."""

import flet as ft

from ranobe.ui.app import ASSETS_DIR, main

ft.run(main, assets_dir=str(ASSETS_DIR))
