-- Migration: Add file_pages and page_sentences tables for PDF highlight sync
-- Stores per-page dimensions and per-sentence bounding box polygons
-- extracted from marker-pdf's Document structure during parsing.

-- ============================================================
-- Table: file_pages
-- ============================================================
CREATE TABLE "public"."file_pages" (
    "page_id" uuid NOT NULL DEFAULT gen_random_uuid(),
    "file_id" uuid NOT NULL,
    "page_number" integer NOT NULL,
    "width" double precision NOT NULL,
    "height" double precision NOT NULL,
    "created_at" timestamp without time zone NOT NULL DEFAULT now()
);

ALTER TABLE "public"."file_pages" ENABLE ROW LEVEL SECURITY;

CREATE UNIQUE INDEX file_pages_pkey ON public.file_pages USING btree (page_id);
CREATE INDEX idx_file_pages_file_id ON public.file_pages USING btree (file_id);
CREATE UNIQUE INDEX idx_file_pages_file_page ON public.file_pages USING btree (file_id, page_number);

ALTER TABLE "public"."file_pages" ADD CONSTRAINT "file_pages_pkey" PRIMARY KEY USING INDEX "file_pages_pkey";
ALTER TABLE "public"."file_pages" ADD CONSTRAINT "file_pages_file_id_fkey"
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE NOT VALID;
ALTER TABLE "public"."file_pages" VALIDATE CONSTRAINT "file_pages_file_id_fkey";

-- ============================================================
-- Table: page_sentences
-- ============================================================
CREATE TABLE "public"."page_sentences" (
    "sentence_id" uuid NOT NULL DEFAULT gen_random_uuid(),
    "page_id" uuid NOT NULL,
    "file_id" uuid NOT NULL,
    "text" text NOT NULL,
    "sequence_number" integer NOT NULL,
    "bbox" jsonb NOT NULL,
    "created_at" timestamp without time zone NOT NULL DEFAULT now()
);

ALTER TABLE "public"."page_sentences" ENABLE ROW LEVEL SECURITY;

CREATE UNIQUE INDEX page_sentences_pkey ON public.page_sentences USING btree (sentence_id);
CREATE INDEX idx_page_sentences_page_id ON public.page_sentences USING btree (page_id);
CREATE INDEX idx_page_sentences_file_id ON public.page_sentences USING btree (file_id);
CREATE INDEX idx_page_sentences_sequence ON public.page_sentences USING btree (file_id, sequence_number);

ALTER TABLE "public"."page_sentences" ADD CONSTRAINT "page_sentences_pkey" PRIMARY KEY USING INDEX "page_sentences_pkey";
ALTER TABLE "public"."page_sentences" ADD CONSTRAINT "page_sentences_page_id_fkey"
    FOREIGN KEY (page_id) REFERENCES file_pages(page_id) ON DELETE CASCADE NOT VALID;
ALTER TABLE "public"."page_sentences" VALIDATE CONSTRAINT "page_sentences_page_id_fkey";
ALTER TABLE "public"."page_sentences" ADD CONSTRAINT "page_sentences_file_id_fkey"
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE NOT VALID;
ALTER TABLE "public"."page_sentences" VALIDATE CONSTRAINT "page_sentences_file_id_fkey";

-- ============================================================
-- Grants: file_pages
-- ============================================================
GRANT DELETE ON TABLE "public"."file_pages" TO "anon";
GRANT INSERT ON TABLE "public"."file_pages" TO "anon";
GRANT REFERENCES ON TABLE "public"."file_pages" TO "anon";
GRANT SELECT ON TABLE "public"."file_pages" TO "anon";
GRANT TRIGGER ON TABLE "public"."file_pages" TO "anon";
GRANT TRUNCATE ON TABLE "public"."file_pages" TO "anon";
GRANT UPDATE ON TABLE "public"."file_pages" TO "anon";

GRANT DELETE ON TABLE "public"."file_pages" TO "authenticated";
GRANT INSERT ON TABLE "public"."file_pages" TO "authenticated";
GRANT REFERENCES ON TABLE "public"."file_pages" TO "authenticated";
GRANT SELECT ON TABLE "public"."file_pages" TO "authenticated";
GRANT TRIGGER ON TABLE "public"."file_pages" TO "authenticated";
GRANT TRUNCATE ON TABLE "public"."file_pages" TO "authenticated";
GRANT UPDATE ON TABLE "public"."file_pages" TO "authenticated";

