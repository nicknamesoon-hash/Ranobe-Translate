"""Editor actions on translated text: everything the editor screen does, without UI.

Each action runs in one transaction, so a segment, its dispute and the glossary never
disagree after a crash.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ranobe.core.models import (
    Dispute,
    GlossaryEntry,
    Note,
    NoteType,
    SegmentStatus,
    utcnow,
)
from ranobe.storage.repositories import Repositories


@dataclass
class DisputeResolution:
    dispute: Dispute
    applied: bool  # False: the old fragment was no longer in the translation (edited by hand)
    glossary_entry: GlossaryEntry | None


class Editor:
    def __init__(self, repos: Repositories):
        self.repos = repos

    def resolve_dispute(
        self, dispute_id: UUID, chosen: int | None = None, custom: str | None = None
    ) -> DisputeResolution:
        """Pick an option (by index) or a custom text for a dispute.

        The text currently in the translation is replaced by the new one, only inside the
        dispute's own segment. If the dispute concerns a term, the choice becomes a locked
        glossary entry, so every following chunk uses it.
        """
        if (chosen is None) == (custom is None):
            raise ValueError("give exactly one of chosen or custom")
        dispute = self.repos.disputes.get(dispute_id)
        if dispute is None:
            raise KeyError(f"dispute {dispute_id} not found")
        if chosen is not None and not 0 <= chosen < len(dispute.options):
            raise ValueError(f"option {chosen} out of range 0..{len(dispute.options) - 1}")
        if custom is not None:
            custom = custom.strip()
            if not custom:
                raise ValueError("custom text is empty")
        segment = self.repos.segments.get(dispute.segment_id)
        work_id = self.repos.segments.work_id_of(dispute.segment_id)
        if segment is None or work_id is None:
            raise KeyError(f"segment {dispute.segment_id} not found")

        old_text = dispute.current_text
        dispute.chosen, dispute.custom_text = chosen, custom
        dispute.resolved_at = utcnow()
        new_text = dispute.current_text

        translation = segment.translation or ""
        applied = old_text in translation
        entry = None
        with self.repos.db.transaction():
            if applied and old_text != new_text:
                segment.translation = translation.replace(old_text, new_text)
                segment.status = SegmentStatus.EDITED
                self.repos.segments.save(segment)
            self.repos.disputes.save_resolution(dispute)
            if dispute.add_to_glossary:
                entry = GlossaryEntry(
                    source=dispute.source_fragment,
                    target=new_text,
                    work_id=work_id,
                    origin="dispute",
                    locked=True,
                )
                self.repos.glossary.upsert(entry)
        return DisputeResolution(dispute, applied, entry)

    # --- glossary suggestions ---

    def accept_suggestion(self, entry_id: UUID, target: str | None = None) -> GlossaryEntry:
        """Confirm a model suggestion, optionally with another rendering. The entry becomes
        locked, so the model can no longer change it."""
        entry = self._suggestion(entry_id)
        if target is not None:
            entry.target = _required(target, "target")
        entry.locked, entry.review = True, "none"
        self.repos.glossary.upsert(entry)
        return entry

    def reject_suggestion(self, entry_id: UUID) -> None:
        """Hide a suggestion from prompts. It stays stored so the model does not suggest the
        same term again."""
        entry = self._suggestion(entry_id)
        entry.review = "rejected"
        self.repos.glossary.upsert(entry)

    def _suggestion(self, entry_id: UUID) -> GlossaryEntry:
        entry = self.repos.glossary.get(entry_id)
        if entry is None or entry.review != "pending":
            raise KeyError(f"no pending glossary suggestion {entry_id}")
        return entry

    # --- notes ---

    def add_note(
        self,
        segment_id: UUID,
        anchor: str,
        text: str,
        type: NoteType = NoteType.TRANSLATOR_CHOICE,
        source_fragment: str = "",
    ) -> Note:
        """A note written by the user. Unlike model notes it is never dropped as a repeat."""
        if self.repos.segments.get(segment_id) is None:
            raise KeyError(f"segment {segment_id} not found")
        note = Note(
            segment_id=segment_id,
            type=type,
            anchor=_required(anchor, "anchor"),
            source_fragment=source_fragment.strip(),
            text=_required(text, "text"),
            origin="user",
        )
        self.repos.notes.add(note)
        return note

    def update_note(
        self,
        note_id: UUID,
        *,
        text: str | None = None,
        anchor: str | None = None,
        type: NoteType | None = None,
        display: str | None = None,
    ) -> Note:
        note = self.repos.notes.get(note_id)
        if note is None:
            raise KeyError(f"note {note_id} not found")
        if text is not None:
            note.text = _required(text, "text")
        if anchor is not None:
            note.anchor = _required(anchor, "anchor")
        if type is not None:
            note.type = type
        if display is not None:
            if display not in ("footnote", "tooltip"):
                raise ValueError(f"unknown display {display!r}")
            note.display = display  # type: ignore[assignment]
        self.repos.notes.update(note)
        return note

    def delete_note(self, note_id: UUID) -> None:
        if self.repos.notes.get(note_id) is None:
            raise KeyError(f"note {note_id} not found")
        self.repos.notes.delete(note_id)


def _required(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is empty")
    return value
