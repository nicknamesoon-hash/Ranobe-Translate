# Ranobe Translator 2.0 — архітектура

Статус: проєкт для узгодження (2026-11-11). Аналіз старого коду: `ANALYSIS.md`.
Порядок робіт: `ROADMAP.md`.

## 0. Принципи

1. **Ядро не знає про UI.** `core/` не імпортує `ui/`, Flet чи платформні модулі. Усе, що
   можна перевірити без вікна, перевіряється тестами без вікна.
2. **Стан перекладу живе в БД проєкту, а не в сесії API.** Кожен запит до LLM будується заново
   з БД (глосарій, резюме, хвіст, налаштування твору). Тому ключ, провайдер чи навіть пристрій
   можна змінити посеред тому без втрати контексту.
3. **Розширення через реєстр.** Новий провайдер, імпортер, експортер чи мова інтерфейсу = новий
   клас/файл + одна реєстрація, без правок наявного коду.
4. **Мінімум нативних залежностей.** Кожна нативна бібліотека ускладнює Android-збірку, тому
   стандартна бібліотека Python має перевагу (EPUB через `zipfile` + `xml.etree`, SQLite через
   `sqlite3`, HTTP через `httpx`).
5. **Сегмент — одиниця всього.** Переклад, перевірка, примітки, спірні моменти, синхронізація
   та відновлення працюють на рівні сегмента (абзацу) зі стабільним ID.

## 1. Вибір UI-фреймворку

### Порівняння

| Критерій | **Flet** | **Kivy / KivyMD** | **Python-ядро + інший фронтенд** (Flutter/Dart, або Tauri/web + Python sidecar) |
|---|---|---|---|
| Android-збірка | `flet build apk/aab` (Flutter + вбудований Python). Чисто-Python пакети працюють; нативні (Pillow, cryptography, pydantic-core) потрібні в мобільному індексі Flet, це треба перевірити спайком | `buildozer`/python-for-android: зріле, але повільна й крихка збірка (тільки Linux/WSL), рецепти для нативних пакетів | Flutter: найкраща Android-збірка, але Python усередині через serious_python або окремий сервер. Tauri mobile + Python sidecar на Android практично непридатний |
| Адаптивність | Flutter-розкладка: `ResponsiveRow`, `NavigationRail`/`NavigationBar`, події `on_resized`. Добре | Ручна: `kv`-правила, власні breakpoints, KivyMD має `MDResponsiveLayout`. Середньо | Відмінно (Flutter або CSS) |
| Анімації | Вбудовані неявні анімації (`animate_opacity`, `animate_position`, `AnimatedSwitcher`, переходи сторінок). Досить для «не надмірних» | Потужні (`Animation`), але все вручну | Відмінно |
| Простота | Один Python-код, віджети як об'єкти, async-обробники. Найпростіше | Окрема мова `kv`, власна модель подій, «не-нативний» вигляд, KivyMD 2.x ламав API | Два мови, два кодові бази, IPC/API між ними. Найскладніше |
| Зрілість | Молодший, API змінювався між 0.x і 1.0. Активна розробка, велика спільнота | Найстаріший (з 2011), стабільний, але KivyMD повільно розвивається | Flutter дуже зрілий; зв'язка з Python — ні |
| Єдиний стиль desktop/Android | Так, Material 3 рендериться однаково (Flutter) | Так, але стиль «свій» | Так |

### Рекомендація: **Flet**

- Єдиний Python-код для Windows, Linux і Android, і рендер через Flutter дає однаковий
  вигляд Material 3 на всіх платформах. Це прямо твоя вимога.
- Твоє ядро на Python лишається Python. Варіант «інший фронтенд» удвічі збільшує кодову базу
  заради кращих анімацій, які тобі не потрібні в надмірній кількості.
- Kivy виграє в зрілості, але програє в простоті, вигляді й адаптивності, а збірка під Android
  через buildozer повільніша й крихкіша за `flet build`.

Як знизити ризики Flet:
- Зафіксувати версію Flet (`flet==X.Y.Z`) і оновлювати свідомо.
- Тримати весь Flet-код у `ui/`, щоб у разі заміни фреймворку переписувати лише його.
- На початку фази 1 зробити **спайк**: зібрати APK, що імпортує всі залежності ядра (httpx,
  pydantic, cryptography, Pillow, charset-normalizer) і пише в SQLite. Якщо щось не зібралося,
  замінити залежність до того, як на ній побудовано ядро.

## 2. Технології

