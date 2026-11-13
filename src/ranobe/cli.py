"""Command line interface for checking the core without a UI.

    python -m ranobe.cli accounts add --provider gemini --label main
    python -m ranobe.cli import book.epub --from ja --to uk
    python -m ranobe.cli translate <work-id-prefix>
    python -m ranobe.cli status <work-id-prefix>
    python -m ranobe.cli disputes list <work-id-prefix>
    python -m ranobe.cli glossary list <work-id-prefix> --pending
    python -m ranobe.cli export <work-id-prefix> book.epub

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
    SegmentStatus,
    Work,
)
from ranobe.core.redact import install_log_redaction
from ranobe.services.editor import Editor
from ranobe.services.exporters import (
    ExportOptions,
    UnknownFormat,
    collect_book,
    exporter_for_path,
    exporter_ids,
    get_exporter,
)
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
    repos, _ = _open()
    work = _work(repos, args.work)
    out = Path(args.out)
    try:
        exporter = get_exporter(args.format) if args.format else exporter_for_path(out)
    except UnknownFormat:
        raise CliError(f"unknown format; choose from {', '.join(exporter_ids())}") from None
    opts = ExportOptions(
        side_by_side=args.side_by_side,
        with_notes=args.notes,
        cover=Path(args.cover) if args.cover else None,
    )
    try:
        exporter.export(collect_book(repos, work), opts, out)
    except (OSError, ValueError) as e:
        raise CliError(f"export failed: {e}") from None
    print(f"wrote {out} ({exporter.id})")


def cmd_disputes_list(args: argparse.Namespace) -> None:
    repos, _ = _open()
    work = _work(repos, args.work)
    disputes = repos.disputes.for_work(work.id, unresolved_only=not args.all)
    for d in disputes:
        state = "resolved" if d.resolved_at else "open"
        print(f"{str(d.id)[:8]} [{state}] {d.source_fragment}: {d.issue}")
        for i, option in enumerate(d.options, start=1):
            mark = "*" if option.text == d.current_text else " "
            print(f"   {mark}{i}. {option.text} — {option.rationale}")
        if d.custom_text is not None:
            print(f"   *   {d.custom_text} (custom)")
    print(f"{len(disputes)} dispute(s)")


def cmd_disputes_resolve(args: argparse.Namespace) -> None:
    repos, _ = _open()
    dispute = repos.disputes.find(args.id)
    if dispute is None:
        raise CliError(f"no single dispute matches '{args.id}'")
    chosen = args.option - 1 if args.option is not None else None
    try:
        result = Editor(repos).resolve_dispute(dispute.id, chosen=chosen, custom=args.custom)
    except ValueError as e:
        raise CliError(str(e)) from None
    print(f"«{dispute.source_fragment}» → «{result.dispute.current_text}»")
    if not result.applied:
        print("  the old text was not found in the translation (edited by hand); check it")
    if result.glossary_entry:
        print("  added to the glossary as a fixed entry")


def cmd_glossary_list(args: argparse.Namespace) -> None:
    repos, _ = _open()
    work = _work(repos, args.work)
    entries = repos.glossary.pending(work.id) if args.pending else repos.glossary.for_work(work.id)
    for e in entries:
        flags = " [fixed]" if e.locked else (" [suggested]" if e.review == "pending" else "")
        scope = "" if e.work_id else " (global)"
        print(f"{str(e.id)[:8]} {e.source} = {e.target}{flags}{scope}")
    print(f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'}")


def _suggestion_action(args: argparse.Namespace, accept: bool) -> None:
    repos, _ = _open()
    entry = repos.glossary.find(args.id)
    if entry is None:
        raise CliError(f"no single glossary entry matches '{args.id}'")
    editor = Editor(repos)
    try:
        if accept:
            entry = editor.accept_suggestion(entry.id, target=args.target)
            print(f"accepted {entry.source} = {entry.target}")
        else:
            editor.reject_suggestion(entry.id)
            print(f"rejected {entry.source} = {entry.target}")
    except KeyError:
        raise CliError("this entry is not a pending suggestion") from None


def cmd_glossary_accept(args: argparse.Namespace) -> None:
    _suggestion_action(args, accept=True)


def cmd_glossary_reject(args: argparse.Namespace) -> None:
    _suggestion_action(args, accept=False)


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

    ex = sub.add_parser("export", help="export the translation (TXT, EPUB, CBZ)")
    ex.add_argument("work")
    ex.add_argument("out")
    ex.add_argument("--format", choices=exporter_ids(), help="default: from the file extension")
    ex.add_argument("--side-by-side", action="store_true", help="original above translation")
    ex.add_argument("--notes", action=argparse.BooleanOptionalAction, default=True)
    ex.add_argument("--cover", help="JPEG or PNG cover image")
    ex.set_defaults(func=cmd_export)

    dis = sub.add_parser("disputes", help="review disputed translations").add_subparsers(
        dest="disputes_command", required=True
    )
    dl = dis.add_parser("list", help="open disputes of a work (* = in the text now)")
    dl.add_argument("work")
    dl.add_argument("--all", action="store_true", help="include resolved disputes")
    dl.set_defaults(func=cmd_disputes_list)
    dr = dis.add_parser("resolve", help="choose an option or your own text")
    dr.add_argument("id", help="dispute id prefix")
    choice = dr.add_mutually_exclusive_group(required=True)
    choice.add_argument("--option", type=int, help="option number as listed (1, 2, ...)")
    choice.add_argument("--custom", help="your own text")
    dr.set_defaults(func=cmd_disputes_resolve)

    glo = sub.add_parser("glossary", help="glossary and model suggestions").add_subparsers(
        dest="glossary_command", required=True
    )
    gl = glo.add_parser("list", help="glossary of a work")
    gl.add_argument("work")
    gl.add_argument("--pending", action="store_true", help="only suggestions to review")
    gl.set_defaults(func=cmd_glossary_list)
    ga = glo.add_parser("accept", help="confirm a suggestion (it becomes fixed)")
    ga.add_argument("id", help="entry id prefix")
    ga.add_argument("--target", help="use another rendering")
    ga.set_defaults(func=cmd_glossary_accept)
    gr = glo.add_parser("reject", help="hide a suggestion from prompts")
    gr.add_argument("id", help="entry id prefix")
    gr.set_defaults(func=cmd_glossary_reject)
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
