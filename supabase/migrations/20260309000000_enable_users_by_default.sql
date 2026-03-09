-- Change the default value of enabled to true so new users start enabled
ALTER TABLE public.user_profiles ALTER COLUMN enabled SET DEFAULT true;

-- Update handle_new_user to explicitly set enabled = true
CREATE OR REPLACE FUNCTION public.handle_new_user()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
BEGIN
    INSERT INTO public.user_profiles (user_id, enabled)
    VALUES (NEW.id, true);
    RETURN NEW;
END;
$function$
;
