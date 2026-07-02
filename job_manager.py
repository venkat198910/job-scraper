import asyncio
import httpx
import random
import time
from datetime import datetime, timedelta, timezone
import logging

# Import shared modules
import config
import app_settings
import user_agents
from supabase_utils import supabase, _normalize_supabase_timestamp # Use the initialized Supabase client

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Helper Functions ---

def get_utc_now() -> datetime:
    """Returns the current time in UTC."""
    return datetime.now(timezone.utc)

def get_past_date(days: int) -> datetime:
    """Returns the datetime object for a specific number of days ago in UTC."""
    return get_utc_now() - timedelta(days=days)

def _parse_job_timestamp(value) -> datetime | None:
    normalized = _normalize_supabase_timestamp(value)
    if not normalized:
        return None

    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        logging.warning("Unable to parse normalized job timestamp: %r", normalized)
        return None

async def _check_single_linkedin_job_active(job_id: str, client: httpx.AsyncClient) -> bool | None:
    """
    Checks if a single LinkedIn job is still active.
    Returns:
        True if the job appears inactive (404, redirect, specific text).
        False if the job appears active.
        None if the check failed after retries.
    """
    job_detail_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    retries = 0
    inactive_keywords = ["this job is no longer available", "job is closed", "No longer accepting applications"] # Add more if needed
    active_check_max_retries = app_settings.get_advanced_int("activeCheckMaxRetries")


    while retries <= active_check_max_retries:
        try:
            sleep_time = random.uniform(5.0, 15.0)
            logging.info(f"Waiting for {sleep_time:.2f} seconds before next request...")
            time.sleep(sleep_time)

            # Rotate user agent and proxy for each attempt
            user_agent = random.choice(user_agents.USER_AGENTS)
            headers = {'User-Agent': user_agent}

            logging.debug(f"Checking job {job_id} (Attempt {retries+1}/{active_check_max_retries+1}) URL: {job_detail_url} with UA: {user_agent}")

            response = await client.get(
                job_detail_url,
                headers=headers,
                timeout=app_settings.get_advanced_int("activeCheckTimeout"),
                follow_redirects=True # Allow redirects to check final destination
            )

            # Check for 404 specifically
            if response.status_code == 404:
                logging.info(f"Job {job_id} returned 404. Marking as inactive.")
                return True

            # Check for other non-successful status codes (could indicate removal, private, etc.)
            # Allow redirects (3xx) as httpx handles them by default with follow_redirects=True
            if response.status_code >= 400:
                 logging.warning(f"Job {job_id} check failed with status {response.status_code}. Assuming active for now.")
                 # Decide if other errors mean inactive. For now, only 404 is definitive.
                 # Could return True here for stricter checking.
                 return False # Or None if we want to retry later

            # Check content for inactive keywords
            response_text_lower = response.text.lower()
            for keyword in inactive_keywords:
                if keyword in response_text_lower:
                    logging.info(f"Job {job_id} contains inactive keyword '{keyword}'. Marking as inactive.")
                    return True

            # If status is OK and no inactive keywords found
            logging.debug(f"Job {job_id} appears active (Status: {response.status_code}).")
            return False

        except httpx.TimeoutException:
            logging.warning(f"Timeout checking job {job_id} (Attempt {retries+1}).")
        except httpx.RequestError as e:
            logging.warning(f"Request error checking job {job_id} (Attempt {retries+1}): {e}")
        except Exception as e:
            logging.error(f"Unexpected error checking job {job_id} (Attempt {retries+1}): {e}")

        retries += 1
        if retries <= active_check_max_retries:
            wait_time = app_settings.get_advanced_int("activeCheckRetryDelay") + random.uniform(0, 5)
            logging.info(f"Retrying job {job_id} check after {wait_time:.2f} seconds...")
            await asyncio.sleep(wait_time)

    logging.error(f"Failed to check job {job_id} activity after {active_check_max_retries + 1} attempts.")
    return None # Failed to determine status

# --- Main Management Functions ---

