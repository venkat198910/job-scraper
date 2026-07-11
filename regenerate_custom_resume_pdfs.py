import argparse
import logging
import re

import app_settings
import config
import pdf_generator
import supabase_utils
from models import Resume
from resume_filename import build_custom_resume_filename


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _configured_total_experience_phrase() -> str:
    profile = app_settings.get_application_profile()
    raw_total_experience = str(profile.get("totalExperience") or "9.6").strip()
    try:
        years = int(float(raw_total_experience))
    except ValueError:
        years = 9
    return f"over {years} years"


def _enforce_total_experience(summary: str) -> str:
    expected_phrase = _configured_total_experience_phrase()
    text = str(summary or "")
    patterns = [
        (r"\bover\s+\d+(?:\.\d+)?\+?\s+years\s+of\s+experience\b", f"{expected_phrase} of experience"),
        (r"\bover\s+\d+(?:\.\d+)?\+?\s+years\b", expected_phrase),
        (r"(?<!over )\b\d+(?:\.\d+)?\+?\s+years\s+of\s+experience\b", f"{expected_phrase} of experience"),
        (r"(?<!over )\b\d+(?:\.\d+)?\+?\s+years'\s+experience\b", f"{expected_phrase} of experience"),
    ]
    for pattern, replacement in patterns:
        text, count = re.subn(pattern, replacement, text, count=1, flags=re.IGNORECASE)
        if count:
            return text
    return text


def _fetch_customized_resumes(limit: int | None = None, batch_size: int = 100) -> list[dict]:
    rows: list[dict] = []
    offset = 0

    while True:
        end = offset + batch_size - 1
        if limit is not None:
            remaining = limit - len(rows)
            if remaining <= 0:
                break
            end = offset + min(batch_size, remaining) - 1

        response = (
            supabase_utils.supabase.table(config.SUPABASE_CUSTOMIZED_RESUMES_TABLE_NAME)
            .select("*")
            .range(offset, end)
            .execute()
        )
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < (end - offset + 1):
            break
        offset += batch_size

    return rows


def _fetch_job_metadata_by_resume_id() -> dict[str, dict]:
    metadata: dict[str, dict] = {}
    offset = 0
    batch_size = 1000

    while True:
        response = (
            supabase_utils.supabase.table(config.SUPABASE_TABLE_NAME)
            .select("job_id, company, job_title, customized_resume_id")
            .not_.is_("customized_resume_id", None)
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        rows = response.data or []
        for row in rows:
            resume_id = row.get("customized_resume_id")
            if resume_id:
                metadata[str(resume_id)] = row
        if len(rows) < batch_size:
            break
        offset += batch_size

    return metadata


def _new_resume_path(record: dict, job_metadata: dict | None = None) -> str:
    job_metadata = job_metadata or {}
    return build_custom_resume_filename(
        candidate_name=record.get("name", ""),
        company=job_metadata.get("company") or "company",
        job_title=job_metadata.get("job_title") or "custom_resume",
        job_id=job_metadata.get("job_id") or str(record.get("id", ""))[:8],
    )


def regenerate_existing_custom_resume_pdfs(limit: int | None = None, dry_run: bool = False) -> tuple[int, int]:
    records = _fetch_customized_resumes(limit=limit)
    logging.info("Found %s customized resume record(s).", len(records))
    job_metadata_by_resume_id = _fetch_job_metadata_by_resume_id()
    logging.info("Found job metadata for %s customized resume record(s).", len(job_metadata_by_resume_id))

    updated = 0
    failed = 0
    for record in records:
        resume_id = record.get("id")
        try:
            resume_data = Resume.model_validate(record)
            resume_data.summary = _enforce_total_experience(resume_data.summary)
            pdf_bytes = pdf_generator.create_resume_pdf(resume_data)
            destination_path = _new_resume_path(record, job_metadata_by_resume_id.get(str(resume_id)))

            if dry_run:
                logging.info("DRY RUN: would update customized_resume id=%s to %s", resume_id, destination_path)
                updated += 1
                continue

            uploaded_path = supabase_utils.upload_customized_resume_to_storage(pdf_bytes, destination_path)
            if not uploaded_path:
                raise RuntimeError("storage upload returned no path")

            response = (
                supabase_utils.supabase.table(config.SUPABASE_CUSTOMIZED_RESUMES_TABLE_NAME)
                .update({"resume_link": uploaded_path, "summary": resume_data.summary})
                .eq("id", resume_id)
                .execute()
            )
            if not response.data:
                raise RuntimeError("database update returned no rows")

            logging.info("Updated customized_resume id=%s with %s", resume_id, uploaded_path)
            updated += 1
        except Exception as exc:
            failed += 1
            logging.error("Failed to regenerate customized_resume id=%s: %s", resume_id, exc, exc_info=True)

    return updated, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate existing customized resume PDFs with the current PDF template.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N customized resumes.")
    parser.add_argument("--dry-run", action="store_true", help="Build and validate without uploading/updating Supabase.")
    args = parser.parse_args()

    updated, failed = regenerate_existing_custom_resume_pdfs(limit=args.limit, dry_run=args.dry_run)
    logging.info("Finished. updated=%s failed=%s", updated, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
