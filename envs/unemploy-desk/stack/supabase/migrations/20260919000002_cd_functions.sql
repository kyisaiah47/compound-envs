-- The two RPCs the app calls. Definitions read out of the live project on 2026-09-19 with
-- pg_get_functiondef, reproduced here verbatim so the environment behaves like production.

CREATE OR REPLACE FUNCTION public.cd_set_mapping_field(doc uuid, col text, val text)
 RETURNS void
 LANGUAGE sql
 SET search_path TO 'public'
AS $function$
  update public.cd_documents
     set mapping = jsonb_set(
           coalesce(mapping, '{}'::jsonb),
           array['fields', col],
           case when val is null then 'null'::jsonb else to_jsonb(val) end,
           true)
   where id = doc
     and audit_started_at is null;
$function$;

CREATE OR REPLACE FUNCTION public.cd_clear_mapping_field(doc uuid, col text)
 RETURNS void
 LANGUAGE sql
 SET search_path TO 'public'
AS $function$
  update public.cd_documents
     set mapping = jsonb_set(
           coalesce(mapping, '{}'::jsonb),
           '{fields}',
           coalesce(mapping -> 'fields', '{}'::jsonb) - col,
           true)
   where id = doc
     and audit_started_at is null;
$function$;
