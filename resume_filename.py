import re


def slugify_filename_part(value: object, fallback: str = "resume", max_length: int = 48) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = fallback
    return text[:max_length].strip("_") or fallback


def build_custom_resume_filename(
    candidate_name: str = "",
    company: str = "",
    job_title: str = "",
    job_id: str = "",
) -> str:
    parts = [
        slugify_filename_part(candidate_name, "venkateswarlu_derangula", 36),
        slugify_filename_part(job_title, "custom_resume", 44),
    ]
    if job_id:
        parts.append(slugify_filename_part(job_id, "job", 24))
    return f"{'_'.join(parts)}.pdf"