| Шар | Вибір | Обґрунтування |
|---|---|---|
| Мова | Python 3.12+ | Підтримка в Flet build; сучасні type hints |
| UI | Flet (Material 3) | Див. вище |
| Async | `asyncio` | Flet async-first; скасування перекладу через `CancelledError` замість прапорців |
| HTTP до LLM | `httpx` (async) напряму, без OpenAI SDK | OpenAI-сумісний `/chat/completions` — це один POST. Повний контроль над тілом помилки 429 (RPM чи квота), менше залежностей на Android |
| Моделі даних | `dataclasses` скрізь; JSON від LLM валідується вручну в `core/llm_schema.py` | Рішення фази 1: ручна валідація вийшла ~150 рядків і прибрала нативну залежність `pydantic-core` (ризик для Android) |
| БД | SQLite через `sqlite3`, власні SQL-міграції (`PRAGMA user_version`) | Без ORM: простіше, без залежностей, легко читати |
| Секрети | `keyring` (Windows Credential Manager, Linux Secret Service) → Android Keystore → Fernet (`cryptography`) з ключем з майстер-пароля (scrypt) | Вимога безпеки |
| Кодування TXT | BOM → UTF-8 → `charset-normalizer` | Виправляє баг з GBK |
| EPUB | Власний читач/писач на `zipfile` + `xml.etree` + `html.parser` | Без lxml (нативний) і ebooklib; повний контроль над spine і виносками |
| Зображення | Pillow (кадрування, накладання назви) | Є мобільні колеса у Flet (перевірити в спайку) |
| i18n | Власний мінімальний модуль на JSON + правила множини uk/en | 60 рядків коду замість gettext-інфраструктури; перемикання без перезапуску |
| Тести | pytest, pytest-asyncio, `respx` (мок httpx) | Нестабільні API мокаються (вимога CLAUDE.md) |
| Якість | ruff (lint + format), mypy або pyright у CI | CLAUDE.md |
| Бекенд синхронізації | Django + Django REST Framework, PostgreSQL | Ти вже деплоїш Django |
| Пакування | `flet build windows/linux/apk` у GitHub Actions | Один інструмент на всі платформи, див. §10 |

## 3. Структура папок

```
ranobe-translator/
├── pyproject.toml
├── CLAUDE.md  ARCHITECTURE.md  ROADMAP.md  README.md
├── src/ranobe/
│   ├── __init__.py            # __version__
│   ├── __main__.py            # python -m ranobe → запуск UI
│   ├── cli.py                 # python -m ranobe.cli … — ручна перевірка ядра без UI
│   │
│   ├── core/                  # чиста логіка, без I/O платформи й UI       [фаза 1 ✓]
│   │   ├── models.py          # Work, Chapter, Segment, Note, Dispute, GlossaryEntry, …
│   │   ├── errors.py          # класифіковані помилки провайдера
│   │   ├── segmenter.py       # текст → сегменти (абзаци), CJK-aware речення
│   │   ├── chunker.py         # сегменти → чанки під бюджет токенів
│   │   ├── tokens.py          # оцінка токенів (евристика за типом письма)
│   │   ├── prompts/           # збирання промтів з блоків (за skill §9)
│   │   │   ├── builder.py     # переклад, редагування, резюме; глосарій лише для чанка
│   │   │   ├── rules_uk.py    # правила для української (зі skill)
│   │   │   └── rules_en.py    # чернетка правил для англійської (на перевірку)
│   │   ├── llm_schema.py      # розбір і валідація JSON-відповіді
│   │   ├── notes.py           # правило «примітка лише при першій появі»          [фаза 2 ✓]
│   │   ├── footnotes.py       # місце маркера примітки в тексті (для експортерів)  [фаза 2 ✓]
│   │   ├── refusal.py         # виявлення відмов/спотворень моделі
│   │   └── redact.py          # маскування ключів у логах і повідомленнях
│   │
│   ├── services/              # інтеграції з зовнішнім світом через інтерфейси
│   │   ├── translator.py      # TranslationJob runner: цикл чанків, ротація, відновлення,
│   │   │                      # повторний переклад сегмента з іншим рівнем цензури      [✓]
│   │   ├── editor.py          # спірні моменти, примітки, черга пропозицій глосарію   [фаза 2 ✓]
│   │   ├── library.py         # імпорт книги в БД                                       [✓]
│   │   ├── providers/                                                                    [✓]
│   │   │   ├── base.py        # Protocol LLMProvider + ProviderInfo
│   │   │   ├── registry.py
│   │   │   ├── openai_compat.py   # базовий клас для OpenAI-сумісних (httpx)
│   │   │   └── builtin.py         # Gemini, Groq, Mistral, OpenRouter, DeepSeek
│   │   ├── key_pool.py        # пул акаунтів, cooldown, ротація між провайдерами        [✓]
│   │   ├── secrets/                                                                      [✓]
│   │   │   ├── base.py        # Protocol SecretStore, MemorySecretStore
│   │   │   ├── keyring_store.py
│   │   │   ├── fernet_store.py
│   │   │   └── android_store.py   # після Android-спайку
│   │   ├── importers/         # text.py, epub.py, cbz.py (+ registry)                    [✓]
│   │   ├── exporters/         # txt.py, epub.py (виноски), cbz.py (+ registry)       [фаза 2 ✓]
│   │   ├── covers.py          # кадрування, накладання назви (Pillow)
│   │   ├── sync/              # client.py, outbox.py, conflicts.py
│   │   └── updater/           # github.py, verify.py, installers/{windows,linux,android}.py
│   │
│   ├── assets/fonts/          # Noto Serif Regular/Bold + OFL.txt (для CBZ)          [фаза 2 ✓]
│   ├── storage/                                                                          [✓]
│   │   ├── db.py              # підключення, транзакції, WAL, міграції
│   │   ├── migrations/        # 0001_init.sql, 0002_glossary_review.sql
│   │   ├── repositories.py    # WorkRepo, SegmentRepo, JobRepo, GlossaryRepo, …
│   │   ├── settings.py        # AppSettings (dataclass) ↔ settings.json
│   │   └── paths.py           # каталоги даних для кожної платформи
│   │
│   ├── i18n/
│   │   ├── __init__.py        # t(), set_locale(), on_locale_change()
│   │   ├── plural.py
│   │   └── locales/{uk,en}.json
│   │
│   ├── help/                  # сторінки довідки
│   │   └── {uk,en}/*.md
│   │
│   └── ui/                    # єдине місце, що імпортує flet
│       ├── app.py             # page setup, тема, маршрути
│       ├── state.py           # AppState (observable), зв'язок із сервісами
│       ├── theme/             # tokens.py (кольори, типографіка, відступи, тривалості), theme.py
│       ├── components/        # AppButton, SegmentRow, NoteBadge, DisputeCard, StatusChip, EmptyState…
│       ├── layout/            # shell.py (rail/bottom bar), breakpoints.py
│       └── views/             # library, work_detail, translate, editor, reader,
│                              # cover_editor, glossary, accounts, settings, help, about
├── tests/
│   ├── core/  services/  storage/  i18n/
│   ├── fixtures/              # маленькі TXT/EPUB у UTF-8, Shift_JIS, GBK; записані відповіді LLM
│   └── quality/               # перевірки промтів за чеклістом skill (без мережі)
├── server/                    # окремий Django-проєкт синхронізації
└── .github/workflows/         # ci.yml, release.yml
```