GRANT DELETE ON TABLE "public"."file_pages" TO "service_role";
GRANT INSERT ON TABLE "public"."file_pages" TO "service_role";
GRANT REFERENCES ON TABLE "public"."file_pages" TO "service_role";
GRANT SELECT ON TABLE "public"."file_pages" TO "service_role";
GRANT TRIGGER ON TABLE "public"."file_pages" TO "service_role";
GRANT TRUNCATE ON TABLE "public"."file_pages" TO "service_role";
GRANT UPDATE ON TABLE "public"."file_pages" TO "service_role";

-- ============================================================
-- Grants: page_sentences
-- ============================================================
GRANT DELETE ON TABLE "public"."page_sentences" TO "anon";
GRANT INSERT ON TABLE "public"."page_sentences" TO "anon";
GRANT REFERENCES ON TABLE "public"."page_sentences" TO "anon";
GRANT SELECT ON TABLE "public"."page_sentences" TO "anon";
GRANT TRIGGER ON TABLE "public"."page_sentences" TO "anon";
GRANT TRUNCATE ON TABLE "public"."page_sentences" TO "anon";
GRANT UPDATE ON TABLE "public"."page_sentences" TO "anon";

GRANT DELETE ON TABLE "public"."page_sentences" TO "authenticated";
GRANT INSERT ON TABLE "public"."page_sentences" TO "authenticated";
GRANT REFERENCES ON TABLE "public"."page_sentences" TO "authenticated";
GRANT SELECT ON TABLE "public"."page_sentences" TO "authenticated";
GRANT TRIGGER ON TABLE "public"."page_sentences" TO "authenticated";
GRANT TRUNCATE ON TABLE "public"."page_sentences" TO "authenticated";
GRANT UPDATE ON TABLE "public"."page_sentences" TO "authenticated";

GRANT DELETE ON TABLE "public"."page_sentences" TO "service_role";
GRANT INSERT ON TABLE "public"."page_sentences" TO "service_role";
GRANT REFERENCES ON TABLE "public"."page_sentences" TO "service_role";
GRANT SELECT ON TABLE "public"."page_sentences" TO "service_role";
GRANT TRIGGER ON TABLE "public"."page_sentences" TO "service_role";
GRANT TRUNCATE ON TABLE "public"."page_sentences" TO "service_role";
GRANT UPDATE ON TABLE "public"."page_sentences" TO "service_role";

-- ============================================================
-- RLS Policies: file_pages
-- ============================================================
CREATE POLICY "Users can view pages for their own files."
ON "public"."file_pages"
AS PERMISSIVE
FOR SELECT
TO authenticated
USING (
    (
        EXISTS (
            SELECT 1
            FROM files
            WHERE (
                files.file_id = file_pages.file_id
                AND files.user_id = (SELECT auth.uid())
            )
        )
    )
    AND
    (
        EXISTS (
            SELECT 1
            FROM user_profiles
            WHERE (
                user_profiles.user_id = (SELECT auth.uid())
                AND user_profiles.enabled = true
            )
        )
    )
);

CREATE POLICY "Service role can manage all file pages."
ON "public"."file_pages"
AS PERMISSIVE
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- ============================================================
-- RLS Policies: page_sentences
-- ============================================================
CREATE POLICY "Users can view sentences for their own files."
ON "public"."page_sentences"
AS PERMISSIVE
FOR SELECT
TO authenticated
USING (
    (
        EXISTS (
            SELECT 1
            FROM files
            WHERE (
                files.file_id = page_sentences.file_id
                AND files.user_id = (SELECT auth.uid())
            )
        )
    )
    AND
    (
        EXISTS (
            SELECT 1
            FROM user_profiles
            WHERE (
                user_profiles.user_id = (SELECT auth.uid())
                AND user_profiles.enabled = true
            )
        )
    )
);

CREATE POLICY "Service role can manage all page sentences."
ON "public"."page_sentences"
AS PERMISSIVE
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- ============================================================
-- Comments
-- ============================================================
COMMENT ON TABLE file_pages IS 'Stores per-page metadata (dimensions) for parsed PDF files, used for highlight sync.';
COMMENT ON TABLE page_sentences IS 'Stores sentences with bounding box polygons for PDF highlight sync during TTS playback.';
COMMENT ON COLUMN page_sentences.bbox IS 'JSONB array of line polygons this sentence spans. Each polygon: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]].';
COMMENT ON COLUMN page_sentences.sequence_number IS 'Global sentence ordering across all pages of a file, starting at 0.';
