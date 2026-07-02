import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import time 
import random 
import logging
import config
import job_alerts
import user_agents
import supabase_utils
from markdownify import markdownify as md
import json
import re
from urllib.parse import urlencode, urljoin
import app_settings

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Convert HTML description to Markdown
def convert_html_to_markdown(html: str) -> str | None:
    """
    Convert HTML to clean Markdown using BeautifulSoup (to strip unwanted tags)
    and markdownify (to convert the cleaned HTML to Markdown).
    No LLM API calls are made — this is entirely local.
    """
    if not html or not html.strip():
        logging.info("Received empty HTML for Markdown conversion, returning empty string.")
        return ""

    try:
        # Clean the HTML: remove scripts, styles, nav, and other non-content tags
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'iframe', 'noscript']):
            tag.decompose()

        cleaned_html = str(soup)

        # Convert cleaned HTML to Markdown
        markdown_text = md(
            cleaned_html,
            heading_style="ATX",
            bullets="-",
            strip=['img'],
        )

        # Clean up excessive blank lines
        lines = markdown_text.splitlines()
        cleaned_lines = []
        prev_blank = False
        for line in lines:
            if not line.strip():
                if not prev_blank:
                    cleaned_lines.append('')
                prev_blank = True
            else:
                cleaned_lines.append(line)
                prev_blank = False
        markdown_text = '\n'.join(cleaned_lines).strip()

        logging.info("Successfully converted HTML to Markdown.")
        return markdown_text if markdown_text else ""
    except Exception as e:
        logging.error(f"Error during HTML to Markdown conversion: {e}")
        return None

def _get_linkedin_experience_levels_param() -> str | None:
    """Return LinkedIn f_E filter values as a comma-separated string."""
    experience_levels = getattr(config, "LINKEDIN_EXPERIENCE_LEVELS", None)
    if not experience_levels:
        return None

    return ",".join(str(level).strip() for level in experience_levels if str(level).strip())

def _linkedin_job_matches_experience_range(job_details: dict) -> bool:
    """Filter jobs to descriptions that clearly request the configured experience range."""
    min_years, max_years, require_match = app_settings.get_experience_range()

    if min_years is None or max_years is None:
        return True

    description = job_details.get("description") or ""
    title = job_details.get("job_title") or ""
    level = job_details.get("level") or ""
    haystack = f"{title}\n{level}\n{description}".lower()
    haystack = haystack.replace("–", "-").replace("—", "-")

    ranges = []
    for match in re.finditer(r"\b(\d{1,2})\s*(?:\+?\s*-\s*|to\s+)(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", haystack):
        low = int(match.group(1))
        high = int(match.group(2))
        if low > high:
            low, high = high, low
        ranges.append((low, high))

    for match in re.finditer(r"\b(?:minimum|min\.?|at least|over|more than)\s+(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", haystack):
        years = int(match.group(1))
        ranges.append((years, years))

    for match in re.finditer(r"\b(\d{1,2})\s*\+\s*(?:years?|yrs?)\b", haystack):
        years = int(match.group(1))
        ranges.append((years, years))

    if not ranges:
        # Avoid false positives from random numbers. When strict mode is enabled,
        # only keep jobs where the description states the required experience.
        return not require_match

    return any(min_years <= low <= max_years and high <= max_years for low, high in ranges)

def _is_uae_location(*values: str | None) -> bool:
    """Return true when a configured/search/result location is in the UAE."""
    haystack = " ".join(str(value or "").lower() for value in values)
    return any(
        marker in haystack
        for marker in (
            "united arab emirates",
            "uae",
            "dubai",
            "abu dhabi",
            "sharjah",
            "ajman",
            "ras al khaimah",
            "fujairah",
            "umm al quwain",
        )
    )

def _linkedin_uae_job_has_sponsorship(job_details: dict) -> bool:
    """Keep UAE jobs only when sponsorship or visa support is explicitly offered."""
    if not getattr(config, "LINKEDIN_UAE_REQUIRE_SPONSORSHIP", True):
        return True

    description = job_details.get("description") or ""
    title = job_details.get("job_title") or ""
    location = job_details.get("location") or ""
    haystack = f"{title}\n{location}\n{description}".lower()
    haystack = haystack.replace("–", "-").replace("—", "-")

    negative_patterns = (
        r"\b(no|not|without)\s+(visa\s+)?sponsorship\b",
        r"\b(does\s+not|do\s+not|cannot|can't|unable\s+to)\s+(provide|offer|sponsor)",
        r"\bmust\s+(already\s+)?(be\s+)?(authorized|eligible)\s+to\s+work\b",
        r"\bexisting\s+(uae\s+)?work\s+(authorization|visa)\s+required\b",
    )
    if any(re.search(pattern, haystack) for pattern in negative_patterns):
        return False

    keywords = getattr(config, "LINKEDIN_UAE_SPONSORSHIP_KEYWORDS", [])
    return any(str(keyword).lower() in haystack for keyword in keywords)

def _parse_int(value: str) -> int | None:
    try:
        return int(value.replace(",", "").strip())
    except (AttributeError, ValueError):
        return None

def _extract_linkedin_applicant_count(soup: BeautifulSoup) -> int | None:
    """Extract the visible LinkedIn applicant count when the guest page exposes it."""
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)

    applicant_match = re.search(
        r"\b(\d[\d,]*)\s+applicants?\b",
        text,
        flags=re.IGNORECASE,
    )
    if applicant_match:
        return _parse_int(applicant_match.group(1))

    return None

def _linkedin_job_exceeds_applicant_limit(job_details: dict) -> bool:
    max_applicants = int(getattr(config, "LINKEDIN_MAX_APPLICANTS", 0) or 0)
    if max_applicants <= 0:
        return False

    applicant_count = job_details.get("applicant_count")
    if applicant_count is None:
        return False

    try:
        return int(applicant_count) > max_applicants
    except (TypeError, ValueError):
        return False

def _job_matches_excluded_title_keywords(job_details: dict) -> bool:
    """Return True when a broad search result is clearly outside target roles."""
    excluded_keywords = getattr(config, "EXCLUDED_JOB_TITLE_KEYWORDS", [])
    if not excluded_keywords:
        return False

    title = (job_details.get("job_title") or "").lower()
    if not title.strip():
        return False

    return any(keyword.lower() in title for keyword in excluded_keywords)

def _get_careers_future_job_company_name(job_item: dict) -> str | None:
    """Helper to extract company name, preferring hiringCompany."""
    if not isinstance(job_item, dict):
        return None
    
    hiring_company = job_item.get('hiringCompany')
    if isinstance(hiring_company, dict) and hiring_company.get('name'):
        return hiring_company['name']
    
    posted_company = job_item.get('postedCompany')
    if isinstance(posted_company, dict) and posted_company.get('name'):
        return posted_company['name']
        
    return None

# --- LinkedIn Scraping Logic ---
def _parse_linkedin_relative_posted_at(text: str, now: datetime | None = None) -> str | None:
    """Convert LinkedIn card text such as '4 hours ago' into a UTC timestamp."""
    if not text:
        return None

    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    if "just now" in normalized:
        return (now or datetime.now(timezone.utc)).isoformat()

    match = re.search(
        r"\b(\d+)\s+(minute|minutes|min|mins|hour|hours|hr|hrs|day|days|week|weeks|month|months)\s+ago\b",
        normalized,
    )
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2)
    if unit in {"minute", "minutes", "min", "mins"}:
        delta = timedelta(minutes=amount)
    elif unit in {"hour", "hours", "hr", "hrs"}:
        delta = timedelta(hours=amount)
    elif unit in {"day", "days"}:
        delta = timedelta(days=amount)
    elif unit in {"week", "weeks"}:
        delta = timedelta(weeks=amount)
    else:
        delta = timedelta(days=amount * 30)

    return ((now or datetime.now(timezone.utc)) - delta).isoformat()


