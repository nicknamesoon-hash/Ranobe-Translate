"""Command line interface for checking the core without a UI.

    python -m ranobe.cli accounts add --provider gemini --label main
    python -m ranobe.cli import book.epub --from ja --to uk
    python -m ranobe.cli translate <work-id-prefix>
    python -m ranobe.cli status <work-id-prefix>
    python -m ranobe.cli export <work-id-prefix> out.txt

Ctrl+C pauses safely; `translate` again resumes from the first untranslated segment.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
from pathlib import Path

from ranobe import __version__
from ranobe.core.models import (
    QUALITY_PRESETS,
    CensorshipLevel,
    HonorificsMode,
    JobState,
    ProviderAccount,
    SegmentKind,
    SegmentStatus,
    Work,
)
from ranobe.core.redact import install_log_redaction
from ranobe.services.importers import ImportFailed, UnsupportedFormat
from ranobe.services.key_pool import KeyPool
from ranobe.services.library import import_file
from ranobe.services.providers import ProviderRegistry, provider_infos
from ranobe.services.secrets import FernetStore, SecretStore, WrongPassword, select_store
from ranobe.services.translator import (
    AccountSwitched,
    ChunkDone,
    Event,
    Translator,
    WaitingQuota,
)
from ranobe.storage import paths
from ranobe.storage.db import Database
from ranobe.storage.repositories import Repositories
from ranobe.storage.settings import AppSettings


class CliError(Exception):
    pass


def _open() -> tuple[Repositories, AppSettings]:
    settings = AppSettings.load(paths.settings_path())
    return Repositories(Database(paths.db_path())), settings


def _secrets(settings: AppSettings) -> SecretStore:
    store = select_store(paths.data_dir(), settings.secret_backend)
    if isinstance(store, FernetStore) and not store.unlocked:
        first = not store.initialized
        print("System keychain is not available; API keys are encrypted with a master password.")
        password = getpass.getpass("Create master password: " if first else "Master password: ")
        if first and getpass.getpass("Repeat master password: ") != password:
            raise CliError("passwords do not match")
        remember = input("Remember on this device? [y/N] ").strip().lower() == "y"
        try:
            store.unlock(password, remember=remember)
        except WrongPassword:
            raise CliError("wrong master password") from None
    return store


def _work(repos: Repositories, prefix: str) -> Work:
    work = repos.works.find(prefix)
    if work is None:
        raise CliError(f"no single work matches '{prefix}' (see `works`)")
    return work


# --- commands ---


def cmd_providers(args: argparse.Namespace) -> None:
    for p in provider_infos():
        tier = "free tier" if p.free_tier else "paid"
        print(f"{p.id:<11} {p.name:<15} {tier:<9} default model: {p.default_model}")
        print(f"{'':<11} get a key: {p.key_url}")


def cmd_accounts_add(args: argparse.Namespace) -> None:
    infos = {p.id: p for p in provider_infos()}
    if args.provider not in infos:
        raise CliError(f"unknown provider; choose from {', '.join(infos)}")
    repos, settings = _open()
    store = _secrets(settings)
    key = sys.stdin.readline().strip() if args.key_stdin else getpass.getpass("API key: ").strip()
    if not key:
        raise CliError("empty key")
    acc = ProviderAccount(
        provider_id=args.provider,
        label=args.label,
        model=args.model or infos[args.provider].default_model,
        rpm=args.rpm,
        priority=args.priority,
    )
    store.set(acc.secret_ref, key)
    repos.accounts.save(acc)
    print(f"added {acc.id[:8]} {acc.provider_id}/{acc.model} ({acc.label}), stored in {store.name}")


def cmd_accounts_list(args: argparse.Namespace) -> None:
    repos, _ = _open()
    for a in repos.accounts.list():
        state = "on " if a.enabled else "off"
        extra = []
        if a.cooldown_until:
            extra.append(f"cooldown until {a.cooldown_until:%H:%M:%S}")
        if a.exhausted_until:
            extra.append(f"quota until {a.exhausted_until:%Y-%m-%d %H:%M} UTC")
        if a.last_error:
            extra.append(f"last error: {a.last_error[:80]}")
        print(f"{a.id[:8]} [{state}] p{a.priority:<3} {a.provider_id}/{a.model} ({a.label}) "
              f"{a.rpm:g} rpm  {'; '.join(extra)}")  # fmt: skip


def cmd_accounts_remove(args: argparse.Namespace) -> None:
    repos, settings = _open()
    matches = [a for a in repos.accounts.list() if a.id.startswith(args.id)]
    if len(matches) != 1:
        raise CliError("account id prefix must match exactly one account")
    _secrets(settings).delete(matches[0].secret_ref)
    repos.accounts.delete(matches[0].id)
    print(f"removed {matches[0].label}")


def cmd_accounts_enable(args: argparse.Namespace) -> None:
    repos, _ = _open()
    for a in repos.accounts.list():
        if a.id.startswith(args.id):
            a.enabled, a.cooldown_until, a.exhausted_until = True, None, None
            repos.accounts.save(a)
            print(f"enabled {a.label}")


async def _test_accounts() -> None:
    repos, settings = _open()
    store = _secrets(settings)
    registry = ProviderRegistry()
    try:
        for a in repos.accounts.list():
            key = store.get(a.secret_ref)
            if not key:
                print(f"{a.label}: no key stored")
                continue
            try:
                models = await registry.get(a.provider_id).list_models(key)
                ok = "model available" if a.model in models else "MODEL NOT IN LIST"
                print(f"{a.label}: OK, {len(models)} models, {a.model}: {ok}")
            except Exception as e:  # report and continue with the next account
                print(f"{a.label}: {type(e).__name__}: {e}")
    finally:
        await registry.aclose()


def cmd_accounts_test(args: argparse.Namespace) -> None:
    asyncio.run(_test_accounts())


def cmd_import(args: argparse.Namespace) -> None:
    repos, _ = _open()
    try:
        work = import_file(repos, Path(args.file), args.source, args.target)
    except (ImportFailed, UnsupportedFormat, OSError) as e:
        raise CliError(f"import failed: {e}") from None
    chapters = repos.chapters.for_work(work.id)
    n = sum(len(repos.segments.for_chapter(c.id)) for c in chapters)
    print(f"imported {str(work.id)[:8]} «{work.title}»: {len(chapters)} chapters, {n} segments")


def cmd_works(args: argparse.Namespace) -> None:
    repos, _ = _open()
    for w in repos.works.list():
        ids = [c.id for c in repos.chapters.for_work(w.id)]
        counts = repos.segments.count_by_status(ids)
        total = sum(counts.values())
        done = total - counts[SegmentStatus.PENDING]
        print(f"{str(w.id)[:8]} {w.source_lang}→{w.target_lang} {done}/{total} "
              f"[{w.translation_status.value}] {w.title}")  # fmt: skip


def cmd_status(args: argparse.Namespace) -> None:
    repos, _ = _open()
    work = _work(repos, args.work)
    ids = [c.id for c in repos.chapters.for_work(work.id)]
    counts = repos.segments.count_by_status(ids)
    ws = work.settings
    print(f"«{work.title}» {work.source_lang}→{work.target_lang}, preset {ws.quality_preset}, "
          f"content level {ws.censorship.value}")  # fmt: skip
    for status, n in counts.items():
        print(f"  {status.value:<13} {n}")
    print(f"  unresolved disputes: {repos.disputes.unresolved_count(work.id)}")
    job = repos.jobs.latest_for_work(work.id)
    if job:
        s = job.stats
        print(f"  job: {job.state.value}, {s.requests} requests, "
              f"{s.input_tokens}+{s.output_tokens} tokens, {s.seconds / 60:.1f} min")  # fmt: skip
        if job.resume_after:
            print(f"  resume after {job.resume_after:%Y-%m-%d %H:%M} UTC")
        if job.last_error:
            print(f"  last error: {job.last_error}")


def _print_event(event: Event) -> None:
    if isinstance(event, ChunkDone):
        flag = f", {event.needs_review} to review" if event.needs_review else ""
        print(f"[{event.translated}/{event.total}{flag}] {event.account}: {event.preview[:70]}")
    elif isinstance(event, AccountSwitched):
        print(f"  ↷ {event.account}: {event.reason}, switching account")
    elif isinstance(event, WaitingQuota):
        when = f"{event.resume_at:%Y-%m-%d %H:%M} UTC" if event.resume_at else "unknown"
        print(f"All accounts are out of quota or disabled. Resume after: {when}")


async def _translate(args: argparse.Namespace) -> None:
    repos, settings = _open()
    work = _work(repos, args.work)
    if args.preset:
        work.settings.quality_preset = args.preset
    if args.censorship:
        work.settings.censorship = CensorshipLevel(args.censorship)
    if args.honorifics:
        work.settings.honorifics = HonorificsMode(args.honorifics)
    for flag in ("notes", "disputes", "summary"):
        value = getattr(args, flag)
        if value is not None:
            setattr(work.settings, f"with_{flag}", value)
    repos.works.save(work)

    registry = ProviderRegistry()
    pool = KeyPool(repos.accounts, _secrets(settings))
    translator = Translator(repos, registry, pool, on_event=_print_event)
    job = repos.jobs.latest_for_work(work.id)
    if job is None or job.state is JobState.DONE:
        job = translator.create_job(work)
    try:
        job = await translator.run(job.id)
    finally:
        await registry.aclose()
    print(f"job {job.state.value}" + (f": {job.last_error}" if job.last_error else ""))


def cmd_translate(args: argparse.Namespace) -> None:
    try:
        asyncio.run(_translate(args))
    except KeyboardInterrupt:
        print("\npaused; run `translate` again to resume")


def cmd_export(args: argparse.Namespace) -> None:
    """Plain text export for checking results. Full exporters (EPUB, CBZ) come in phase 2."""
    repos, _ = _open()
    work = _work(repos, args.work)
    lines: list[str] = []
    for ch in repos.chapters.for_work(work.id):
        for seg in repos.segments.for_chapter(ch.id):
            text = seg.translation if seg.translation else f"[{seg.status.value}] {seg.source}"
            if args.side_by_side and seg.kind is not SegmentKind.SEPARATOR:
                text = f"{seg.source}\n{text}"
            lines.append(text)
    Path(args.out).write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")


# --- parser ---


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ranobe", description="Ranobe Translator core CLI")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("providers", help="list supported providers").set_defaults(func=cmd_providers)

    acc = sub.add_parser("accounts", help="manage API accounts").add_subparsers(
        dest="accounts_command", required=True
    )
    add = acc.add_parser("add", help="add an account (key is asked interactively)")
    add.add_argument("--provider", required=True)
    add.add_argument("--label", required=True)
    add.add_argument("--model")
    add.add_argument("--rpm", type=float, default=5.0, help="requests per minute (default 5)")
    add.add_argument("--priority", type=int, default=100, help="lower is tried first")
    add.add_argument("--key-stdin", action="store_true", help="read the key from stdin")
    add.set_defaults(func=cmd_accounts_add)
    acc.add_parser("list").set_defaults(func=cmd_accounts_list)
    rm = acc.add_parser("remove")
    rm.add_argument("id")
    rm.set_defaults(func=cmd_accounts_remove)
    en = acc.add_parser("enable", help="re-enable and clear cooldowns")
    en.add_argument("id")
    en.set_defaults(func=cmd_accounts_enable)
    acc.add_parser("test", help="check every key").set_defaults(func=cmd_accounts_test)

    imp = sub.add_parser("import", help="import a TXT/EPUB/CBZ file")
    imp.add_argument("file")
    imp.add_argument("--from", dest="source", required=True, choices=["ja", "ko", "en"])
    imp.add_argument("--to", dest="target", required=True, choices=["uk", "en"])
    imp.set_defaults(func=cmd_import)

    sub.add_parser("works", help="list works").set_defaults(func=cmd_works)

    st = sub.add_parser("status", help="show work progress")
    st.add_argument("work")
    st.set_defaults(func=cmd_status)

    tr = sub.add_parser("translate", help="translate or resume a work")
    tr.add_argument("work")
    tr.add_argument("--preset", choices=list(QUALITY_PRESETS))
    tr.add_argument("--censorship", choices=[c.value for c in CensorshipLevel])
    tr.add_argument("--honorifics", choices=[h.value for h in HonorificsMode])
    for flag in ("notes", "disputes", "summary"):
        tr.add_argument(f"--{flag}", action=argparse.BooleanOptionalAction, default=None)
    tr.set_defaults(func=cmd_translate)

    ex = sub.add_parser("export", help="export translation as plain text")
    ex.add_argument("work")
    ex.add_argument("out")
    ex.add_argument("--side-by-side", action="store_true", help="original above translation")
    ex.set_defaults(func=cmd_export)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    install_log_redaction()
    try:
        args.func(args)
    except CliError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
