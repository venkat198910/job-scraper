import copy
import json
import logging
from typing import Any

import config

SETTINGS_TABLE = "app_settings"
SETTINGS_ID = "default"
SETTINGS_STORAGE_BUCKET = getattr(config, "SUPABASE_RESUME_STORAGE_BUCKET", "resumes")
SETTINGS_STORAGE_PATH = "settings/app_settings.json"

DEFAULT_SETTINGS = {
    "locations": getattr(config, "LINKEDIN_LOCATIONS", [getattr(config, "LINKEDIN_LOCATION", "")]),
    "roles": getattr(config, "LINKEDIN_SEARCH_QUERIES", []),
    "jobTypes": [getattr(config, "LINKEDIN_JOB_TYPE", "F")],
    "postingDateFilter": getattr(config, "LINKEDIN_JOB_POSTING_DATE", "r86400"),
    "minExperience": getattr(config, "LINKEDIN_MIN_EXPERIENCE_YEARS", 6),
    "maxExperience": getattr(config, "LINKEDIN_MAX_EXPERIENCE_YEARS", 12),
    "minScore": 90,
    "applicationProfile": {
        "firstName": "Venkateswarlu",
        "lastName": "Derangula",
        "fullName": "Venkateswarlu Derangula",
        "email": "vderangula44@gmail.com",
        "phone": "+91 7780569119",
        "linkedinUrl": "https://www.linkedin.com/in/venkateswarlu-derangula/",
        "githubUrl": "https://github.com/venkat198910/",
        "currentLocation": "Bengaluru",
        "addressLine1": "31, KR Puram",
        "addressCity": "Bengaluru",
        "addressState": "Karnataka",
        "addressPostalCode": "560036",
        "totalExperience": "9.6",
        "devopsExperience": "7+",
        "sreExperience": "7+",
        "cloudExperience": "6+",
        "kubernetesExperience": "5+",
        "terraformExperience": "5+",
        "pythonExperience": "3+",
    },
    "applicationAutomation": {
        "maxJobAgeMinutes": 720,
        "maxDailyApplications": 30,
        "allowFinalSubmit": False,
        "allowPortalLogin": False,
        "allowPortalRegister": False,
        "headlessBrowser": False,
    },
    "applicationAutoAnswers": {
        "country": "India",
        "nationality": "Indian",
        "currentJobTitle": "Technical Lead",
        "currentEmployer": "Infinite Computer Solutions",
        "highestEducation": "MBA",
        "degreeName": "MBA",
        "university": "SV University (EAIMS), Tirupati",
        "graduationYear": "2012",
        "bachelorDegree": "B.Com (Computer Applications)",
        "bachelorUniversity": "SV University, Tirupati",
        "bachelorGraduationYear": "2010",
        "availabilityDate": "After 30 days notice",
        "preferredWorkMode": "Remote or Hybrid",
        "preferredEmploymentType": "Full-time",
        "preferredShift": "Flexible",
        "openToContract": "No",
        "salaryNegotiable": "Yes",
        "workAuthorization": "No",
        "needSponsorship": "Yes",
        "indiaWorkAuthorization": "Yes",
        "indiaNeedSponsorship": "No",
        "outsideIndiaWorkAuthorization": "No",
        "outsideIndiaNeedSponsorship": "Yes",
        "currentLocation": "Bengaluru",
        "willingToRelocate": "Yes",
        "relocateLocations": "Bengaluru, Bangalore, Dubai, Abu Dhabi",
        "noticePeriod": "30 days",
        "indiaCurrentCtc": "31 LPA",
        "indiaExpectedCtc": "50 LPA",
        "uaeCurrentAnnual": "125000 AED",
        "uaeCurrentMonthly": "10300 AED",
        "uaeExpectedAnnual": "300000 AED",
        "uaeExpectedMonthly": "25000 AED",
    },
    "advanced": {
        "llmMaxRpm": getattr(config, "LLM_MAX_RPM", 10),
        "llmMaxRetries": getattr(config, "LLM_MAX_RETRIES", 3),
        "llmRetryBaseDelay": getattr(config, "LLM_RETRY_BASE_DELAY", 10),
        "llmDailyRequestBudget": getattr(config, "LLM_DAILY_REQUEST_BUDGET", 0),
        "llmRequestDelaySeconds": getattr(config, "LLM_REQUEST_DELAY_SECONDS", 8),
        "jobsToScorePerRun": getattr(config, "JOBS_TO_SCORE_PER_RUN", 10),
        "jobsToCustomizePerRun": getattr(config, "JOBS_TO_CUSTOMIZE_PER_RUN", 5),
        "jobsToRescorePerRun": getattr(config, "JOBS_TO_RESCORE_PER_RUN", 5),
        "maxLinkedinJobsPerSearch": getattr(config, "MAX_JOBS_PER_SEARCH", {}).get("linkedin", 20),
        "maxCareersFutureJobsPerSearch": getattr(config, "MAX_JOBS_PER_SEARCH", {}).get("careers_future", 10),
        "maxCompanyCareerJobsPerRun": getattr(config, "MAX_JOBS_PER_SEARCH", {}).get("company_careers", 300),
        "linkedinMaxStart": getattr(config, "LINKEDIN_MAX_START", 1),
        "requestTimeout": getattr(config, "REQUEST_TIMEOUT", 30),
        "maxRetries": getattr(config, "MAX_RETRIES", 3),
        "retryDelaySeconds": getattr(config, "RETRY_DELAY_SECONDS", 15),
        "jobExpiryDays": getattr(config, "JOB_EXPIRY_DAYS", 7),
        "jobCheckDays": getattr(config, "JOB_CHECK_DAYS", 3),
        "jobDeletionDays": getattr(config, "JOB_DELETION_DAYS", 60),
        "jobCheckLimit": getattr(config, "JOB_CHECK_LIMIT", 50),
        "activeCheckTimeout": getattr(config, "ACTIVE_CHECK_TIMEOUT", 20),
        "activeCheckMaxRetries": getattr(config, "ACTIVE_CHECK_MAX_RETRIES", 2),
        "activeCheckRetryDelay": getattr(config, "ACTIVE_CHECK_RETRY_DELAY", 10),
    },
    "toggles": {
        "linkedin": "linkedin" in getattr(config, "SCRAPING_SOURCES", []),
        "careersFuture": "careers_future" in getattr(config, "SCRAPING_SOURCES", []),
        "companyCareers": "company_careers" in getattr(config, "SCRAPING_SOURCES", []),
        "remote": True,
        "hybrid": True,
        "onsite": False,
        "easyApplyOnly": False,
        "companyPortals": True,
        "autoGenerateResume": True,
        "strictExperience": getattr(config, "LINKEDIN_REQUIRE_EXPERIENCE_RANGE_MATCH", True),
    },
}

