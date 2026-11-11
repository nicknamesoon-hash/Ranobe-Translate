"""Remove API keys from any text that may reach a log, an error message or the UI."""

from __future__ import annotations

import logging
import re

_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),  # Google
    re.compile(r"sk-[0-9A-Za-z_\-]{16,}"),  # OpenAI-style (DeepSeek, OpenRouter, ...)
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),  # Groq
    re.compile(r"(?i)(bearer\s+)[0-9A-Za-z._\-]{16,}"),
    re.compile(r"(?i)([?&]key=)[0-9A-Za-z._\-]{16,}"),
]


def redact(text: str, extra: list[str] | None = None) -> str:
    for secret in extra or []:
        if secret:
            text = text.replace(secret, "***")
    for pattern in _PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + "***", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


def install_log_redaction(logger: logging.Logger | None = None) -> None:
    target = logger or logging.getLogger()
    for handler in target.handlers or []:
        handler.addFilter(RedactingFilter())
    target.addFilter(RedactingFilter())
