import argparse
import logging

import config
from custom_resume_generator import _enforce_total_experience, build_professional_title
import pdf_generator
import supabase_utils
from models import Resume
from resume_filename import build_custom_resume_filename


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


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
            .select("job_id, company, job_title, level, description, customized_resume_id")
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


def _fetch_current_profile_certifications() -> list:
    base_resume = supabase_utils.get_base_resume()
    if not base_resume:
        logging.warning(
            "Current base resume is unavailable; existing customized-resume certifications will be preserved."
        )
        return []

    try:
        return Resume.model_validate(base_resume).certifications
    except Exception as exc:
        logging.warning(
            "Current base-resume certifications could not be parsed; existing values will be preserved: %s",
            exc,
        )
        return []


def regenerate_existing_custom_resume_pdfs(limit: int | None = None, dry_run: bool = False) -> tuple[int, int]:
    records = _fetch_customized_resumes(limit=limit)
    logging.info("Found %s customized resume record(s).", len(records))
    job_metadata_by_resume_id = _fetch_job_metadata_by_resume_id()
    logging.info("Found job metadata for %s customized resume record(s).", len(job_metadata_by_resume_id))
    profile_certifications = _fetch_current_profile_certifications()
    logging.info(
        "Loaded %s certification(s) from the current profile for existing resume regeneration.",
        len(profile_certifications),
    )

    updated = 0
    failed = 0
    for record in records:
        resume_id = record.get("id")
        try:
            resume_data = Resume.model_validate(record)
            if profile_certifications:
                resume_data.certifications = [
                    certification.model_copy(deep=True)
                    for certification in profile_certifications
                ]
            resume_data.summary = _enforce_total_experience(resume_data.summary)
            job_metadata = job_metadata_by_resume_id.get(str(resume_id), {})
            resume_data.professional_title = build_professional_title(job_metadata, resume_data)
            pdf_bytes = pdf_generator.create_resume_pdf(resume_data)
            destination_path = _new_resume_path(record, job_metadata)

            if dry_run:
                logging.info("DRY RUN: would update customized_resume id=%s to %s", resume_id, destination_path)
                updated += 1
                continue

            uploaded_path = supabase_utils.upload_customized_resume_to_storage(pdf_bytes, destination_path)
            if not uploaded_path:
                raise RuntimeError("storage upload returned no path")

            response = (
                supabase_utils.supabase.table(config.SUPABASE_CUSTOMIZED_RESUMES_TABLE_NAME)
                .update(
                    {
                        "resume_link": uploaded_path,
                        "summary": resume_data.summary,
                        "certifications": [
                            certification.model_dump(exclude_none=True)
                            for certification in resume_data.certifications
                        ],
                    }
                )
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
    if failed:
        logging.warning(
            "Completed with %s failed record(s). Successfully updated records are already patched.",
            failed,
        )
    return 0 if updated else 1


if __name__ == "__main__":
    raise SystemExit(main())
