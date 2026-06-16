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
    "minExperience": getattr(config, "LINKEDIN_MIN_EXPERIENCE_YEARS", 6),
    "maxExperience": getattr(config, "LINKEDIN_MAX_EXPERIENCE_YEARS", 12),
    "minScore": 90,
    "toggles": {
        "linkedin": "linkedin" in getattr(config, "SCRAPING_SOURCES", []),
        "careersFuture": "careers_future" in getattr(config, "SCRAPING_SOURCES", []),
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

    return {
        "locations": _clean_string_list(incoming.get("locations"), defaults["locations"]),
        "roles": _clean_string_list(incoming.get("roles"), defaults["roles"]),
        "minExperience": min_experience,
        "maxExperience": max_experience,
        "minScore": _bounded_int(incoming.get("minScore"), defaults["minScore"], 0, 100),
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
    return sources


def get_linkedin_locations() -> list[str]:
    return get_app_settings()["locations"]


def get_linkedin_search_queries() -> list[str]:
    return get_app_settings()["roles"]


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
