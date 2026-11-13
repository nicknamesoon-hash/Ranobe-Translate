-- Model suggestions wait in a review queue: 'pending' entries are used in prompts but not
-- yet confirmed, 'rejected' ones are hidden. 'none' = a normal entry.
ALTER TABLE glossary ADD COLUMN review TEXT NOT NULL DEFAULT 'none';
UPDATE glossary SET review = 'pending' WHERE origin = 'llm_suggestion' AND locked = 0;
