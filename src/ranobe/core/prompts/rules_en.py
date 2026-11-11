"""Draft rules for English as the target language. Needs review by the user: the
ranobe-translation-rules skill only covers Ukrainian so far."""

BASE = """\
Principles:
- Meaning and voice matter more than literalness. The text must read as natural English prose.
- Keep the author's style: short sentences stay short, inner monologue stays monologue, comedy stays comedic.
- Every character keeps a consistent voice across the work.
- Names, terms, techniques, ranks and places come from the glossary. Propose new terms in glossary_suggestions instead of inventing a new rendering each time.
- Do not silently add or drop anything: record lost meaning as a note, equally valid options as a dispute.

English conventions:
- Use standard double quotes for dialogue, one paragraph per speaker, a single ellipsis character …
- Prefer active voice and concrete verbs. Avoid translationese and calques.
- Small numbers in words ("three days"); stats and system windows (LitRPG) in digits.

Onomatopoeia, wordplay, dialects:
- Render onomatopoeia with English sound words or description ("doki-doki" → "her heart pounded"); keep a romanized SFX only if it is a deliberate stylistic device, with a note.
- Adapt wordplay with an English equivalent where possible; otherwise translate literally and add a wordplay note.
- Do not map dialects onto a specific real English dialect; use colourful colloquial speech and add a note on first appearance.
- Archaic speech gets light archaisms, without overdoing it."""

NAMES = {
    "ja": "Romanize Japanese names not in the glossary with modified Hepburn (Satō may be written Sato; be consistent). Family-name order follows the source unless the glossary says otherwise.",
    "ko": "Romanize Korean names not in the glossary with the Revised Romanization, keeping established spellings of common surnames (Kim, Lee, Park).",
    "en": "",
}

HONORIFICS = {
    "keep": "Keep Japanese honorifics with a hyphen: Sato-san, Yuki-chan, Tanaka-senpai, Yamada-sensei. Add a cultural note on the first appearance of each honorific.",
    "adapt": "Render Japanese honorifics with English means: -san → Mr./Ms. or first name, -sama → Lord/Lady, -senpai → senior, sensei → teacher/Master.",
    "drop": "Drop Japanese honorifics; convey politeness through word choice.",
}

HONORIFICS_ALWAYS = "A change of honorific or form of address is often a plot point: do not smooth it over, and add a note in adapt/drop modes. Keigo → formal register; rude speech (ore, teme, kisama) → blunt, rough colloquial register."
