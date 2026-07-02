ALTER TABLE public.jobs
    ADD COLUMN IF NOT EXISTS job_url text,
    ADD COLUMN IF NOT EXISTS apply_url text,
    ADD COLUMN IF NOT EXISTS career_url text;

COMMENT ON COLUMN public.jobs.job_url IS 'Canonical job posting URL from the source provider';
COMMENT ON COLUMN public.jobs.apply_url IS 'Direct application URL for company career portals when available';
COMMENT ON COLUMN public.jobs.career_url IS 'Company career search page URL used by the scraper';

NOTIFY pgrst, 'reload schema';