## 4. Модель даних

### 4.1 Доменні сутності (`core/models.py`)

```python
class SegmentStatus(StrEnum):
    PENDING = "pending"  # ще не перекладено
    TRANSLATED = "translated"  # є машинний переклад
    NEEDS_REVIEW = "needs_review"  # відмова моделі / невалідний JSON / різке скорочення
    REVIEWED = "reviewed"  # користувач перевірив
    EDITED = "edited"  # користувач змінив текст вручну


class CensorshipLevel(StrEnum):
    ORIGINAL = "original"
    SOFTENED = "softened"
    FAMILY = "family"


class TranslationStatus(StrEnum):  # статус перекладу твору (метадані)
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    DONE = "done"


@dataclass
class Work:
    id: UUID
    title: str
    original_title: str | None
    author: str | None
    source_lang: str  # BCP-47: "ja", "zh", "ko", "en"
    target_lang: str  # "uk"
    genres: list[str]
    tags: list[str]
    synopsis: str
    translation_status: TranslationStatus
    cover_id: UUID | None
    settings: WorkSettings  # див. нижче
    updated_at: datetime
    rev: int  # версія для синхронізації
    deleted: bool = False


@dataclass
class WorkSettings:
    censorship: CensorshipLevel = CensorshipLevel.ORIGINAL
    honorifics: Literal["keep", "adapt", "drop"] = "keep"
    two_pass: bool = False
    quality_preset: str = "balanced"  # id, не підпис
    provider_id: str = "gemini"
    model: str | None = None


@dataclass
class Chapter:
    id: UUID
    work_id: UUID
    index: int
    title: str
    rev: int


@dataclass
class Segment:
    id: UUID
    chapter_id: UUID
    index: int  # порядок у розділі
    kind: Literal["paragraph", "heading", "dialogue", "separator"]
    source: str
    translation: str | None
    status: SegmentStatus
    censored: bool  # текст пом'якшено відповідно до рівня
    machine_translation: str | None  # перша версія від LLM (щоб показати diff після ручних правок)
    rev: int


@dataclass
class DisputeOption:
    text: str
    rationale: str


@dataclass
class Dispute:
    id: UUID
    segment_id: UUID
    source_fragment: str
    issue: str
    options: list[DisputeOption]  # 2–4
    recommended: int
    chosen: int | None  # індекс; None = ще не вирішено
    custom_text: str | None  # свій варіант користувача
    add_to_glossary: bool
    resolved_at: datetime | None


class NoteType(StrEnum):
    UNTRANSLATABLE = "untranslatable"
    WORDPLAY = "wordplay"
    CULTURAL = "cultural"
    TERM = "term"
    REFERENCE = "reference"
    TRANSLATOR_CHOICE = "translator_choice"


@dataclass
class Note:
    id: UUID
    segment_id: UUID
    type: NoteType
    anchor: str  # слово в перекладі, до якого прив'язана примітка
    source_fragment: str
    text: str
    first_occurrence: bool
    display: Literal["footnote", "tooltip"]  # як показувати й експортувати
    origin: Literal["llm", "user"]


@dataclass
class GlossaryEntry:
    id: UUID
    work_id: UUID | None  # None = глобальний глосарій
    source: str
    target: str
    kind: Literal["name", "term", "place", "technique", "other"]
    note: str | None
    origin: Literal["user", "dispute", "llm_suggestion"]
    locked: bool  # користувач підтвердив, модель не може змінювати
```