_cached_settings: dict[str, Any] | None = None
JOB_TYPE_VALUES = {"F", "C", "P", "T", "I"}
POSTING_DATE_VALUES = {
    "r3600",
    "r7200",
    "r10800",
    "r14400",
    "r18000",
    "r21600",
    "r43200",
    "r86400",
    "r604800",
}


def _clean_string_list(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return fallback

    cleaned = []
    seen = set()
    for item in value:
        text = str(item or "").strip()
        key = text.lower()
        if text and key not in seen:
            cleaned.append(text)
            seen.add(key)

    return cleaned or fallback


def _bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback

    return min(maximum, max(minimum, number))


def _enum_list(value: Any, fallback: list[str], allowed: set[str]) -> list[str]:
    cleaned = [item for item in _clean_string_list(value, fallback) if item in allowed]
    return cleaned or fallback


def _enum_value(value: Any, fallback: str, allowed: set[str]) -> str:
    text = str(value or "").strip()
    return text if text in allowed else fallback


def _string_value(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def normalize_settings(value: Any) -> dict[str, Any]:
    incoming = value if isinstance(value, dict) else {}
    defaults = copy.deepcopy(DEFAULT_SETTINGS)
    incoming_toggles = incoming.get("toggles") if isinstance(incoming.get("toggles"), dict) else {}

    min_experience = _bounded_int(
        incoming.get("minExperience"),
        defaults["minExperience"],
        0,
        50,
    )
    max_experience = max(
        min_experience,
        _bounded_int(incoming.get("maxExperience"), defaults["maxExperience"], 0, 50),
    )
    incoming_advanced = incoming.get("advanced") if isinstance(incoming.get("advanced"), dict) else {}
    incoming_profile = incoming.get("applicationProfile") if isinstance(incoming.get("applicationProfile"), dict) else {}
    incoming_automation = incoming.get("applicationAutomation") if isinstance(incoming.get("applicationAutomation"), dict) else {}
    incoming_auto_answers = incoming.get("applicationAutoAnswers") if isinstance(incoming.get("applicationAutoAnswers"), dict) else {}

    return {
        "locations": _clean_string_list(incoming.get("locations"), defaults["locations"]),
        "roles": _clean_string_list(incoming.get("roles"), defaults["roles"]),
        "jobTypes": _enum_list(incoming.get("jobTypes"), defaults["jobTypes"], JOB_TYPE_VALUES),
        "postingDateFilter": _enum_value(
            incoming.get("postingDateFilter"),
            defaults["postingDateFilter"],
            POSTING_DATE_VALUES,
        ),
        "minExperience": min_experience,
        "maxExperience": max_experience,
        "minScore": _bounded_int(incoming.get("minScore"), defaults["minScore"], 0, 100),
        "applicationProfile": {
            key: _string_value(incoming_profile.get(key), default_value)
            for key, default_value in defaults["applicationProfile"].items()
        },
        "applicationAutomation": {
            "maxJobAgeMinutes": _bounded_int(
                incoming_automation.get("maxJobAgeMinutes"),
                defaults["applicationAutomation"]["maxJobAgeMinutes"],
                1,
                1440,
            ),
            "maxDailyApplications": _bounded_int(
                incoming_automation.get("maxDailyApplications"),
                defaults["applicationAutomation"]["maxDailyApplications"],
                0,
                200,
            ),
            "allowFinalSubmit": bool(
                incoming_automation.get(
                    "allowFinalSubmit",
                    defaults["applicationAutomation"]["allowFinalSubmit"],
                )
            ),
            "allowPortalLogin": bool(
                incoming_automation.get(
                    "allowPortalLogin",
                    defaults["applicationAutomation"]["allowPortalLogin"],
                )
            ),
            "allowPortalRegister": bool(
                incoming_automation.get(
                    "allowPortalRegister",
                    defaults["applicationAutomation"]["allowPortalRegister"],
                )
            ),
            "headlessBrowser": bool(
                incoming_automation.get(
                    "headlessBrowser",
                    defaults["applicationAutomation"]["headlessBrowser"],
                )
            ),
        },
        "applicationAutoAnswers": {
            key: _string_value(incoming_auto_answers.get(key), default_value)
            for key, default_value in defaults["applicationAutoAnswers"].items()
        },
        "advanced": {
            "llmMaxRpm": _bounded_int(incoming_advanced.get("llmMaxRpm"), defaults["advanced"]["llmMaxRpm"], 1, 120),
            "llmMaxRetries": _bounded_int(incoming_advanced.get("llmMaxRetries"), defaults["advanced"]["llmMaxRetries"], 0, 10),
            "llmRetryBaseDelay": _bounded_int(incoming_advanced.get("llmRetryBaseDelay"), defaults["advanced"]["llmRetryBaseDelay"], 1, 300),
            "llmDailyRequestBudget": _bounded_int(incoming_advanced.get("llmDailyRequestBudget"), defaults["advanced"]["llmDailyRequestBudget"], 0, 10000),
            "llmRequestDelaySeconds": _bounded_int(incoming_advanced.get("llmRequestDelaySeconds"), defaults["advanced"]["llmRequestDelaySeconds"], 0, 120),
            "jobsToScorePerRun": _bounded_int(incoming_advanced.get("jobsToScorePerRun"), defaults["advanced"]["jobsToScorePerRun"], 1, 1000),
            "jobsToCustomizePerRun": _bounded_int(incoming_advanced.get("jobsToCustomizePerRun"), defaults["advanced"]["jobsToCustomizePerRun"], 1, 1000),
            "jobsToRescorePerRun": _bounded_int(incoming_advanced.get("jobsToRescorePerRun"), defaults["advanced"]["jobsToRescorePerRun"], 1, 1000),
            "maxLinkedinJobsPerSearch": _bounded_int(incoming_advanced.get("maxLinkedinJobsPerSearch"), defaults["advanced"]["maxLinkedinJobsPerSearch"], 1, 1000),
            "maxCareersFutureJobsPerSearch": _bounded_int(incoming_advanced.get("maxCareersFutureJobsPerSearch"), defaults["advanced"]["maxCareersFutureJobsPerSearch"], 1, 1000),
            "maxCompanyCareerJobsPerRun": _bounded_int(incoming_advanced.get("maxCompanyCareerJobsPerRun"), defaults["advanced"]["maxCompanyCareerJobsPerRun"], 1, 1000),
            "linkedinMaxStart": _bounded_int(incoming_advanced.get("linkedinMaxStart"), defaults["advanced"]["linkedinMaxStart"], 0, 1000),
            "requestTimeout": _bounded_int(incoming_advanced.get("requestTimeout"), defaults["advanced"]["requestTimeout"], 5, 300),
            "maxRetries": _bounded_int(incoming_advanced.get("maxRetries"), defaults["advanced"]["maxRetries"], 0, 10),
            "retryDelaySeconds": _bounded_int(incoming_advanced.get("retryDelaySeconds"), defaults["advanced"]["retryDelaySeconds"], 1, 300),
            "jobExpiryDays": _bounded_int(incoming_advanced.get("jobExpiryDays"), defaults["advanced"]["jobExpiryDays"], 1, 365),
            "jobCheckDays": _bounded_int(incoming_advanced.get("jobCheckDays"), defaults["advanced"]["jobCheckDays"], 1, 365),
            "jobDeletionDays": _bounded_int(incoming_advanced.get("jobDeletionDays"), defaults["advanced"]["jobDeletionDays"], 1, 3650),
            "jobCheckLimit": _bounded_int(incoming_advanced.get("jobCheckLimit"), defaults["advanced"]["jobCheckLimit"], 1, 1000),
            "activeCheckTimeout": _bounded_int(incoming_advanced.get("activeCheckTimeout"), defaults["advanced"]["activeCheckTimeout"], 5, 300),
            "activeCheckMaxRetries": _bounded_int(incoming_advanced.get("activeCheckMaxRetries"), defaults["advanced"]["activeCheckMaxRetries"], 0, 10),
            "activeCheckRetryDelay": _bounded_int(incoming_advanced.get("activeCheckRetryDelay"), defaults["advanced"]["activeCheckRetryDelay"], 1, 300),
        },
        "toggles": {
            key: bool(incoming_toggles.get(key, default_value))
            for key, default_value in defaults["toggles"].items()
        },
    }


def get_app_settings(force_refresh: bool = False) -> dict[str, Any]:
    global _cached_settings

    if _cached_settings is not None and not force_refresh:
        return copy.deepcopy(_cached_settings)

    try:
        import supabase_utils

        try:
            response = (
                supabase_utils.supabase.table(SETTINGS_TABLE)
                .select("settings")
                .eq("id", SETTINGS_ID)
                .limit(1)
                .execute()
            )
            if response.data:
                _cached_settings = normalize_settings(response.data[0].get("settings"))
            else:
                _cached_settings = normalize_settings(_download_storage_settings(supabase_utils))
        except Exception as table_exc:
            logging.info("Settings table unavailable; reading storage fallback: %s", table_exc)
            _cached_settings = normalize_settings(_download_storage_settings(supabase_utils))
    except Exception as exc:
        logging.warning("Using default app settings; could not load %s: %s", SETTINGS_TABLE, exc)
        _cached_settings = normalize_settings(DEFAULT_SETTINGS)

    return copy.deepcopy(_cached_settings)


def _download_storage_settings(supabase_utils: Any) -> dict[str, Any]:
    try:
        file_bytes = (
            supabase_utils.supabase.storage.from_(SETTINGS_STORAGE_BUCKET)
            .download(SETTINGS_STORAGE_PATH)
        )
        if isinstance(file_bytes, str):
            raw_text = file_bytes
        else:
            raw_text = bytes(file_bytes).decode("utf-8")
        return json.loads(raw_text)
    except Exception as exc:
        logging.info("Settings storage fallback unavailable; using defaults: %s", exc)
        return DEFAULT_SETTINGS


def get_enabled_scraping_sources() -> list[str]:
    toggles = get_app_settings()["toggles"]
    sources = []
    if toggles.get("linkedin"):
        sources.append("linkedin")
    if toggles.get("careersFuture"):
        sources.append("careers_future")
    if toggles.get("companyCareers"):
        sources.append("company_careers")
    return sources


def get_linkedin_locations() -> list[str]:
    return get_app_settings()["locations"]


def get_linkedin_search_queries() -> list[str]:
    return get_app_settings()["roles"]


def get_linkedin_job_type_param() -> str:
    return ",".join(get_app_settings()["jobTypes"])


def get_linkedin_posting_date_filter() -> str:
    return get_app_settings()["postingDateFilter"]


def get_careers_future_search_queries() -> list[str]:
    if get_app_settings()["toggles"].get("careersFuture"):
        return get_app_settings()["roles"]
    return getattr(config, "CAREERS_FUTURE_SEARCH_QUERIES", [])


def get_experience_range() -> tuple[int, int, bool]:
    settings = get_app_settings()
    return (
        settings["minExperience"],
        settings["maxExperience"],
        bool(settings["toggles"].get("strictExperience")),
    )


def get_min_score() -> int:
    return get_app_settings()["minScore"]


def get_application_profile() -> dict[str, str]:
    return get_app_settings()["applicationProfile"]


def get_application_automation() -> dict[str, Any]:
    return get_app_settings()["applicationAutomation"]


def get_application_auto_answers() -> dict[str, str]:
    return get_app_settings()["applicationAutoAnswers"]


def get_application_auto_answer_defaults() -> dict[str, str]:
    answers = get_application_auto_answers()
    profile = get_application_profile()

    return {
        "Country": answers.get("country", ""),
        "Current Country": answers.get("country", ""),
        "Nationality": answers.get("nationality", ""),
        "Current Job Title": answers.get("currentJobTitle", ""),
        "Current Title": answers.get("currentJobTitle", ""),
        "Current Role": answers.get("currentJobTitle", ""),
        "Current Employer": answers.get("currentEmployer", ""),
        "Current Company": answers.get("currentEmployer", ""),
        "Highest Education": answers.get("highestEducation", ""),
        "Highest Qualification": answers.get("highestEducation", ""),
        "Degree": answers.get("degreeName", ""),
        "Qualification": answers.get("degreeName", ""),
        "University": answers.get("university", ""),
        "College": answers.get("university", ""),
        "Graduation Year": answers.get("graduationYear", ""),
        "Year of Graduation": answers.get("graduationYear", ""),
        "Bachelor Degree": answers.get("bachelorDegree", ""),
        "Bachelor's Degree": answers.get("bachelorDegree", ""),
        "Undergraduate Degree": answers.get("bachelorDegree", ""),
        "Bachelor University": answers.get("bachelorUniversity", ""),
        "Bachelor College": answers.get("bachelorUniversity", ""),
        "Bachelor Graduation Year": answers.get("bachelorGraduationYear", ""),
        "Undergraduate Graduation Year": answers.get("bachelorGraduationYear", ""),
        "Available From": answers.get("availabilityDate", ""),
        "Availability Date": answers.get("availabilityDate", ""),
        "Preferred Work Mode": answers.get("preferredWorkMode", ""),
        "Work Mode": answers.get("preferredWorkMode", ""),
        "Preferred Employment Type": answers.get("preferredEmploymentType", ""),
        "Employment Type": answers.get("preferredEmploymentType", ""),
        "Preferred Shift": answers.get("preferredShift", ""),
        "Shift Preference": answers.get("preferredShift", ""),
        "Open to Contract": answers.get("openToContract", ""),
        "Contract Role": answers.get("openToContract", ""),
        "Salary Negotiable": answers.get("salaryNegotiable", ""),
        "Negotiable": answers.get("salaryNegotiable", ""),
        "Work Authorization": answers.get("workAuthorization", ""),
        "Are you authorized to work": answers.get("workAuthorization", ""),
        "Are you legally authorized to work": answers.get("workAuthorization", ""),
        "Need Sponsorship": answers.get("needSponsorship", ""),
        "Do you need sponsorship": answers.get("needSponsorship", ""),
        "Do you require sponsorship": answers.get("needSponsorship", ""),
        "Visa Sponsorship": answers.get("needSponsorship", ""),
        "India Work Authorization": answers.get("indiaWorkAuthorization", ""),
        "India Sponsorship": answers.get("indiaNeedSponsorship", ""),
        "Outside India Work Authorization": answers.get("outsideIndiaWorkAuthorization", ""),
        "Outside India Sponsorship": answers.get("outsideIndiaNeedSponsorship", ""),
        "Current Location": answers.get("currentLocation", profile.get("currentLocation", "")),
        "Willing to Relocate": answers.get("willingToRelocate", ""),
        "Relocation": answers.get("willingToRelocate", ""),
        "Preferred Relocation Locations": answers.get("relocateLocations", ""),
        "Notice Period": answers.get("noticePeriod", ""),
        "Availability": answers.get("noticePeriod", ""),
        "Total Experience": profile.get("totalExperience", ""),
        "Years of Experience": profile.get("totalExperience", ""),
        "DevOps Experience": profile.get("devopsExperience", ""),
        "SRE Experience": profile.get("sreExperience", ""),
        "AWS Experience": profile.get("cloudExperience", ""),
        "Cloud Experience": profile.get("cloudExperience", ""),
        "Kubernetes Experience": profile.get("kubernetesExperience", ""),
        "Terraform Experience": profile.get("terraformExperience", ""),
        "Python Experience": profile.get("pythonExperience", ""),
        "Current CTC": answers.get("indiaCurrentCtc", ""),
        "Expected CTC": answers.get("indiaExpectedCtc", ""),
        "Current Salary": answers.get("indiaCurrentCtc", ""),
        "Expected Salary": answers.get("indiaExpectedCtc", ""),
        "UAE Current Annual Salary": answers.get("uaeCurrentAnnual", ""),
        "UAE Current Monthly Salary": answers.get("uaeCurrentMonthly", ""),
        "UAE Expected Annual Salary": answers.get("uaeExpectedAnnual", ""),
        "UAE Expected Monthly Salary": answers.get("uaeExpectedMonthly", ""),
    }


def get_application_profile_defaults() -> dict[str, str]:
    profile = get_application_profile()
    address_parts = [
        profile.get("addressLine1", ""),
        profile.get("addressCity", ""),
        profile.get("addressState", ""),
        profile.get("addressPostalCode", ""),
    ]
    address = "\n".join(part for part in address_parts if part)

    return {
        "First Name": profile.get("firstName", ""),
        "Last Name": profile.get("lastName", ""),
        "Full Name": profile.get("fullName", ""),
        "Name": profile.get("fullName", ""),
        "Email": profile.get("email", ""),
        "Email Address": profile.get("email", ""),
        "Phone": profile.get("phone", ""),
        "Mobile": profile.get("phone", ""),
        "Mobile Phone": profile.get("phone", ""),
        "LinkedIn": profile.get("linkedinUrl", ""),
        "LinkedIn Profile": profile.get("linkedinUrl", ""),
        "GitHub": profile.get("githubUrl", ""),
        "GitHub Profile": profile.get("githubUrl", ""),
        "Current Location": profile.get("currentLocation", ""),
        "Location": profile.get("currentLocation", ""),
        "Address": address,
        "Street Address": profile.get("addressLine1", ""),
        "City": profile.get("addressCity", ""),
        "State": profile.get("addressState", ""),
        "Postal Code": profile.get("addressPostalCode", ""),
        "Zip Code": profile.get("addressPostalCode", ""),
        "Total Experience": profile.get("totalExperience", ""),
        "Years of Experience": profile.get("totalExperience", ""),
        "DevOps Experience": profile.get("devopsExperience", ""),
        "SRE Experience": profile.get("sreExperience", ""),
        "AWS/Cloud Experience": profile.get("cloudExperience", ""),
        "Cloud Experience": profile.get("cloudExperience", ""),
        "Kubernetes Experience": profile.get("kubernetesExperience", ""),
        "Terraform Experience": profile.get("terraformExperience", ""),
        "Python Experience": profile.get("pythonExperience", ""),
    }


def is_auto_resume_enabled() -> bool:
    return bool(get_app_settings()["toggles"].get("autoGenerateResume"))


def get_linkedin_work_type_param() -> str | None:
    toggles = get_app_settings()["toggles"]
    work_types = []
    if toggles.get("onsite"):
        work_types.append("1")
    if toggles.get("remote"):
        work_types.append("2")
    if toggles.get("hybrid"):
        work_types.append("3")
    return ",".join(work_types) if work_types else None


def is_easy_apply_only() -> bool:
    return bool(get_app_settings()["toggles"].get("easyApplyOnly"))


def get_advanced_int(key: str) -> int:
    settings = get_app_settings()
    return int(settings["advanced"].get(key, DEFAULT_SETTINGS["advanced"][key]))