def _extract_linkedin_card_posted_at(job_element) -> str | None:
    for time_tag in job_element.find_all("time"):
        text_posted_at = _parse_linkedin_relative_posted_at(time_tag.get_text(" ", strip=True))
        if text_posted_at:
            return text_posted_at

        datetime_value = time_tag.get("datetime")
        if datetime_value:
            try:
                parsed = datetime.fromisoformat(datetime_value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc).isoformat()
            except ValueError:
                pass

    return _parse_linkedin_relative_posted_at(job_element.get_text(" ", strip=True))


def _fetch_linkedin_job_ids(search_query: str, location: str) -> list:
    """Fetches job IDs from LinkedIn search results pages with delays, rotating user agents, and retries."""

    job_ids_list = []
    job_metadata_by_id = {}
    start = 0
    max_start = app_settings.get_advanced_int("linkedinMaxStart")


    logging.info(f"--- Starting Phase 1: Scraping Job IDs (Max Start: {max_start}) ---")
    while start <= max_start:
        query_params = {
            "keywords": search_query,
            "location": location,
            "f_TPR": app_settings.get_linkedin_posting_date_filter(),
            "f_JT": app_settings.get_linkedin_job_type_param(),
            "start": start,
        }
        work_type = app_settings.get_linkedin_work_type_param()
        if work_type:
            query_params["f_WT"] = work_type
        if app_settings.is_easy_apply_only():
            query_params["f_AL"] = "true"
        experience_levels = _get_linkedin_experience_levels_param()
        if experience_levels:
            query_params["f_E"] = experience_levels
        geo_id = getattr(config, "LINKEDIN_GEO_IDS", {}).get(location)
        if geo_id:
            query_params["geoId"] = geo_id
        target_url = (
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
            + urlencode(query_params)
        )

        if start > 0:
            sleep_time = random.uniform(5.0, 15.0)
            logging.info(f"Waiting for {sleep_time:.2f} seconds before next request...")
            time.sleep(sleep_time)

        user_agent = random.choice(user_agents.USER_AGENTS)
        headers = {'User-Agent': user_agent}
    
        logging.info(f"Using User-Agent: {user_agent}")

    
        logging.info(f"Scraping URL: {target_url}")

        res = None 
        retries = 0
        max_retries = app_settings.get_advanced_int("maxRetries")
        while retries <= max_retries:
            try:
                res = requests.get(target_url, headers=headers, timeout=app_settings.get_advanced_int("requestTimeout"))
                res.raise_for_status()
                break
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429 and retries < max_retries:
                    retries += 1
                    wait_time = app_settings.get_advanced_int("retryDelaySeconds") + random.uniform(0, 5) 
                    
                    logging.warning(f"Error 429: Too Many Requests. Retrying attempt {retries}/{max_retries} after {wait_time:.2f} seconds...")
                    time.sleep(wait_time)

                    user_agent = random.choice(user_agents.USER_AGENTS)
                    headers = {'User-Agent': user_agent}
                
                    logging.info(f"Retrying with new User-Agent: {user_agent}")
                    continue
                else:
                    
                    logging.error(f"HTTP Error fetching search results page: {e}")
                    res = None 
                    break
            except requests.exceptions.RequestException as e:
                
                logging.error(f"Request Exception fetching search results page: {e}")
                res = None
                break

        
        if res is None:
            logging.error(f"Failed to fetch {target_url} after {retries} retries. Stopping pagination for this query.")
            break 

        if not res.text:
            
             logging.info(f"Received empty response text at start={start}, stopping.")
             break

        soup = BeautifulSoup(res.text, 'html.parser')
        all_jobs_on_this_page = soup.find_all('li')

        if not all_jobs_on_this_page:
            
             logging.info(f"No job listings ('li' elements) found on page at start={start}, stopping.")
             break

    
        logging.info(f"Found {len(all_jobs_on_this_page)} potential job elements on this page.")

        jobs_found_this_iteration = 0
        for job_element in all_jobs_on_this_page:
            base_card = job_element.find("div", {"class": "base-card"})
            job_urn = base_card.get('data-entity-urn') if base_card else None
            if job_urn and 'jobPosting:' in job_urn:
                try:
                    jobid = job_urn.split(":")[3]
                    if jobid not in job_ids_list:
                         job_ids_list.append(jobid)
                         posted_at = _extract_linkedin_card_posted_at(job_element)
                         if posted_at:
                             job_metadata_by_id[jobid] = {"posted_at": posted_at}
                         jobs_found_this_iteration += 1
                except IndexError:
                    
                    logging.warning(f"Could not parse job ID from URN: {job_urn}")
                    pass

    
        logging.info(f"Added {jobs_found_this_iteration} unique job IDs from this page.")

        if jobs_found_this_iteration == 0 and len(all_jobs_on_this_page) > 0:
        
            logging.info("Found list items but no new job IDs extracted, potentially end of relevant results or parsing issue.")
            break

        start += 10


    logging.info(f"--- Finished Phase 1: Found {len(job_ids_list)} unique job IDs during scraping ---")
    return job_ids_list, job_metadata_by_id