Чому сегменти з UUID, а не індекси чанків:
- side-by-side вирівнювання тривіальне: один сегмент = один рядок оригіналу й перекладу;
- відновлення = «перший сегмент зі статусом `pending`», не залежить від розміру чанка;
- примітки, спірні моменти й закладки прив'язуються до сегмента й переживають правки
  тексту та об'єднання томів;
- синхронізація й конфлікти локалізуються до одного абзацу.

### 4.2 Стан завдання перекладу

```python
@dataclass
class TranslationJob:
    id: UUID
    work_id: UUID
    chapter_ids: list[UUID]  # що перекладаємо
    state: Literal["running", "paused", "waiting_quota", "failed", "done"]
    plot_summary: str  # оновлюється кожні N чанків
    last_source_tail: str  # хвіст оригіналу попереднього чанка
    last_translation_tail: str  # хвіст перекладу попереднього чанка
    settings_snapshot: WorkSettings  # з чим запускали
    stats: JobStats  # токени, запити, час, для ETA й вартості
    resume_after: datetime | None  # коли закінчиться cooldown усіх ключів
    updated_at: datetime
```

Курсор не зберігається окремо: наступна робота — це перші `pending`-сегменти вибраних розділів.

### 4.3 Схема SQLite (скорочено)

```
works(id PK, title, original_title, author, source_lang, target_lang, genres JSON, tags JSON,
      synopsis, translation_status, cover_id, settings JSON, updated_at, rev, deleted)
chapters(id PK, work_id FK, idx, title, updated_at, rev, deleted)
segments(id PK, chapter_id FK, idx, kind, source, translation, machine_translation,
         status, censored, updated_at, rev, deleted)          INDEX(chapter_id, idx)
notes(id PK, segment_id FK, type, anchor, source_fragment, text, first_occurrence,
      display, origin, updated_at, rev, deleted)
disputes(id PK, segment_id FK, source_fragment, issue, options JSON, recommended,
         chosen, custom_text, add_to_glossary, resolved_at, updated_at, rev, deleted)
glossary(id PK, work_id FK NULL, source, target, kind, note, origin, locked,
         review, updated_at, rev, deleted)                     UNIQUE(work_id, source)
         -- review: none | pending (пропозиція моделі, чекає на рішення) | rejected
bookmarks(id PK, work_id, segment_id, label, created_at, rev, deleted)
covers(id PK, work_id, sha256, mime, width, height, blob_path, updated_at, rev)
jobs(id PK, work_id, state, chapter_ids JSON, plot_summary, last_source_tail,
     last_translation_tail, settings_snapshot JSON, stats JSON, resume_after, updated_at)
provider_accounts(id PK, provider_id, label, secret_ref, model, rpm, priority, enabled,
                  cooldown_until, exhausted_until, last_error, created_at)  -- ніколи не синхронізується
sync_outbox(seq PK AUTOINCREMENT, entity, entity_id, op, payload JSON, created_at)
sync_state(key PK, value)            -- cursor сервера, device_id
```

Тексти перекладу зберігаються в SQLite (один том ≈ 1–3 МБ тексту, це нормально). Обкладинки
лежать файлами в каталозі даних, у БД лише хеш і шлях.

## 5. Ключові інтерфейси

### 5.1 Провайдер

```python
@dataclass(frozen=True)
class ProviderInfo:
    id: str  # "gemini"
    display_key: str  # i18n-ключ назви: "provider.gemini"
    default_model: str
    key_url: str
    supports_json_mode: bool


@dataclass
class ChatRequest:
    model: str
    system: str
    user: str
    temperature: float
    json_schema: dict | None  # якщо провайдер підтримує structured output
    max_output_tokens: int | None


@dataclass
class ChatResponse:
    text: str
    finish_reason: str | None  # "stop" | "length" | "content_filter" | …
    input_tokens: int | None
    output_tokens: int | None


class LLMProvider(Protocol):
    info: ProviderInfo

    async def chat(self, req: ChatRequest, api_key: str) -> ChatResponse: ...
    def classify_error(
        self, status: int, body: dict | str, headers: Mapping[str, str]
    ) -> ProviderError: ...
    async def list_models(self, api_key: str) -> list[str]: ...
```

Новий OpenAI-сумісний провайдер — це ~15 рядків:

```python
@register_provider
class DeepSeekProvider(OpenAICompatProvider):
    info = ProviderInfo(
        id="deepseek",
        display_key="provider.deepseek",
        default_model="deepseek-chat",
        key_url="https://platform.deepseek.com/api_keys",
        supports_json_mode=True,
    )
    base_url = "https://api.deepseek.com"
```

Провайдер з іншим API (наприклад, нативний Gemini з `safetySettings` або Anthropic)
реалізує той самий `LLMProvider` напряму.

### 5.2 Класифікація помилок (`core/errors.py`)

```python
class ProviderError(Exception): ...


class RateLimited(ProviderError):
    retry_after: float | None  # RPM/TPM: cooldown ключа на секунди


class QuotaExhausted(ProviderError):
    reset_at: datetime | None  # денна/місячна квота: ключ «вичерпаний» до скидання


class AuthFailed(ProviderError): ...  # ключ невалідний: вимкнути, попросити користувача


class ContentRefused(ProviderError): ...  # відмова/фільтр: ротація ключа не допоможе


class InvalidOutput(ProviderError): ...  # невалідний JSON / не всі сегменти


class Transient(ProviderError): ...  # 5xx, таймаут, мережа: backoff на тому ж ключі
```

