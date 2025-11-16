-- Migration: Add Row Level Security to file_parsings table
-- Ensures users can only see parsing records for their own files

-- Enable RLS on file_parsings table
ALTER TABLE "public"."file_parsings" ENABLE ROW LEVEL SECURITY;

-- Grant permissions to anon role
GRANT DELETE ON TABLE "public"."file_parsings" TO "anon";
GRANT INSERT ON TABLE "public"."file_parsings" TO "anon";
GRANT REFERENCES ON TABLE "public"."file_parsings" TO "anon";
GRANT SELECT ON TABLE "public"."file_parsings" TO "anon";
GRANT TRIGGER ON TABLE "public"."file_parsings" TO "anon";
GRANT TRUNCATE ON TABLE "public"."file_parsings" TO "anon";
GRANT UPDATE ON TABLE "public"."file_parsings" TO "anon";

-- Grant permissions to authenticated role
GRANT DELETE ON TABLE "public"."file_parsings" TO "authenticated";
GRANT INSERT ON TABLE "public"."file_parsings" TO "authenticated";
GRANT REFERENCES ON TABLE "public"."file_parsings" TO "authenticated";
GRANT SELECT ON TABLE "public"."file_parsings" TO "authenticated";
GRANT TRIGGER ON TABLE "public"."file_parsings" TO "authenticated";
GRANT TRUNCATE ON TABLE "public"."file_parsings" TO "authenticated";
GRANT UPDATE ON TABLE "public"."file_parsings" TO "authenticated";

-- Grant permissions to service_role
GRANT DELETE ON TABLE "public"."file_parsings" TO "service_role";
GRANT INSERT ON TABLE "public"."file_parsings" TO "service_role";
GRANT REFERENCES ON TABLE "public"."file_parsings" TO "service_role";
GRANT SELECT ON TABLE "public"."file_parsings" TO "service_role";
GRANT TRIGGER ON TABLE "public"."file_parsings" TO "service_role";
GRANT TRUNCATE ON TABLE "public"."file_parsings" TO "service_role";
GRANT UPDATE ON TABLE "public"."file_parsings" TO "service_role";

-- Create SELECT policy: Users can view parsings for their own files only
CREATE POLICY "Users can view parsings for their own files."
ON "public"."file_parsings"
AS PERMISSIVE
FOR SELECT
TO authenticated
USING (
    (
        EXISTS (
            SELECT 1
            FROM files
            WHERE (
                files.file_id = file_parsings.file_id
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

-- Service role has full access
CREATE POLICY "Service role can manage all parsings."
ON "public"."file_parsings"
AS PERMISSIVE
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);
