-- Add audio_path column to page_sentences to cache synthesized audio in storage
ALTER TABLE page_sentences ADD COLUMN audio_path text;
