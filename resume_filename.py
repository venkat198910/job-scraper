import re


def slugify_filename_part(value: object, fallback: str = "resume", max_length: int = 48) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = fallback
    return text[:max_length].strip("_") or fallback


def compact_job_id(value: object) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("workday-"):
        match = re.search(r"-([a-z]+-\d+[a-z0-9-]*|\d+[a-z0-9]*)$", text)
        if match:
            return match.group(1)
    return text


def build_custom_resume_filename(
    candidate_name: str = "",
    company: str = "",
    job_title: str = "",
    job_id: str = "",
) -> str:
    candidate_part = slugify_filename_part(candidate_name, "venkateswarlu_derangula", 28)
    job_part = slugify_filename_part(compact_job_id(job_id), "job", 24)
    return f"{candidate_part}_resume_{job_part}.pdf"