async def mark_expired_jobs():
    """Marks old jobs (not applied/interviewing) as expired."""
    logging.info("--- Starting Task: Mark Expired Jobs ---")
    job_expiry_days = app_settings.get_advanced_int("jobExpiryDays")
    expiry_date = get_past_date(job_expiry_days)
    excluded_statuses = {'applied', 'offer', 'offered', 'interviewing'} # Statuses that mean "don't expire"
    logging.info(f"Expiring active jobs posted/scraped before {expiry_date.isoformat()} ({job_expiry_days} day threshold).")

    try:
        # Use posted_at first so old company career postings do not remain active
        # just because they were scraped recently. Fall back to scraped_at when
        # the source does not publish a posting date.
        response = supabase.table(config.SUPABASE_TABLE_NAME)\
            .select("job_id, status, posted_at, scraped_at")\
            .eq("is_active", True)\
            .execute()

        if response.data:
            job_ids_to_expire = []
            protected_count = 0
            missing_date_count = 0

            for job in response.data:
                if (job.get('status') or '').lower() in excluded_statuses:
                    protected_count += 1
                    continue

                reference_date = _parse_job_timestamp(job.get("posted_at")) or _parse_job_timestamp(job.get("scraped_at"))
                if not reference_date:
                    missing_date_count += 1
                    continue

                if reference_date < expiry_date:
                    job_ids_to_expire.append(job['job_id'])

            if protected_count:
                logging.info(f"Skipped {protected_count} active jobs with protected statuses: {sorted(excluded_statuses)}.")
            if missing_date_count:
                logging.info(f"Skipped {missing_date_count} active jobs without posted_at or scraped_at timestamps.")
            logging.info(f"Found {len(job_ids_to_expire)} jobs older than {job_expiry_days} days to mark as expired.")

            if job_ids_to_expire:
                # Update in batches if necessary, though supabase-py might handle large lists
                # For simplicity, updating all at once here. Consider batching for >1000s of IDs.
                update_response = supabase.table(config.SUPABASE_TABLE_NAME)\
                    .update({"job_state": "expired", "is_active": False})\
                    .in_("job_id", job_ids_to_expire)\
                    .execute()

                # Check response structure - may vary slightly
                if hasattr(update_response, 'data') and update_response.data:
                     updated_count = len(update_response.data) # Supabase often returns the updated rows
                     logging.info(f"Successfully marked {updated_count} jobs as expired.")
                elif hasattr(update_response, 'count') and update_response.count is not None:
                     logging.info(f"Successfully marked {update_response.count} jobs as expired (based on count).")
                else:
                     # Log raw response if structure is unexpected
                     logging.warning(f"Mark expired jobs update executed. Response: {update_response}")

        else:
            logging.info("No jobs found meeting the criteria for expiration.")

    except Exception as e:
        logging.error(f"Error marking expired jobs: {e}")

    logging.info("--- Finished Task: Mark Expired Jobs ---")