def _fetch_linkedin_job_details(job_id: str) -> dict | None:
    """Fetches detailed information for a single job ID with delays, rotating user agents, and retries."""

    job_detail_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

    logging.info(f"Preparing to fetch details for job ID: {job_id}")

    sleep_time = random.uniform(3.0, 10.0)

    logging.info(f"Waiting for {sleep_time:.2f} seconds before fetching details...")
    time.sleep(sleep_time)

    user_agent = random.choice(user_agents.USER_AGENTS)
    headers = {'User-Agent': user_agent}

    logging.info(f"Using User-Agent for details: {user_agent}")


    logging.info(f"Fetching details from: {job_detail_url}")

    resp = None 
    retries = 0
    max_retries = app_settings.get_advanced_int("maxRetries")
    while retries <= max_retries:
        try:
            resp = requests.get(job_detail_url, headers=headers, timeout=app_settings.get_advanced_int("requestTimeout"))
            resp.raise_for_status()
            break
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429 and retries < max_retries:
                retries += 1
                wait_time = app_settings.get_advanced_int("retryDelaySeconds") + random.uniform(0, 5) 
                
                logging.warning(f"Error 429 for job ID {job_id}. Retrying attempt {retries}/{max_retries} after {wait_time:.2f} seconds...")
                time.sleep(wait_time)
                user_agent = random.choice(user_agents.USER_AGENTS)
                headers = {'User-Agent': user_agent}
            
                logging.info(f"Retrying job {job_id} with new User-Agent: {user_agent}")
                continue
            else:
                
                logging.error(f"HTTP Error fetching details for job ID {job_id}: {e}")
                return None
        except requests.exceptions.RequestException as e:
            
            logging.error(f"Request Exception fetching details for job ID {job_id}: {e}")
            return None 

    
    if resp is None:
         logging.error(f"Failed to fetch details for job ID {job_id} after {retries} retries (unexpected state).")
         return None

    try:
        soup = BeautifulSoup(resp.text, 'html.parser')
        job_details = {"job_id": job_id}

        # --- Extract Company ---
        try:
            company_img = soup.find("div",{"class":"top-card-layout__card"}).find("a").find("img")
            if company_img:
                job_details["company"] = company_img.get('alt').strip()
            if not job_details.get("company"):
                 company_link = soup.find("a", {"class": "topcard__org-name-link"})
                 if company_link:
                      job_details["company"] = company_link.text.strip()
                 else:
                      sub_title_span = soup.find("span", {"class": "topcard__flavor"})
                      if sub_title_span:
                           job_details["company"] = sub_title_span.text.strip()

            if not job_details.get("company"):
                 job_details["company"] = None
                 print(f"Warning: Could not extract company for job ID {job_id}")
        except Exception as e:
            print(f"Error extracting company for job ID {job_id}: {e}")
            job_details["company"] = None

        # --- Extract Job Title ---
        try:
            title_link = soup.find("div",{"class":"top-card-layout__entity-info"}).find("a")
            job_details["job_title"] = title_link.text.strip() if title_link else None
            if not job_details["job_title"]:
                 title_h1 = soup.find("h1", {"class": "top-card-layout__title"})
                 if title_h1:
                      job_details["job_title"] = title_h1.text.strip()
        except Exception as e: 
            print(f"Error extracting job title for job ID {job_id}: {e}")
            job_details["job_title"] = None

        # --- Extract Seniority Level ---
        try:
            # Find all criteria items
            criteria_items = soup.find("ul",{"class":"description__job-criteria-list"}).find_all("li")
            job_details["level"] = None 
            for item in criteria_items:
                header = item.find("h3", {"class": "description__job-criteria-subheader"})
                if header and "Seniority level" in header.text:
                    level_text = item.find("span", {"class": "description__job-criteria-text"})
                    if level_text:
                        job_details["level"] = level_text.text.strip()
                        break 
        except Exception as e: 
            print(f"Error extracting seniority level for job ID {job_id}: {e}")
            job_details["level"] = None

        # --- Extract Location ---
        try:
           
            location_span = soup.find("span", {"class": "topcard__flavor topcard__flavor--bullet"})
            if location_span:
                job_details["location"] = location_span.text.strip()
            else:
                
                subtitle_div = soup.find("div", {"class": "topcard__flavor-row"})
                if subtitle_div:
                    location_span_fallback = subtitle_div.find("span", {"class": "topcard__flavor"})
                    if location_span_fallback:
                         job_details["location"] = location_span_fallback.text.strip()

            if not job_details.get("location"): 
                 job_details["location"] = None
                 print(f"Warning: Could not extract location for job ID {job_id}")
        except Exception as e:
            print(f"Error extracting location for job ID {job_id}: {e}")
            job_details["location"] = None

        # --- Extract Applicant Count ---
        try:
            job_details["applicant_count"] = _extract_linkedin_applicant_count(soup)
        except Exception as e:
            logging.warning("Could not extract applicant count for job ID %s: %s", job_id, e)
            job_details["applicant_count"] = None

        # --- Extract Description ---
        description_html = "" 
        try:
            description_div = soup.find("div", {"class": "show-more-less-html__markup"})
            if description_div:
                description_html = str(description_div)
            else:
                logging.warning(f"Could not find description div for job ID {job_id}")
        except Exception as e:
                logging.error(f"Error extracting description HTML for job ID {job_id}: {e}")
                description_html = ""

        if description_html.strip():
            job_details["description"] = convert_html_to_markdown(description_html)
        else:
            job_details["description"] = None 
            logging.warning(f"Description HTML was empty for job ID {job_id}. Skipping conversion.") 

        # --- Set Provider ---
        job_details["provider"] = "linkedin"
        
        return job_details

    except Exception as e:
         
         logging.error(f"General Error processing details for job ID {job_id} after successful fetch: {e}")
         return None

def process_linkedin_query(search_query: str, location: str, limit: int = None) -> list:
    """
    Orchestrates scraping and detail fetching for a single query,
    filtering against existing jobs in Supabase BEFORE fetching details.
    Returns a list of new job details found.
    """

    scraped_result = _fetch_linkedin_job_ids(search_query, location)
    if isinstance(scraped_result, tuple):
        scraped_job_ids, scraped_job_metadata = scraped_result
    else:
        scraped_job_ids = scraped_result
        scraped_job_metadata = {}
    if not scraped_job_ids:
    
        logging.info("No job IDs found in Phase 1. Skipping detail fetching.")
        return []

    unique_linkedin_job_ids = list(set(scraped_job_ids))

    logging.info(f"Found {len(scraped_job_ids)} raw job IDs, {len(unique_linkedin_job_ids)} unique IDs after scraping.")


    logging.info("\n--- Starting Filtering Step: Checking against Supabase ---")
    job_ids_set, company_title_set = supabase_utils.get_existing_jobs_from_supabase()

    new_job_ids_to_process = [
        str(job_id) for job_id in unique_linkedin_job_ids 
        if str(job_id) not in job_ids_set
    ]


    logging.info(f"Found {len(unique_linkedin_job_ids)} unique scraped IDs.")

    logging.info(f"Found {len(job_ids_set)} existing IDs in Supabase.")

    logging.info(f"Identified {len(new_job_ids_to_process)} new job IDs to fetch details for.")

    if not new_job_ids_to_process:
    
        logging.info("No new job IDs to process after filtering.")
        return []

    if limit is not None and len(new_job_ids_to_process) > limit:
        logging.info(f"Truncating new_job_ids_to_process from {len(new_job_ids_to_process)} to {limit} to stay within source limit.")
        new_job_ids_to_process = new_job_ids_to_process[:limit]

    logging.info(f"\n--- Starting Phase 2: Fetching Job Details for {len(new_job_ids_to_process)} New IDs ---")
    detailed_new_jobs = []
    processed_count = 0

    ids_to_fetch = new_job_ids_to_process

    for job_id in ids_to_fetch:
        details = _fetch_linkedin_job_details(job_id)
        if details:
            if not details.get("posted_at"):
                details["posted_at"] = (scraped_job_metadata.get(str(job_id)) or {}).get("posted_at")
            description = details.get('description')
            if description and description.strip(): 
                if _job_matches_excluded_title_keywords(details):
                    logging.info(
                        "Skipping job ID %s because title '%s' matches excluded keywords.",
                        job_id,
                        details.get("job_title"),
                    )
                    continue
                if _linkedin_job_exceeds_applicant_limit(details):
                    logging.info(
                        "Skipping job ID %s because applicant count %s is above limit %s.",
                        job_id,
                        details.get("applicant_count"),
                        getattr(config, "LINKEDIN_MAX_APPLICANTS", 0),
                    )
                    continue
                if not _linkedin_job_matches_experience_range(details):
                    logging.info(
                        "Skipping job ID %s because requested experience is outside %s-%s years.",
                        job_id,
                        app_settings.get_experience_range()[0],
                        app_settings.get_experience_range()[1],
                    )
                    continue
                if 'job_id' in details and details['job_id'] is not None:
                    details.pop("applicant_count", None)
                    detailed_new_jobs.append(details)
                    processed_count += 1
                else:
                    
                    logging.warning(f"Fetched details for {job_id} but missing 'job_id' key. Skipping.")
            else:
                
                logging.warning(f"Skipping job ID {job_id} due to missing or empty description.") 
        else:
            
            logging.warning(f"Skipping job ID {job_id} as detail fetching failed or returned no data.") 


    logging.info(f"--- Finished Phase 2: Successfully fetched details for {processed_count} new job(s) ---")
    return detailed_new_jobs

