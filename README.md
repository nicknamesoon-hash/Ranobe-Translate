# Ranobe Translator 2.0

Context-aware light novel translator (ja / ko / en → uk / en) powered by free-tier LLM APIs.
Rewrite of the original CustomTkinter app. See `ARCHITECTURE.md` and `ROADMAP.md`.

Status: phase 1 (core without UI).

## Development

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip ...
pytest
ruff check . && ruff format --check .
python -m ranobe.cli --help
```
