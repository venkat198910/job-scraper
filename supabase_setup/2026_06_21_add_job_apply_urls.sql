ALTER TABLE public.jobs
    ADD COLUMN IF NOT EXISTS job_url text,
    ADD COLUMN IF NOT EXISTS apply_url text,
    ADD COLUMN IF NOT EXISTS career_url text;

COMMENT ON COLUMN public.jobs.job_url IS 'Canonical job posting URL from the source provider';
COMMENT ON COLUMN public.jobs.apply_url IS 'Direct application URL for company career portals when available';
COMMENT ON COLUMN public.jobs.career_url IS 'Company career search page URL used by the scraper';

ALTER TABLE public.application_queue
    ADD COLUMN IF NOT EXISTS apply_url text;

COMMENT ON COLUMN public.application_queue.apply_url IS 'URL used by the Applications page to open the queued job/application';

UPDATE public.application_queue aq
SET apply_url = COALESCE(NULLIF(j.apply_url, ''), NULLIF(j.job_url, ''), NULLIF(j.career_url, ''))
FROM public.jobs j
WHERE aq.job_id = j.job_id
  AND (aq.apply_url IS NULL OR aq.apply_url = '')
  AND COALESCE(NULLIF(j.apply_url, ''), NULLIF(j.job_url, ''), NULLIF(j.career_url, '')) IS NOT NULL;

NOTIFY pgrst, 'reload schema';