### 5.3 Пул ключів

```python
class KeyPool:
    def __init__(self, accounts: AccountRepo, secrets: SecretStore, clock: Clock): ...
    async def acquire(self, provider_id: str) -> Lease:
        """Повертає найпріоритетніший доступний акаунт, чекаючи на його RPM-лімітер.
        Кидає AllKeysUnavailable(resume_at) якщо всі в cooldown/вичерпані/вимкнені."""
    def report_success(self, lease: Lease, usage: Usage) -> None: ...
    def report_error(self, lease: Lease, err: ProviderError) -> None:
        """RateLimited → cooldown_until; QuotaExhausted → exhausted_until;
        AuthFailed → enabled=False; інші не змінюють стан ключа."""

Рішення 2026-11-11: ротація йде і між провайдерами. `acquire()` приймає не один `provider_id`,
а ланцюжок акаунтів твору (`WorkSettings.account_chain`, за замовчуванням усі увімкнені акаунти
за `priority`). Коли акаунт недоступний, береться наступний, навіть якщо це інший провайдер і
модель. Промт однаковий для всіх, бо збирається з БД; відмінності провайдерів (JSON-режим,
ліміти токенів) закриває сам клас провайдера. У `Segment` додається поле
`translated_by: str | None` (`"gemini/gemini-2.5-flash"`), щоб у редакторі було видно, де
модель змінилася.

@dataclass
class Lease:
    account_id: UUID
    api_key: str          # живе лише в пам'яті, ніколи не логуватися (repr приховує)
    model: str
```

### 5.4 Оркестратор

```python
class Translator:
    def __init__(
        self,
        providers: ProviderRegistry,
        pool: KeyPool,
        repo: ProjectRepository,
        prompts: PromptBuilder,
        events: EventSink,
    ): ...

    async def run(self, job_id: UUID) -> JobResult:
        """Цикл: взяти наступний чанк pending-сегментів → зібрати промт із БД →
        викликати з ротацією ключів → провалідувати → в ОДНІЙ транзакції записати
        сегменти, примітки, спірні, пропозиції глосарію, хвости, статистику.
        Скасування (CancelledError) безпечне: незавершений чанк лишається pending."""
```

Алгоритм одного чанка:

```
for attempt in range(MAX_ATTEMPTS):
    lease = await pool.acquire(provider)                  # може кинути AllKeysUnavailable → job.waiting_quota
    try:
        resp = await provider.chat(request, lease.api_key)
        result = parse_and_validate(resp, expected_segment_ids)
        if refusal.detect(chunk, result, resp.finish_reason): mark NEEDS_REVIEW; break
        repo.commit_chunk(job, result)                     # одна транзакція
        pool.report_success(lease, usage); break
    except RateLimited | QuotaExhausted | AuthFailed as e:
        pool.report_error(lease, e); continue              # той самий чанк, наступний ключ
    except Transient:   await backoff(attempt); continue    # той самий ключ
    except InvalidOutput as e:
        if not retried_with_error: request = request.with_error_feedback(e); continue
        mark NEEDS_REVIEW; break
    except ContentRefused: mark NEEDS_REVIEW; break        # або fallback-провайдер, якщо налаштовано
```

Реалізація (фаза 1): `services/translator.py`, бо оркестратор використовує сервіси (пул,
провайдери) і сховище, а `core/` не імпортує `services/`. Події передаються колбеком
`on_event`.

Події (`EventSink`) для UI: `ChunkStarted`, `ChunkDone(progress, eta, preview)`, `KeySwitched`,
`WaitingQuota(resume_at)`, `SegmentNeedsReview`, `JobFinished`. UI лише підписується.

### 5.5 Формат відповіді LLM (`core/llm_schema.py`)

Модель отримує сегменти з короткими локальними ID (`s1…sN`, мапляться на UUID) і повертає:

```json
{
  "segments": [{"id": "s1", "translation": "…", "censored": false}],
  "notes": [{"segment": "s3", "type": "cultural", "anchor": "Обон",
             "source_fragment": "お盆", "text": "…", "first_occurrence": true}],
  "disputes": [{"segment": "s5", "source_fragment": "剣聖", "issue": "…",
                "options": [{"text": "Святий Меча", "rationale": "…"}],
                "recommended": 0, "add_to_glossary": true}],
  "glossary_suggestions": [{"source": "魔力", "target": "мана", "kind": "term"}]
}
```

Валідація: усі `id` з запиту присутні рівно один раз; 2–4 варіанти в спірному; `recommended`
в межах; не більше ~5 спірних на чанк; `finish_reason == "length"` → `InvalidOutput`
(чанк завеликий, ділимо навпіл і повторюємо).

### 5.6 Збирання промту

