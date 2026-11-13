"""Editor actions on translated text: everything the editor screen does, without UI.

Each action runs in one transaction, so a segment, its dispute and the glossary never
disagree after a crash.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ranobe.core.models import Dispute, GlossaryEntry, SegmentStatus, utcnow
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