def _fetch_careers_future_jobs(search_query: str) -> list:
    """
    Fetches job items from CareersFuture based on the provided search query.
    This involves:
    1. Getting skill suggestions based on the search query.
    2. Using these skill UUIDs to search for jobs.
    3. Handling pagination to retrieve all job results.
    4. Returning a list of all collected job item dictionaries.

    Args:
        search_query (str): The job title or keywords to search for.

    Returns:
        list: A list of job item dictionaries. Returns an empty list if an error occurs
              or if no jobs are found.
    """


    careers_future_suggestions_api_url = "https://api.mycareersfuture.gov.sg/v2/skills/suggestions"
    careers_future_search_api_base_url =  "https://api.mycareersfuture.gov.sg/v2/search"

    skillUuids = []

    # --- 1. Get Skill Suggestions ---
    skills_suggestions_payload = {'jobTitle': search_query}

    try:
        logging.info(f"Fetching skill suggestions for query: '{search_query}' from {careers_future_suggestions_api_url}")
        skills_suggestions_response = requests.post(
            careers_future_suggestions_api_url, 
            data=skills_suggestions_payload,
            timeout=app_settings.get_advanced_int("requestTimeout")
            )

        skills_suggestions_response.raise_for_status()
        skills_data = skills_suggestions_response.json()
        skills_list = skills_data.get('skills', [])
        skillUuids = [skill_dict['uuid'] for skill_dict in skills_list if 'uuid' in skill_dict]
        logging.info(f"Successfully retrieved {len(skillUuids)} skill UUIDs for '{search_query}'.")
        if not skillUuids:
            logging.warning(f"No skill UUIDs found for query '{search_query}'. Job search will proceed without specific skill filtering.")


    except requests.exceptions.HTTPError as http_err:
        status_code = http_err.response.status_code if http_err.response is not None else 'N/A'
        response_text = http_err.response.text if http_err.response is not None else 'N/A'
        logging.error(f"HTTP error during skill suggestions: {http_err} - Status: {status_code}")
        logging.debug(f"Skill suggestions error response content: {response_text[:500]}") 
        return []
    except requests.exceptions.RequestException as req_err: 
        logging.error(f"Request exception during skill suggestions: {req_err}")
        return []
    except json.JSONDecodeError:
        content_for_log = skills_suggestions_response.text if 'skills_suggestions_response' in locals() and skills_suggestions_response else "N/A"
        logging.error(f"Could not decode JSON response for skill suggestions. Content: {content_for_log[:500]}")
        return []

    # --- 2. Search for Jobs and Handle Pagination ---
    all_job_items = []
    total_api_calls_for_search = 0

    # Initial search URL with default limit and page
    current_search_url = f"{careers_future_search_api_base_url}?limit=100&page=0"
    search_payload = {
        'sessionId':"",
        'search': search_query,
        'categories':config.CAREERS_FUTURE_SEARCH_CATEGORIES,
        'employmentTypes': config.CAREERS_FUTURE_SEARCH_EMPLOYMENT_TYPES,
        'postingCompany' : [],
        'sortBy': ["new_posting_date"],
        'skillUuids': skillUuids,

    }

    try:
        while current_search_url:
            total_api_calls_for_search += 1
            logging.info(f"Job search API call {total_api_calls_for_search}: POST to {current_search_url}")
        
            search_response = requests.post(current_search_url, json=search_payload, timeout=app_settings.get_advanced_int("requestTimeout"))
            search_response.raise_for_status()
            search_results_data  = search_response.json()

            current_page_jobs = search_results_data.get('results', [])
            all_job_items.extend(current_page_jobs)

            logging.info(f"Retrieved {len(current_page_jobs)} job items from this page. Total items collected: {len(all_job_items)}.")

            # Log total results reported by API 
            if 'total' in search_results_data and total_api_calls_for_search == 1:
                logging.info(f"API reports total potential jobs matching criteria: {search_results_data['total']}")
            
            # Get the next page URL. The API provides a full URL.
            next_page_link_info = search_results_data.get("_links", {}).get("next", {})
            current_search_url = next_page_link_info.get("href") if next_page_link_info else None 

            if current_search_url:
                logging.debug(f"Next page URL for job search: {current_search_url}")
            else:
                logging.info("No more job pages to fetch.")

        logging.info(f"Completed job search. Total API calls made for search: {total_api_calls_for_search}.")
    
    except requests.exceptions.HTTPError as http_err:
        status_code = http_err.response.status_code if http_err.response is not None else 'N/A'
        response_text = http_err.response.text if http_err.response is not None else 'N/A'
        logging.error(f"HTTP error during job search: {http_err} - Status: {status_code}")
        logging.debug(f"Job search error response content: {response_text[:500]}")
    except requests.exceptions.RequestException as req_err:
        logging.error(f"Request exception during job search: {req_err}")
    except json.JSONDecodeError:
        content_for_log = search_response.text if 'search_response' in locals() and search_response else "N/A"
        logging.error(f"Could not decode JSON response during job search. Content: {content_for_log[:500]}")

    # --- 3. Return all collected job items ---
    if not all_job_items:
        logging.info(f"No job items were collected for query '{search_query}'.")
        return [] 

    logging.info(f"Returning {len(all_job_items)} total job items for query '{search_query}'.")
    return all_job_items