`PromptBuilder.build(chunk, work, job) -> ChatRequest` збирає блоки в порядку skill §9:
роль → стислі правила українською → налаштування твору (суфікси, цензура, стиль) →
**тільки ті терміни глосарію, що трапляються в чанку** (пошук підрядків, для CJK без
токенізації) з позначкою `locked` → резюме сюжету + хвіст оригіналу й перекладу → формат JSON.
Кожен блок — окрема функція з тестом. Другий прохід отримує оригінал, чернетку, глосарій і
чекліст skill §10, повертає виправлені сегменти + список змін.

Резюме сюжету оновлюється окремим дешевим запитом кожні ~10 чанків (≤ 300 слів). Це
дозволяє тримати контекст тому без передачі всього попереднього тексту.

### 5.7 Сховище секретів

```python
class SecretStore(Protocol):
    def available(self) -> bool: ...
    def set(self, ref: str, secret: str) -> None: ...
    def get(self, ref: str) -> str | None: ...
    def delete(self, ref: str) -> None: ...
```

Вибір при старті: `KeyringStore` (Windows/Linux з Secret Service) → `AndroidKeystoreStore` →
`FernetStore` (файл `secrets.enc`, ключ = scrypt(майстер-пароль, сіль), пароль питається раз
за сесію, або опційно «запам'ятати на цьому пристрої»: похідний ключ у `device.key` з правами
лише власника, рішення 2026-11-11). У БД зберігається лише `secret_ref` (`"ranobe:account:<uuid>"`).
Гарантії: `Lease.__repr__` і логер маскують ключі (фільтр за регулярками `AIza…`, `sk-…`),
`provider_accounts` і секрети виключені з синхронізації та експорту.

### 5.8 Імпорт/експорт

```python
class Importer(Protocol):
    extensions: tuple[str, ...]

    def read(self, path: Path) -> ImportedBook: ...  # метадані + розділи з абзацами


class Exporter(Protocol):
    id: str
    display_key: str
    extension: str

    def export(
        self, work: Work, chapters: list[ChapterWithSegments], opts: ExportOptions, out: Path
    ) -> None: ...
```

EPUB-експорт: розділ = XHTML-файл; примітки як EPUB3 виноски
(`<a epub:type="noteref" href="#n12">` + `<aside epub:type="footnote" id="n12">`), що в
більшості читалок відкриваються спливаючим вікном; обкладинка, метадані (автор, жанри,
анотація), стабільний `urn:uuid:` з `Work.id`.

**Реалізовано у фазі 2.** `collect_book(repos, work)` збирає `ExportBook`: розділ, що
починається сегментом-заголовком, бере його переклад як назву (у тексті заголовок не
повторюється); неперекладені сегменти йдуть оригіналом. Маркер примітки ставиться одразу
після першої появи `anchor` у перекладі (`core/footnotes.py`); якщо anchor зник після
редагування, примітка не губиться, а йде в кінець абзацу. `ExportOptions`: `side_by_side`,
`with_notes`, `cover`, а для CBZ `page_size` і `font_size`.

- **TXT:** маркери `[n]`, список приміток після кожного розділу.
- **EPUB 3:** `mimetype` першим і без стиснення, `nav.xhtml` і `toc.ncx` (для старих читалок),
  виноски noteref/aside, обкладинка (`properties="cover-image"`), `dcterms:modified` з
  `Work.updated_at`, тож повторний експорт дає ідентичний OPF. Перевірка `epubcheck` іде
  окремою задачею в CI (локально потрібна Java).
- **CBZ:** сторінки PNG у відтінках сірого, рендер через Pillow вбудованим Noto Serif (OFL,
  працює й на Android). Обкладинка або згенерований титул першою сторінкою, кожен розділ з
  нової сторінки, примітки внизу тієї сторінки, де стоїть маркер, `ComicInfo.xml` з метаданими.
  Обмеження: шрифт без CJK, тому неперекладені японські абзаци в CBZ показуються квадратиками;
  side-by-side у CBZ не підтримується.

## 6. Редактор

- **Side-by-side:** список сегментів, кожен рядок = оригінал | переклад, віртуалізований
  `ListView` (тисячі абзаців). На вузькому екрані — один стовпчик з перемикачем або
  оригіналом під перекладом дрібнішим шрифтом.
- **Статуси:** чип на сегменті; фільтри «лише needs_review», «з нерозв'язаними спірними».
  Навігація між проблемними сегментами клавішами (desktop) або кнопками.
- **Спірні моменти:** у тексті стоїть рекомендований варіант, підсвічений; клік відкриває
  картку з варіантами й обґрунтуваннями + поле «свій варіант». Вибір пише `chosen`/`custom_text`,
  замінює фрагмент у перекладі й, якщо `add_to_glossary`, створює `GlossaryEntry(origin="dispute",
  locked=True)` для майбутніх чанків.
- **Примітки:** маркер біля `anchor`; на desktop — tooltip при наведенні, на Android — tap
  відкриває bottom sheet. Тип примітки — іконка й колір. Можна додати свою примітку.
- **Цензура:** рівень у налаштуваннях твору впливає на промт; сегменти з `censored=true`
  позначені, щоб було видно, де текст змінено; для будь-якого сегмента є дія «перекласти
  заново з іншим рівнем».
