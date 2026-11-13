# Ranobe Translator 2.0

Context-aware light novel translator (ja / ko / en → uk / en) powered by free-tier LLM APIs.
Rewrite of the original CustomTkinter app. See `ARCHITECTURE.md` and `ROADMAP.md`.

Status: phase 3 (desktop UI: library, translation, accounts, settings).

## Development

```
python -m venv .venv
.venv/bin/pip install -e ".[dev,ui]"   # Windows: .venv\Scripts\pip ...
pytest
ruff check . && ruff format --check .
python -m ranobe                       # the app (add --web to open it in a browser)
python -m ranobe.cli --help
```

## Trying the core

```
python -m ranobe.cli providers                       # where to get free keys
python -m ranobe.cli accounts add --provider gemini --label main --rpm 8 --priority 10
python -m ranobe.cli accounts add --provider groq --label backup --priority 20
python -m ranobe.cli accounts test
python -m ranobe.cli import book.epub --from ja --to uk
python -m ranobe.cli translate <id>                  # Ctrl+C pauses, run again to resume
python -m ranobe.cli status <id>
python -m ranobe.cli disputes list <id>                # open disputes, * = in the text
python -m ranobe.cli disputes resolve <dispute> --option 2   # or --custom "..."
python -m ranobe.cli glossary list <id> --pending      # model suggestions to review
python -m ranobe.cli glossary accept <entry> [--target "..."]
python -m ranobe.cli export <id> book.epub --cover cover.jpg  # also .txt, .cbz
```

Data lives in `%APPDATA%\RanobeTranslator` (Windows) or `~/.local/share/ranobe-translator`
(Linux); set `RANOBE_DATA_DIR` to use another folder. API keys go to the system keychain, or to
a file encrypted with a master password when no keychain is available.
