-- Function to update storage object owner_id
-- This is needed because storage.objects is not accessible via the regular table API

CREATE OR REPLACE FUNCTION update_storage_owner(
    file_path TEXT,
    bucket_name TEXT,
    new_owner_id UUID
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    UPDATE storage.objects 
    SET owner_id = new_owner_id
    WHERE name = file_path 
    AND bucket_id = bucket_name;
    
    -- Return true if a row was updated
    RETURN FOUND;
END;
$$;

-- Grant execute permission to service role
GRANT EXECUTE ON FUNCTION update_storage_owner TO service_role;