def _fetch_careers_future_job_details(job_id: str) -> dict | None:
    """
    Fetch job details from CareersFuture based on the provided job ID.

    Args:
        job_id (str): The UUID of the job to fetch details for.

    Returns:
        dict | None: A dictionary containing the job details if successful,
                      None otherwise.
    """
    if not job_id:
        logging.warning("Job ID is missing or empty. Cannot fetch details.")
        return None

    api_url = f"https://api.mycareersfuture.gov.sg/v2/jobs/{job_id}"
    
    logging.info(f"Attempting to fetch job details for ID: {job_id} from URL: {api_url}")

    try:
        response = requests.get(api_url, timeout=app_settings.get_advanced_int("requestTimeout")) 

        response.raise_for_status()

        job_data = response.json()
        logging.info(f"Successfully fetched and parsed job details for ID: {job_id}")

        raw_description_html = job_data.get('description', '')
        # Convert HTML description directly to Markdown (no LLM needed)
        markdown_description = None 
        if raw_description_html.strip(): 
            markdown_description = convert_html_to_markdown(raw_description_html)
        else:
            logging.warning(f"Raw description was empty for Careers Future job ID {job_id}. Skipping conversion.") 

        job_details = {
            'job_id': job_data.get('uuid'),
            'company': _get_careers_future_job_company_name(job_data),
            'job_title': job_data.get('title'),
            'location': 'Singapore',
            'level': job_data.get('positionLevels', [{'position': 'Not applicable'}])[0].get('position', 'Not applicable'),
            'provider': 'careers_future',
            'description': markdown_description, 
            'posted_at': job_data.get('metadata', {}).get('createdAt', ''),
        }

        return job_details

    except requests.exceptions.HTTPError as http_err:
        status_code = http_err.response.status_code if http_err.response is not None else 'N/A'
        response_text = http_err.response.text if http_err.response is not None else 'N/A'
        if status_code == 404:
            logging.warning(f"Job details not found (404) for ID: {job_id} at {api_url}.")
        else:
            logging.error(f"HTTP error occurred while fetching job details for ID '{job_id}': {http_err} - Status: {status_code}")
            logging.debug(f"Error response content: {response_text[:500]}") 
    except requests.exceptions.ConnectionError as conn_err:
        logging.error(f"Connection error occurred while fetching job details for ID '{job_id}': {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        logging.error(f"Timeout error occurred while fetching job details for ID '{job_id}': {timeout_err}")
    except requests.exceptions.RequestException as req_err: 
        logging.error(f"An error occurred during the request for job details for ID '{job_id}': {req_err}")
    except json.JSONDecodeError:
        content_for_log = response.text if 'response' in locals() and response else "N/A"
        logging.error(f"Failed to decode JSON response for job details for ID '{job_id}'. Content: {content_for_log[:500]}")
    
    return None # Return None in case of any error

def process_careers_future_query(search_query: str, limit: int = None) -> list:
    """
    Fetch jobs from CareersFuture and return them as a list of dictionaries.
    """
    # 1. Fetch all potential job items from CareersFuture search
    careers_future_jobs = _fetch_careers_future_jobs(search_query)
    if not careers_future_jobs:
        print("No job items found in Phase 1. Skipping detail fetching.")
        return []

    # 2. Fetch existing job identifiers from Supabase
    logging.info("Phase 2: Fetching existing job identifiers from Supabase...")
    try:
        job_ids_set_supabase, company_title_set_supabase = supabase_utils.get_existing_jobs_from_supabase()
        logging.info(f"Phase 2: Supabase returned {len(job_ids_set_supabase)} existing IDs and {len(company_title_set_supabase)} company/title pairs.")
    except Exception as e:
        logging.error(f"Failed to fetch existing jobs from Supabase: {e}")
        logging.warning("Proceeding without Supabase data; all fetched jobs will be considered new.")
        job_ids_set_supabase = set()
        company_title_set_supabase = set()

    # 3. Filter the fetched jobs
    logging.info("Phase 3: Filtering fetched jobs against Supabase data...")
    new_job_ids_to_process = []
    skipped_by_id_count = 0
    skipped_by_combo_count = 0

    for job_item in careers_future_jobs:
        if not isinstance(job_item, dict):
            logging.warning(f"Skipping invalid job item (not a dict): {str(job_item)[:100]}")
            continue

        job_uuid = str(job_item.get('uuid'))
        
        # Check 1: Does the UUID already exist in Supabase?
        if job_uuid and job_uuid in job_ids_set_supabase:
            logging.debug(f"Skipping job (ID exists in Supabase): UUID='{job_uuid}', Title='{job_item.get('title', 'N/A')}'")
            skipped_by_id_count += 1
            continue # Skip this job

        # Prepare for Check 2: Company & Title combination
        company_name = _get_careers_future_job_company_name(job_item)
        job_title = job_item.get('title')

        normalized_company = None
        normalized_title = None

        if company_name:
            normalized_company = company_name.strip().lower()
        if job_title:
            normalized_title = job_title.strip().lower()
        
        if normalized_company and normalized_title:
            company_title_key = (normalized_company, normalized_title)
            if company_title_key in company_title_set_supabase:
                logging.debug(f"Skipping job (Company/Title combo exists in Supabase): UUID='{job_uuid}', Company='{normalized_company}', Title='{normalized_title}'")
                skipped_by_combo_count +=1
                continue 
        elif job_uuid: 
            logging.debug(f"Job UUID='{job_uuid}' has no company/title for combo check. Will be added if ID is new.")
        else: 
             logging.warning(f"Job item has no UUID and insufficient company/title for matching: {str(job_item)[:100]}")


        new_job_ids_to_process.append(job_uuid) 

    # 4. Fetch details ONLY for the genuinely new job IDs
    if limit is not None and len(new_job_ids_to_process) > limit:
        logging.info(f"Truncating new_job_ids_to_process from {len(new_job_ids_to_process)} to {limit} to stay within source limit.")
        new_job_ids_to_process = new_job_ids_to_process[:limit]

    print(f"\n--- Phase 4: Fetching Job Details for {len(new_job_ids_to_process)} New Jobs ---")
    detailed_new_jobs = []
    processed_count = 0

    for job_id in new_job_ids_to_process:
        details = _fetch_careers_future_job_details(job_id)
        if details:
            # --- NEW: Check for description before adding ---
            description = details.get('description')
            if description and description.strip(): # Ensure it's not None or an empty/whitespace string
                if _job_matches_excluded_title_keywords(details):
                    logging.info(
                        "Skipping job ID %s because title '%s' matches excluded keywords.",
                        job_id,
                        details.get("job_title"),
                    )
                    continue
                if 'job_id' in details and details['job_id'] is not None:
                    detailed_new_jobs.append(details)
                    processed_count += 1
                else:
                    
                    logging.warning(f"Fetched details for {job_id} but missing 'job_id' key. Skipping.")
            else:
                
                logging.warning(f"Skipping job ID {job_id} due to missing or empty description.") 
        else:
            
            logging.warning(f"Skipping job ID {job_id} as detail fetching failed or returned no data.") 



    logging.info(f"--- Finished Phase 4: Successfully fetched details for {processed_count} new job(s) ---")
    return detailed_new_jobs

def _plain_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    return re.sub(r"\s+", " ", str(value)).strip()

def _job_matches_company_career_keywords(job_details: dict) -> bool:
    if _job_matches_excluded_title_keywords(job_details):
        return False

    title = (job_details.get("job_title") or "").lower()
    title_keywords = (
        getattr(config, "COMPANY_CAREER_TITLE_KEYWORDS", None)
        or getattr(config, "COMPANY_CAREER_ROLE_KEYWORDS", [])
    )
    return any(str(keyword).lower() in title for keyword in title_keywords)

def _job_matches_company_career_location(job_details: dict) -> bool:
    location = (job_details.get("location") or "").lower()
    if not location:
        return False

    keywords = getattr(config, "COMPANY_CAREER_LOCATION_KEYWORDS", [])
    return any(str(keyword).lower() in location for keyword in keywords)

def _parse_company_career_posted_at(value: object) -> datetime | None:
    normalized = supabase_utils._normalize_supabase_timestamp(value)
    if not normalized:
        return None

    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        logging.warning("Unable to parse normalized company career posted_at value: %r", normalized)
        return None

def _company_career_posted_recent_enough(job_details: dict) -> bool:
    posted_at = _parse_company_career_posted_at(job_details.get("posted_at"))
    if not posted_at:
        return True

    job_expiry_days = app_settings.get_advanced_int("jobExpiryDays")
    if job_expiry_days <= 0:
        return True

    cutoff = datetime.now(timezone.utc) - timedelta(days=job_expiry_days)
    if posted_at < cutoff:
        logging.info(
            "Skipping old company career job %s | %s posted_at=%s older than %s days.",
            job_details.get("company"),
            job_details.get("job_title"),
            posted_at.isoformat(),
            job_expiry_days,
        )
        return False

    return True

def _company_career_job_allowed(job_details: dict) -> bool:
    description = job_details.get("description")
    if not description or not description.strip():
        return False
    if not _company_career_posted_recent_enough(job_details):
        return False
    if not _job_matches_company_career_keywords(job_details):
        return False
    if not _job_matches_company_career_location(job_details):
        return False
    if not _linkedin_job_matches_experience_range(job_details):
        return False
    return True

def _fetch_json(url: str) -> dict | list | None:
    try:
        response = requests.get(url, timeout=app_settings.get_advanced_int("requestTimeout"))
        if response.status_code == 404:
            logging.info("Career endpoint not found: %s", url)
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        logging.warning("Career endpoint request failed for %s: %s", url, exc)
    except json.JSONDecodeError as exc:
        logging.warning("Career endpoint did not return JSON for %s: %s", url, exc)
    return None

def _random_user_agent() -> str:
    agents = getattr(user_agents, "USER_AGENTS", None) or getattr(user_agents, "user_agents", None) or []
    return random.choice(agents) if agents else "Mozilla/5.0"

def _post_json(url: str, payload: dict) -> dict | list | None:
    try:
        response = requests.post(
            url,
            json=payload,
            timeout=app_settings.get_advanced_int("requestTimeout"),
            headers={"User-Agent": _random_user_agent()},
        )
        if response.status_code == 404:
            logging.info("Career endpoint not found: %s", url)
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        logging.warning("Career endpoint request failed for %s: %s", url, exc)
    except json.JSONDecodeError as exc:
        logging.warning("Career endpoint did not return JSON for %s: %s", url, exc)
    return None

def _normalize_greenhouse_job(target: dict, job: dict) -> dict | None:
    job_id = job.get("id")
    if not job_id:
        return None

    description = convert_html_to_markdown(job.get("content") or "")
    offices = job.get("offices") if isinstance(job.get("offices"), list) else []
    location = (job.get("location") or {}).get("name") if isinstance(job.get("location"), dict) else ""
    if not location and offices:
        location = ", ".join(_plain_text(office.get("name")) for office in offices if isinstance(office, dict) and office.get("name"))

    return {
        "job_id": f"greenhouse-{target.get('slug')}-{job_id}",
        "company": target.get("name"),
        "job_title": _plain_text(job.get("title")),
        "location": _plain_text(location),
        "level": "",
        "provider": "company_careers_greenhouse",
        "description": description,
        "posted_at": job.get("updated_at") or "",
        "job_url": job.get("absolute_url"),
        "apply_url": job.get("absolute_url"),
        "career_url": target.get("career_url") or "",
    }

def _fetch_greenhouse_jobs(target: dict) -> list[dict]:
    slug = target.get("slug")
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    payload = _fetch_json(url)
    if not isinstance(payload, dict):
        return []
    return [
        job_details
        for job in payload.get("jobs", [])
        if isinstance(job, dict)
        for job_details in [_normalize_greenhouse_job(target, job)]
        if job_details
    ]

def _normalize_lever_job(target: dict, job: dict) -> dict | None:
    job_id = job.get("id")
    if not job_id:
        return None

    categories = job.get("categories") if isinstance(job.get("categories"), dict) else {}
    description = job.get("descriptionPlain") or convert_html_to_markdown(job.get("description") or "")
    lists = job.get("lists") if isinstance(job.get("lists"), list) else []
    list_text = "\n".join(
        f"{item.get('text', '')}\n" + "\n".join(item.get("content", []) or [])
        for item in lists
        if isinstance(item, dict)
    )
    if list_text.strip():
        description = f"{description}\n\n{list_text}".strip()

    return {
        "job_id": f"lever-{target.get('slug')}-{job_id}",
        "company": target.get("name"),
        "job_title": _plain_text(job.get("text")),
        "location": _plain_text(categories.get("location")),
        "level": _plain_text(categories.get("commitment")),
        "provider": "company_careers_lever",
        "description": description,
        "posted_at": job.get("createdAt") or "",
        "job_url": job.get("hostedUrl") or job.get("applyUrl"),
        "apply_url": job.get("hostedUrl") or job.get("applyUrl"),
        "career_url": target.get("career_url") or "",
    }

def _fetch_lever_jobs(target: dict) -> list[dict]:
    slug = target.get("slug")
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    payload = _fetch_json(url)
    if not isinstance(payload, list):
        return []
    return [
        job_details
        for job in payload
        if isinstance(job, dict)
        for job_details in [_normalize_lever_job(target, job)]
        if job_details
    ]

def _normalize_ashby_job(target: dict, job: dict) -> dict | None:
    job_id = job.get("id")
    if not job_id:
        return None

    location_value = job.get("location")
    if isinstance(location_value, dict):
        location = location_value.get("name")
    else:
        location = location_value

    description = convert_html_to_markdown(job.get("descriptionHtml") or job.get("description") or "")
    return {
        "job_id": f"ashby-{target.get('slug')}-{job_id}",
        "company": target.get("name"),
        "job_title": _plain_text(job.get("title")),
        "location": _plain_text(location),
        "level": _plain_text(job.get("employmentType")),
        "provider": "company_careers_ashby",
        "description": description,
        "posted_at": job.get("publishedAt") or "",
        "job_url": job.get("jobUrl") or job.get("applyUrl"),
        "apply_url": job.get("jobUrl") or job.get("applyUrl"),
        "career_url": target.get("career_url") or "",
    }

def _fetch_ashby_jobs(target: dict) -> list[dict]:
    slug = target.get("slug")
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    payload = _fetch_json(url)
    if not isinstance(payload, dict):
        return []
    jobs = payload.get("jobs") if isinstance(payload.get("jobs"), list) else []
    return [
        job_details
        for job in jobs
        if isinstance(job, dict)
        for job_details in [_normalize_ashby_job(target, job)]
        if job_details
    ]

def _smartrecruiters_location(job: dict) -> str:
    location = job.get("location") if isinstance(job.get("location"), dict) else {}
    parts = [
        location.get("city"),
        location.get("region"),
        location.get("country"),
    ]
    return ", ".join(_plain_text(part) for part in parts if _plain_text(part))

def _smartrecruiters_description(job: dict) -> str:
    job_ad = job.get("jobAd") if isinstance(job.get("jobAd"), dict) else {}
    sections = job_ad.get("sections") if isinstance(job_ad.get("sections"), dict) else {}
    texts = []
    for value in sections.values():
        if isinstance(value, dict):
            text = value.get("text") or value.get("title")
            if text:
                texts.append(str(text))
        elif isinstance(value, str):
            texts.append(value)
    return convert_html_to_markdown("\n".join(texts))

def _fetch_smartrecruiters_jobs(target: dict) -> list[dict]:
    slug = target.get("slug")
    per_term_limit = int(getattr(config, "COMPANY_CAREER_JOBS_PER_TERM", 10) or 10)
    list_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit={per_term_limit}"
    payload = _fetch_json(list_url)
    if not isinstance(payload, dict):
        return []

    jobs = []
    for summary in payload.get("content", []):
        if not isinstance(summary, dict) or not summary.get("id"):
            continue
        detail_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{summary['id']}"
        detail = _fetch_json(detail_url)
        job = detail if isinstance(detail, dict) else summary
        jobs.append(
            {
                "job_id": f"smartrecruiters-{slug}-{summary['id']}",
                "company": target.get("name"),
                "job_title": _plain_text(job.get("name") or summary.get("name")),
                "location": _smartrecruiters_location(job or summary),
                "level": _plain_text(job.get("experienceLevel", {}).get("label") if isinstance(job.get("experienceLevel"), dict) else ""),
                "provider": "company_careers_smartrecruiters",
                "description": _smartrecruiters_description(job),
                "posted_at": job.get("releasedDate") or summary.get("releasedDate") or "",
                "job_url": job.get("ref") or summary.get("ref"),
                "apply_url": job.get("applyUrl") or job.get("ref") or summary.get("ref"),
                "career_url": target.get("career_url") or "",
            }
        )
    return jobs

def _workday_job_url(target: dict, external_path: str) -> str:
    host = target.get("host")
    site = target.get("site")
    if not host or not external_path:
        return ""
    if external_path.startswith("http"):
        return external_path
    if site and external_path.startswith("/job/"):
        return f"https://{host}/{site}{external_path}"
    return f"https://{host}{external_path}"

def _normalize_workday_job(target: dict, summary: dict, detail: dict | None) -> dict | None:
    info = detail.get("jobPostingInfo") if isinstance(detail, dict) and isinstance(detail.get("jobPostingInfo"), dict) else {}
    external_path = (
        info.get("externalUrl")
        or info.get("externalPath")
        or summary.get("externalPath")
        or summary.get("externalUrl")
        or ""
    )
    job_id = summary.get("bulletFields", [None])[0] if isinstance(summary.get("bulletFields"), list) and summary.get("bulletFields") else None
    job_id = job_id or summary.get("title") or external_path
    if not job_id:
        return None

    description = (
        info.get("jobDescription")
        or info.get("jobDescriptionText")
        or summary.get("description")
        or ""
    )
    if "<" in str(description):
        description = convert_html_to_markdown(description)

    return {
        "job_id": f"workday-{target.get('tenant')}-{target.get('site')}-{_plain_text(job_id).lower().replace(' ', '-')}",
        "company": target.get("name"),
        "job_title": _plain_text(info.get("title") or summary.get("title")),
        "location": _plain_text(info.get("location") or summary.get("locationsText")),
        "level": _plain_text(info.get("timeType") or summary.get("timeType")),
        "provider": "company_careers_workday",
        "description": description,
        "posted_at": info.get("startDate") or summary.get("postedOn") or "",
        "job_url": _workday_job_url(target, external_path),
        "apply_url": _workday_job_url(target, external_path),
        "career_url": target.get("career_url") or "",
    }

def _fetch_workday_jobs(target: dict) -> list[dict]:
    host = target.get("host")
    tenant = target.get("tenant")
    site = target.get("site")
    if not host or not tenant or not site:
        return []

    list_url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    jobs: list[dict] = []
    seen_ids: set[str] = set()
    search_terms = target.get("search_terms") or getattr(config, "COMPANY_CAREER_ROLE_KEYWORDS", [])
    applied_facets = target.get("facets") if isinstance(target.get("facets"), dict) else {}
    per_term_limit = int(target.get("limit") or getattr(config, "COMPANY_CAREER_JOBS_PER_TERM", 10) or 10)
    for search_text in search_terms:
        payload = _post_json(
            list_url,
            {
                "appliedFacets": applied_facets,
                "limit": per_term_limit,
                "offset": 0,
                "searchText": str(search_text),
            },
        )
        if not isinstance(payload, dict):
            continue
        for summary in payload.get("jobPostings", []):
            if not isinstance(summary, dict):
                continue
            external_path = summary.get("externalPath") or ""
            dedupe_key = external_path or summary.get("title")
            if not dedupe_key or dedupe_key in seen_ids:
                continue
            seen_ids.add(str(dedupe_key))

            detail = None
            if external_path:
                detail_url = f"https://{host}/wday/cxs/{tenant}/{site}{external_path}"
                detail_payload = _fetch_json(detail_url)
                detail = detail_payload if isinstance(detail_payload, dict) else None

            job_details = _normalize_workday_job(target, summary, detail)
            if job_details:
                jobs.append(job_details)
    return jobs

def _normalize_jibe_job(target: dict, card) -> dict | None:
    link = card.select_one('a[href*="/job/"]')
    if not link:
        return None
    href = link.get("href") or ""
    job_id = link.get("data-job-id") or href.rstrip("/").split("/")[-1]
    if not job_id:
        return None

    base_url = target.get("base_url")
    job_url = urljoin(base_url, href)
    detail = _fetch_jibe_job_detail(job_url)
    return {
        "job_id": f"jibe-{target.get('name', '').lower().replace(' ', '-')}-{job_id}",
        "company": target.get("name"),
        "job_title": _plain_text(link.get_text(" ", strip=True)),
        "location": _plain_text((card.select_one(".location") or {}).get_text(" ", strip=True) if card.select_one(".location") else ""),
        "level": _plain_text((card.select_one(".category") or {}).get_text(" ", strip=True) if card.select_one(".category") else ""),
        "provider": "company_careers_jibe",
        "description": detail.get("description") or _plain_text(card.get_text(" ", strip=True)),
        "posted_at": detail.get("posted_at") or "",
        "job_url": job_url,
        "apply_url": job_url,
        "career_url": target.get("career_url") or target.get("base_url") or "",
    }

def _fetch_jibe_job_detail(job_url: str) -> dict:
    payload = {"description": "", "posted_at": ""}
    try:
        response = requests.get(job_url, timeout=app_settings.get_advanced_int("requestTimeout"), headers={"User-Agent": _random_user_agent()})
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        logging.warning("Career job detail request failed for %s: %s", job_url, exc)
        return payload

    soup = BeautifulSoup(response.text, "html.parser")
    description = soup.select_one(".ats-description") or soup.select_one(".job-description")
    details = soup.select_one('[data-selector-name="jobdetails"]')
    posted_text = ""
    if details:
        details_text = details.get_text(" ", strip=True)
        posted_match = re.search(r"Date posted\s+([A-Za-z]{3,9}\.?\s+\d{1,2},\s+\d{4})", details_text)
        posted_text = posted_match.group(1) if posted_match else ""
    payload["description"] = convert_html_to_markdown(str(description)) if description else ""
    payload["posted_at"] = posted_text
    return payload

def _fetch_jibe_jobs(target: dict) -> list[dict]:
    base_url = target.get("base_url")
    if not base_url:
        return []

    jobs = []
    seen_ids = set()
    search_terms = target.get("search_terms") or getattr(config, "COMPANY_CAREER_ROLE_KEYWORDS", [])
    per_term_limit = int(target.get("limit") or getattr(config, "COMPANY_CAREER_JOBS_PER_TERM", 10) or 10)
    for search_text in search_terms:
        query = urlencode(
            {
                "ActiveFacetID": 0,
                "CurrentPage": 1,
                "RecordsPerPage": per_term_limit,
                "Distance": 50,
                "RadiusUnitType": 0,
                "Keywords": str(search_text),
                "ShowRadius": "False",
                "IsPagination": "False",
                "CustomFacetName": "",
                "FacetTerm": "",
                "FacetType": 0,
                "SearchResultsModuleName": "Search Results",
                "SearchFiltersModuleName": "Search Filters",
                "SortCriteria": 0,
                "SortDirection": 1,
                "SearchType": 5,
            }
        )
        payload = _fetch_json(f"{base_url.rstrip('/')}/search-jobs/results?{query}")
        if not isinstance(payload, dict) or not payload.get("hasJobs"):
            continue
        soup = BeautifulSoup(payload.get("results") or "", "html.parser")
        for card in soup.select("li.job-card"):
            job_details = _normalize_jibe_job(target, card)
            if not job_details or job_details["job_id"] in seen_ids:
                continue
            seen_ids.add(job_details["job_id"])
            jobs.append(job_details)
    return jobs

def _normalize_jibe_api_job(target: dict, job: dict) -> dict | None:
    data = job.get("data") if isinstance(job.get("data"), dict) else job
    if not isinstance(data, dict):
        return None

    slug = _plain_text(data.get("slug") or data.get("req_id"))
    if not slug:
        return None

    base_url = str(target.get("base_url") or "").rstrip("/")
    job_path = str(target.get("job_path") or "/jobs/{slug}")
    language = _plain_text(data.get("language") or "en-us")
    job_url = urljoin(base_url, job_path.format(slug=slug))
    if language and "lang=" not in job_url:
        separator = "&" if "?" in job_url else "?"
        job_url = f"{job_url}{separator}lang={language}"

    description = data.get("description") or data.get("qualifications") or data.get("responsibilities") or ""
    if "<" in str(description):
        description = convert_html_to_markdown(str(description))

    location = (
        data.get("full_location")
        or data.get("short_location")
        or ", ".join(_plain_text(part) for part in [data.get("city"), data.get("state"), data.get("country")] if _plain_text(part))
        or data.get("location_name")
        or ""
    )
    categories = data.get("categories") if isinstance(data.get("categories"), list) else data.get("category")
    if isinstance(categories, list):
        level = ", ".join(_plain_text(item) for item in categories if _plain_text(item))
    else:
        level = _plain_text(categories or data.get("employment_type"))

    return {
        "job_id": f"jibeapi-{target.get('name', '').lower().replace(' ', '-')}-{slug}",
        "company": target.get("name"),
        "job_title": _plain_text(data.get("title")),
        "location": _plain_text(location),
        "level": level,
        "provider": "company_careers_jibe_api",
        "description": description,
        "posted_at": data.get("posted_date") or data.get("create_date") or data.get("update_date") or "",
        "job_url": job_url,
        "apply_url": data.get("apply_url") or job_url,
        "career_url": target.get("career_url") or target.get("base_url") or "",
    }

def _fetch_jibe_api_jobs(target: dict) -> list[dict]:
    base_url = str(target.get("base_url") or "").rstrip("/")
    if not base_url:
        return []

    jobs = []
    seen_ids = set()
    search_terms = target.get("search_terms") or getattr(config, "COMPANY_CAREER_ROLE_KEYWORDS", [])
    per_term_limit = int(target.get("limit") or getattr(config, "COMPANY_CAREER_JOBS_PER_TERM", 10) or 10)
    for search_text in search_terms:
        payload = _fetch_json(
            f"{base_url}/api/jobs?{urlencode({'keywords': str(search_text), 'page': 1, 'limit': per_term_limit})}"
        )
        if not isinstance(payload, dict):
            continue
        for job in payload.get("jobs", []):
            if not isinstance(job, dict):
                continue
            job_details = _normalize_jibe_api_job(target, job)
            if not job_details or job_details["job_id"] in seen_ids:
                continue
            seen_ids.add(job_details["job_id"])
            jobs.append(job_details)
    return jobs

def _fetch_company_career_target_jobs(target: dict) -> list[dict]:
    ats = str(target.get("ats") or "").lower()
    if ats == "greenhouse":
        return _fetch_greenhouse_jobs(target)
    if ats == "lever":
        return _fetch_lever_jobs(target)
    if ats == "ashby":
        return _fetch_ashby_jobs(target)
    if ats == "smartrecruiters":
        return _fetch_smartrecruiters_jobs(target)
    if ats == "workday":
        return _fetch_workday_jobs(target)
    if ats == "jibe":
        return _fetch_jibe_jobs(target)
    if ats == "jibe_api":
        return _fetch_jibe_api_jobs(target)
    logging.info("Unsupported company career ATS '%s' for %s", ats, target.get("name"))
    return []

def _with_career_url(target: dict) -> dict:
    if target.get("career_url"):
        return target
    career_url = getattr(config, "COMPANY_CAREER_PAGE_URLS", {}).get(str(target.get("name") or ""))
    if not career_url:
        return target
    enriched = dict(target)
    enriched["career_url"] = career_url
    return enriched

def process_company_careers(limit: int | None = None) -> list:
    """Fetch matching jobs from configured top company career pages."""
    targets = list(getattr(config, "COMPANY_CAREER_TARGETS", []))
    target_limit = int(getattr(config, "COMPANY_CAREER_TARGET_LIMIT", 300) or 300)
    targets = targets[:target_limit]
    targets_per_run = int(getattr(config, "COMPANY_CAREER_TARGETS_PER_RUN", target_limit) or target_limit)
    total_targets = len(targets)
    if targets_per_run > 0 and total_targets > targets_per_run:
        batch_index = int(datetime.now(timezone.utc).timestamp() // 3600)
        start = (batch_index * targets_per_run) % total_targets
        end = start + targets_per_run
        targets = (targets + targets)[start:end]
        logging.info(
            "Company Careers target rotation: scanning window start=%s size=%s total=%s",
            start,
            len(targets),
            total_targets,
        )
    logging.info(
        "Company Careers enabled: scanning %s target(s), result limit=%s",
        len(targets),
        limit if limit is not None else "unlimited",
    )

    job_ids_set, company_title_set = supabase_utils.get_existing_jobs_from_supabase()
    detailed_new_jobs = []

    for target in targets:
        if limit is not None and len(detailed_new_jobs) >= limit:
            break
        if not isinstance(target, dict):
            continue
        target = _with_career_url(target)

        logging.info("Scraping company careers target: %s (%s)", target.get("name"), target.get("ats"))
        for details in _fetch_company_career_target_jobs(target):
            if limit is not None and len(detailed_new_jobs) >= limit:
                break
            if not details.get("job_id") or str(details["job_id"]) in job_ids_set:
                continue

            normalized_company = (details.get("company") or "").strip().lower()
            normalized_title = (details.get("job_title") or "").strip().lower()
            if normalized_company and normalized_title and (normalized_company, normalized_title) in company_title_set:
                continue

            if not _company_career_job_allowed(details):
                continue

            detailed_new_jobs.append(details)
            job_ids_set.add(str(details["job_id"]))
            if normalized_company and normalized_title:
                company_title_set.add((normalized_company, normalized_title))

    logging.info("--- Finished Company Careers: matched %s new job(s) ---", len(detailed_new_jobs))
    return detailed_new_jobs

# --- Main Execution ---
if __name__ == "__main__":

    total_new_jobs_saved = 0
    alert_jobs = []

    scraping_sources = app_settings.get_enabled_scraping_sources()
    logging.info("Enabled scraping sources: %s", ", ".join(scraping_sources) or "none")

    # Get jobs from LinkedIn
    if "linkedin" in scraping_sources:
        logging.info("\n--- Starting LinkedIn Job Scraping ---")
        max_jobs_per_search = app_settings.get_advanced_int("maxLinkedinJobsPerSearch")
        linkedin_locations = app_settings.get_linkedin_locations()
        for query in app_settings.get_linkedin_search_queries():
            for location in linkedin_locations:
                print(f"\n{'='*20} Processing Search Query: '{query}' in '{location}' {'='*20}")

                # 1. Process the query: Scrape IDs, filter, fetch new details
                new_linkedin_job_details = process_linkedin_query(query, location, limit=max_jobs_per_search)

                # 2. Save the NEW scraped data to Supabase
                if new_linkedin_job_details:
                    print(f"\n--- Saving {len(new_linkedin_job_details)} new job(s) for query '{query}' in '{location}' ---")
                    supabase_utils.save_jobs_to_supabase(new_linkedin_job_details)
                    total_new_jobs_saved += len(new_linkedin_job_details)
                    alert_jobs.extend(new_linkedin_job_details)
                else:
                    print(f"\nNo new job details were fetched or processed for query '{query}' in '{location}'.")
    else:
        logging.info("\n--- Skipping LinkedIn Job Scraping per config ---")

    # Get jobs from Careers Future
    if "careers_future" in scraping_sources:
        logging.info(f"\n--- Starting Careers Future Job Scraping ---")
        max_jobs_per_search = app_settings.get_advanced_int("maxCareersFutureJobsPerSearch")
        for query in app_settings.get_careers_future_search_queries():
            logging.info(f"\n{'='*20} Processing Careers Future Search Query: '{query}' {'='*20}")

            # 1. Process the query: Scrape IDs, filter, fetch new details
            new_careers_future_job_details = process_careers_future_query(query, limit=max_jobs_per_search)

            # 2. Save the NEW scraped data to Supabase
            if new_careers_future_job_details:
                logging.info(f"\n--- Saving {len(new_careers_future_job_details)} new job(s) for query '{query}' ---")
                supabase_utils.save_jobs_to_supabase(new_careers_future_job_details)
                total_new_jobs_saved += len(new_careers_future_job_details)
                alert_jobs.extend(new_careers_future_job_details)
            else:
                logging.info(f"\nNo new job details were fetched or processed for query '{query}'.")
    else:
        logging.info("\n--- Skipping Careers Future Job Scraping per config ---")

    # Get jobs from configured company career pages / ATS APIs.
    if "company_careers" in scraping_sources:
        logging.info("\n--- Starting Company Careers Job Scraping ---")
        max_jobs_per_run = app_settings.get_advanced_int("maxCompanyCareerJobsPerRun")
        new_company_career_jobs = process_company_careers(limit=max_jobs_per_run)

        if new_company_career_jobs:
            logging.info("\n--- Saving %s new company career job(s) ---", len(new_company_career_jobs))
            supabase_utils.save_jobs_to_supabase(new_company_career_jobs)
            total_new_jobs_saved += len(new_company_career_jobs)
            alert_jobs.extend(new_company_career_jobs)
        else:
            logging.info("\nNo new company career jobs were fetched or processed.")
    else:
        logging.info("\n--- Skipping Company Careers Job Scraping per config ---")

    # --- End of Script ---
    if alert_jobs:
        job_alerts.send_new_jobs_email(alert_jobs, source_label="JobTrack pipeline")
    logging.info(f"\n{'='*20} Job scraping script finished {'='*20}")
    logging.info(f"Total new jobs saved across all queries: {total_new_jobs_saved}")