- **Логіка без UI (фаза 2, `services/editor.py` і `Translator.retranslate_segment`):**
  - `Editor.resolve_dispute(id, chosen=… | custom=…)` замінює поточний варіант (рекомендований
    або попередній вибір) у перекладі лише свого сегмента, ставить сегменту `EDITED`; якщо
    користувач уже переписав фрагмент вручну, текст не чіпається (`applied=False`), але рішення
    й запис у глосарій зберігаються.
  - Примітки: `add_note` / `update_note` / `delete_note` (м'яке видалення для синхронізації).
    Примітки моделі зберігаються лише для першої появи фрагмента в усьому творі; примітки
    користувача ніколи не відкидаються.
  - Глосарій: пропозиції моделі мають `review="pending"`; вони вже йдуть у промт (послідовність
    перекладу), але чекають на рішення. `accept_suggestion` (можна з іншим перекладом) робить
    запис `locked`, `reject_suggestion` ховає його з промтів і не дає моделі запропонувати знову.
  - `retranslate_segment(id, censorship)` перекладає один сегмент з іншим рівнем, не змінюючи
    налаштувань твору; контекст = попередній абзац + останнє резюме. Примітки моделі й
    нерозв'язані спірні цього сегмента замінюються новими.
  - Другий прохід (редагування) отримує чекліст skill §10 мовою перекладу (`rules_*.CHECKLIST`)
    і повертає `censored`; прапорець, поставлений будь-яким проходом, не знімається.
- **Відмови моделей:** `refusal.detect` спрацьовує на порожню відповідь, фрази-відмови,
  `finish_reason=content_filter`, відношення довжини перекладу до оригіналу нижче порогу для
  мови. Сегмент отримує `NEEDS_REVIEW`, ніколи не підставляється мовчки.

## 7. Бібліотека і синхронізація

### 7.1 Варіанти бекенду

| Варіант | Плюси | Мінуси |
|---|---|---|
| **Django + DRF на твоєму сервері (рекомендовано)** | Ти це вмієш; повний контроль; дані не в чужій хмарі; легко додати друзів як користувачів | Треба писати й підтримувати API та бекапи |
| Supabase / PocketBase | Готова авторизація й realtime | Ще одна технологія; логіка конфліктів однаково на клієнті |
| Файлова синхронізація (Syncthing/Drive) SQLite | Нуль коду | SQLite не можна синхронізувати файлом без пошкоджень і конфліктів |

### 7.2 Протокол (Django REST)

- Авторизація: токен (DRF TokenAuthentication або JWT), зберігається в `SecretStore`.
- Кожна синхронізована сутність має `id` (UUID, генерує клієнт), `rev` (серверна версія),
  `updated_at`, `deleted` (tombstone).
- `POST /api/sync/push` — пакет змін з `sync_outbox`, кожна з `base_rev`. Сервер приймає, якщо
  `base_rev == current_rev`, інакше повертає конфлікт із серверною версією.
- `GET /api/sync/pull?cursor=N` — усі зміни після глобального курсора (монотонний лічильник
  на сервері), сторінками.
- `PUT /api/blobs/<sha256>` — обкладинки за хешем (дедуплікація).

### 7.3 Конфлікти

- **Метадані твору, глосарій, закладки:** last-writer-wins по полю (рідко конфліктують).
- **Сегменти:** якщо обидві сторони змінили `translation`, не губимо жодну: локальна версія
  лишається, серверна зберігається як альтернатива, сегмент отримує статус `NEEDS_REVIEW` з
  позначкою «конфлікт синхронізації», і редактор пропонує вибрати.
- **Видалення проти зміни:** зміна перемагає, твір відновлюється.

### 7.4 Офлайн

Усе працює локально завжди; синхронізація — фонова задача при старті, після завершення чанка
(з дебаунсом) і вручну. Outbox переживає перезапуск.

Не синхронізуються: API-ключі, акаунти провайдерів, налаштування пристрою.

### 7.5 Обкладинка й опис

Редактор обкладинки: імпорт зображення → кадрування до 2:3 (рамка, що перетягується, поверх
`ft.Image` у `Stack`, жести через `GestureDetector`) → накладання назви (шрифт, розмір, колір,
позиція верх/низ, напівпрозора плашка) → Pillow рендерить фінальний JPEG 1600×2400. Форма
опису: автор, оригінальна назва, жанри й теги (чипи з автодоповненням), анотація, статус
перекладу.

## 8. i18n і довідка

```python
t("library.empty.title")  # простий рядок
t("translate.progress", done=3, total=40)  # підстановка
t("segments.count", n=5)  # множина: uk має one/few/many, en one/other
set_locale("en")  # викликає підписників → UI перебудовує поточний view
```

- Файли `i18n/locales/uk.json`, `en.json`; плоскі ключі з крапками; тест перевіряє, що набори
  ключів однакові й плейсхолдери збігаються.
- Перемикання без перезапуску: кожен view будується функцією від стану, `AppState` при
  `locale_changed` перебудовує поточний маршрут і оболонку навігації.
- Довідка: `help/<locale>/<page>.md`, рендер через `ft.Markdown`. Контекстні підказки:
  `HelpIcon(topic="key_pool")` біля складних налаштувань відкриває короткий текст з ключа
  `help.tip.key_pool` і посилання «Докладніше» на сторінку довідки.
- Мова інтерфейсу не залежить від мов перекладу. Мови перекладу зберігаються кодами BCP-47,
  назви беруться з i18n.

## 9. Дизайн-система

`ui/theme/tokens.py` — єдине джерело значень, компоненти не використовують «магічних» чисел.

- **Кольори:** Material 3 `color_scheme_seed` (наприклад, індиго `#4F5BD5`) для світлої й
  темної схем + семантичні токени: `status.pending/translated/needs_review/reviewed`,
  `note.<type>`, `dispute.highlight`.
- **Типографіка:** шкала M3 (display / headline / title / body / label); окремий токен
  `reading` для тексту перекладу (розмір і міжрядковий інтервал налаштовуються в читанні).
  Шрифт з підтримкою кирилиці й CJK (Noto Sans + Noto Sans JP/SC, вбудовані в збірку).
- **Відступи:** 4 · 8 · 12 · 16 · 24 · 32 · 48. **Радіуси:** 4 · 8 · 16 · 28.
- **Тривалості анімацій:** `fast=150ms` (наведення, чипи), `normal=250ms` (появи, панелі),
  `slow=400ms` (переходи сторінок); крива `EASE_OUT_CUBIC`. Налаштування «зменшити анімації»
  обнуляє тривалості.
- **Breakpoints:** `compact < 600` (телефон: `NavigationBar` знизу, один стовпчик),
  `medium 600–1024` (`NavigationRail`, side-by-side за бажанням), `expanded ≥ 1024`
  (rail + side-by-side + бічна панель приміток/спірних).
- **Компоненти:** `AppButton` (filled/tonal/text), `Card`, `StatusChip`, `SegmentRow`,
  `NoteMarker`, `DisputeCard`, `ProgressPanel` (прогрес, ETA, активний ключ, стан квоти),
  `EmptyState`, `HelpIcon`, `ConfirmDialog`, `Toast`.
- Тема: світла / темна / системна, перемикання без перезапуску (`page.theme_mode`).

## 10. Пакування й оновлення

### 10.1 Збірка

`flet build` для всіх платформ у GitHub Actions (матриця `windows-latest`, `ubuntu-latest`):

| Платформа | Артефакт релізу | Примітка |
|---|---|---|
| Windows | `RanobeTranslator-<ver>-windows-x64.zip` (тека з exe) | onedir, без UPX (менше хибних спрацювань антивірусу) |
| Linux | `RanobeTranslator-<ver>-linux-x86_64.AppImage` | вихід `flet build linux`, загорнутий `appimagetool` |
| Android | `RanobeTranslator-<ver>.apk` (підписаний, minSdk 31 = Android 12) | ключ підпису в GitHub Secrets; втрата ключа = неможливість оновлення поверх |
| Усі | `SHA256SUMS` + `SHA256SUMS.sig` | підпис ed25519 (minisign), публічний ключ вшитий у застосунок |

Чому не PyInstaller: він не збирає Android, а `flet build` дає один процес для всіх платформ.
`flet pack` (PyInstaller) лишається запасним варіантом для Windows, якщо `flet build` чимось не
влаштує.

### 10.2 Оновлювач (`services/updater/`)

1. `GET https://api.github.com/repos/<owner>/<repo>/releases/latest` → порівняти тег з
   `__version__` (семантичні версії).
2. Показати changelog з тіла релізу, кнопка «Оновити».
3. Завантажити архів для платформи і `SHA256SUMS` (+ `.sig`), перевірити підпис і хеш.
   Хеш без підпису захищає лише від пошкодження, не від підміни релізу, тому підпис бажаний.
4. Встановлення:
   - **Windows:** розпакувати в `%LOCALAPPDATA%\RanobeTranslator\versions\<ver>`, запустити
     маленький `updater.exe` (окремий скрипт, зібраний разом), який чекає завершення процесу,
     перемикає `current` на нову теку, запускає її й прибирає стару.
   - **Linux:** записати новий AppImage поруч, `os.replace` поверх старого (працює для запущеного
     файлу), `os.execv` новий.
   - **Android:** застосунок не може тихо замінити себе. Відкриваємо URL APK з релізу
     (`page.launch_url`), система завантажує й пропонує встановити. Цілісність гарантує підпис
     APK (Android відмовить, якщо ключ інший). Потрібен дозвіл «встановлення з невідомих джерел».
5. Дані користувача лежать окремо від теки застосунку, тому оновлення їх не торкається;
   міграції БД виконуються при першому старті нової версії (з бекапом `library.db.bak-<ver>`).

## 11. Каталоги даних

| Платформа | Дані |
|---|---|
| Windows | `%APPDATA%\RanobeTranslator\` |
| Linux | `$XDG_DATA_HOME/ranobe-translator/` |
| Android | каталог застосунку від Flet (`FLET_APP_STORAGE_DATA`) |

Міграції зі старої версії немає (рішення 2026-11-11): нова версія стартує з порожньою
бібліотекою й не читає `~/.ranobe_translator/`.