async def check_linkedin_job_activity():
    """Checks if active jobs are still available on LinkedIn."""
    logging.info("--- Starting Task: Check Job Activity ---")
    job_check_days = app_settings.get_advanced_int("jobCheckDays")
    job_check_limit = app_settings.get_advanced_int("jobCheckLimit")
    check_older_than_date = get_past_date(job_check_days)
    check_older_than_date_str = check_older_than_date.isoformat()
    now_str = get_utc_now().isoformat()

    jobs_to_check = []
    try:
        # Query for jobs needing a check: active AND older than N days
        # Order by last_checked ASC to prioritize oldest checks
        # Limit the number of checks per run
        excluded_statuses = {'applied', 'offer', 'offered', 'interviewing'} # Statuses that mean "don't expire"
        query = supabase.table(config.SUPABASE_TABLE_NAME)\
            .select("job_id, last_checked, status")\
            .eq("is_active", True)\
            .eq("provider", "linkedin")\
            .lt("last_checked", check_older_than_date_str)\
            .order("last_checked", desc=False)\
            .limit(job_check_limit)

        response = query.execute()

        if response.data:
            jobs_to_check = [
                job for job in response.data
                if (job.get('status') or '').lower() not in excluded_statuses
            ]
            logging.info(f"Found {len(jobs_to_check)} active jobs to check (limit: {job_check_limit}).")
        else:
            logging.info("No active jobs need checking currently.")
            return # Nothing to do

    except Exception as e:
        logging.error(f"Error fetching jobs to check: {e}")
        return # Cannot proceed

    # Use httpx.AsyncClient for connection pooling and efficiency
    async with httpx.AsyncClient() as client:
        tasks = []
        for job in jobs_to_check:
            tasks.append(_check_single_linkedin_job_active(job['job_id'], client))
        results = await asyncio.gather(*tasks, return_exceptions=True)

    inactive_job_ids = []
    active_checked_job_ids = []
    failed_check_job_ids = []

    for i, result in enumerate(results):
        job_id = jobs_to_check[i]['job_id']
        if isinstance(result, Exception):
            logging.error(f"Exception checking job {job_id}: {result}")
            failed_check_job_ids.append(job_id)
        elif result is True: # Job confirmed inactive
            inactive_job_ids.append(job_id)
        elif result is False: # Job confirmed active
            active_checked_job_ids.append(job_id)
        elif result is None: # Check failed after retries
            failed_check_job_ids.append(job_id)

    logging.info(f"Activity Check Summary: Inactive={len(inactive_job_ids)}, Active={len(active_checked_job_ids)}, Failed={len(failed_check_job_ids)}")

    # Update Supabase
    try:
        if inactive_job_ids:
            update_inactive = supabase.table(config.SUPABASE_TABLE_NAME)\
                .update({"job_state": "removed", "is_active": False, "last_checked": now_str})\
                .in_("job_id", inactive_job_ids)\
                .execute()
            # Add logging for update_inactive response count/data
            logging.info(f"Marked {len(inactive_job_ids)} jobs as removed. Response: {update_inactive}")


        if active_checked_job_ids:
            update_active = supabase.table(config.SUPABASE_TABLE_NAME)\
                .update({"last_checked": now_str})\
                .in_("job_id", active_checked_job_ids)\
                .execute()
            # Add logging for update_active response count/data
            logging.info(f"Updated last_checked for {len(active_checked_job_ids)} active jobs.")

    except Exception as e:
        logging.error(f"Error updating job statuses after activity check: {e}")

    logging.info("--- Finished Task: Check Job Activity ---")


async def delete_old_inactive_jobs():
    """Permanently deletes very old inactive jobs."""
    logging.info("--- Starting Task: Delete Old Inactive Jobs ---")
    job_deletion_days = app_settings.get_advanced_int("jobDeletionDays")
    delete_older_than_date = get_past_date(job_deletion_days)
    delete_older_than_date_str = delete_older_than_date.isoformat()
    inactive_states = ['expired', 'removed']

    try:
        # Select jobs to delete
        # No need to select data, just filter and delete
        delete_response = supabase.table(config.SUPABASE_TABLE_NAME)\
            .delete()\
            .eq("is_active", False)\
            .in_("job_state", inactive_states)\
            .lt("scraped_at", delete_older_than_date_str)\
            .execute()

        # Check response structure for delete count
        deleted_count = 0
        if hasattr(delete_response, 'data') and delete_response.data:
             deleted_count = len(delete_response.data) # Delete often returns the deleted rows
        elif hasattr(delete_response, 'count') and delete_response.count is not None:
             deleted_count = delete_response.count

        if deleted_count > 0:
            logging.info(f"Successfully deleted {deleted_count} inactive jobs older than {job_deletion_days} days.")
        else:
            logging.info("No old inactive jobs found to delete.")
            # Log raw response if structure is unexpected but count is 0
            logging.debug(f"Delete response when no jobs matched: {delete_response}")


    except Exception as e:
        logging.error(f"Error deleting old inactive jobs: {e}")

    logging.info("--- Finished Task: Delete Old Inactive Jobs ---")


# --- Main Execution ---
async def main():
    """Runs the job management tasks."""
    logging.info("Starting Job Management Script...")
    start_time = time.time()

    await mark_expired_jobs()
    await check_linkedin_job_activity()
    await delete_old_inactive_jobs()

    end_time = time.time()
    logging.info(f"Job Management Script finished in {end_time - start_time:.2f} seconds.")

if __name__ == "__main__":
    asyncio.run(main())
