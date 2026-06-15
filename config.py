import os
from dotenv import load_dotenv

load_dotenv()


def _clean_env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value else None

# =================================================================
# 1. CORE SYSTEM CONFIGURATION
# =================================================================

SUPABASE_URL: str = _clean_env("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY: str = _clean_env("SUPABASE_SERVICE_ROLE_KEY")

SUPABASE_TABLE_NAME: str = "jobs"
SUPABASE_CUSTOMIZED_RESUMES_TABLE_NAME = "customized_resumes"

SUPABASE_STORAGE_BUCKET = "personalized_resumes"
SUPABASE_RESUME_STORAGE_BUCKET = "resumes"

SUPABASE_BASE_RESUME_TABLE_NAME = "base_resume"

BASE_RESUME_PATH = "resume.json"

# Provider-specific API keys.
#
# Keep these separate. Fallback models use different providers, so a Gemini key
# must never be passed to OpenAI/Groq and vice versa.
GEMINI_API_KEY = _clean_env("GEMINI_API_KEY") or _clean_env("GEMINI_FIRST_API_KEY")
OPENAI_API_KEY = _clean_env("OPENAI_API_KEY")
ANTHROPIC_API_KEY = _clean_env("ANTHROPIC_API_KEY")
GROQ_API_KEY = _clean_env("GROQ_API_KEY")

# Optional legacy/generic key. Existing scripts still use this as an "any LLM
# key exists" check. llm_client only uses it for the matching primary provider,
# never for unrelated fallback providers.
LLM_API_KEY = (
    _clean_env("LLM_API_KEY")
    or GEMINI_API_KEY
    or OPENAI_API_KEY
    or ANTHROPIC_API_KEY
    or GROQ_API_KEY
)

# =================================================================
# 2. USER PREFERENCES
# =================================================================

# --- LLM Settings ---

# Primary LLM Model
# Examples:
# "gemini/gemini-2.5-flash-lite"
# "gemini/gemini-3.1-flash-lite-preview"
# "gpt-4o-mini"
# "groq/llama-3.3-70b-versatile"

LLM_MODEL = "gemini/gemini-2.5-flash-lite"

# LLM Fallback Models (in priority order)
# If the primary model fails or hits rate limits, the client will automatically
# attempt these fallback models in the specified order
# Priority: Gemini (primary) → OpenAI → Groq
LLM_FALLBACK_MODELS = [
    "gpt-4o-mini",  # OpenAI fallback
    "anthropic/claude-3-haiku-20240307",  # Anthropic fallback
    "groq/llama-3.3-70b-versatile",  # Groq secondary fallback
]

# =================================================================
# LINKEDIN SEARCH CONFIGURATION
# =================================================================

LINKEDIN_SEARCH_QUERIES = [
    "DevOps Engineer",
    "Cloud Engineer",
    "GCP Engineer",
    "GCP DevOps Engineer",
    "Google Cloud Engineer",
    "Kubernetes Engineer",
    "Platform Engineer",
    "Infrastructure Engineer",
    "Terraform Engineer",
    "Site Reliability Engineer",
    "SRE",
    "DevSecOps Engineer",
    "CI/CD Engineer",
    "Release Engineer",
    "Cloud Platform Engineer",
    "Observability Engineer",
    "Docker Kubernetes Engineer",
    "GKE Engineer",
    "Cloud Native Engineer"
]

# Location
LINKEDIN_LOCATION = "India"

# India GEO ID
LINKEDIN_GEO_ID = 102713980

# Job Type
# F=Full-time
# C=Contract
# P=Part-time
# T=Temporary
# I=Internship

LINKEDIN_JOB_TYPE = "F"

# Date Filter
# r86400 = Past 24h
# r604800 = Past week

LINKEDIN_JOB_POSTING_DATE = "r86400"

# Work Type
# 1 = Onsite
# 2 = Remote
# 3 = Hybrid

LINKEDIN_F_WT = 2

# =================================================================
# CAREERS FUTURE SEARCH CONFIGURATION
# =================================================================

CAREERS_FUTURE_SEARCH_QUERIES = [
    "DevOps Engineer",
    "Cloud Engineer",
    "GCP Engineer",
    "Kubernetes Engineer",
    "Platform Engineer",
    "Terraform Engineer",
    "Infrastructure Engineer",
    "SRE",
    "Cloud Platform Engineer"
]

CAREERS_FUTURE_SEARCH_CATEGORIES = [
    "Information Technology"
]

CAREERS_FUTURE_SEARCH_EMPLOYMENT_TYPES = [
    "Full Time"
]

# =================================================================
# PROCESSING LIMITS
# =================================================================

SCRAPING_SOURCES = [
    "linkedin"
    # "careers_future"
]

JOBS_TO_SCORE_PER_RUN = 20

JOBS_TO_CUSTOMIZE_PER_RUN = 10

MAX_JOBS_PER_SEARCH = {
    "linkedin": 25,
    "careers_future": 10,
}

# =================================================================
# 3. ADVANCED SYSTEM SETTINGS
# =================================================================

LLM_MAX_RPM = 10

LLM_MAX_RETRIES = 3

LLM_RETRY_BASE_DELAY = 10

# 0 = unlimited
LLM_DAILY_REQUEST_BUDGET = 0

LLM_REQUEST_DELAY_SECONDS = 8

LINKEDIN_MAX_START = 1

REQUEST_TIMEOUT = 30

MAX_RETRIES = 3

RETRY_DELAY_SECONDS = 15

# Move active jobs to Expired Jobs once they are older than one week.
JOB_EXPIRY_DAYS = 7

JOB_CHECK_DAYS = 3

JOB_DELETION_DAYS = 60

JOB_CHECK_LIMIT = 50

ACTIVE_CHECK_TIMEOUT = 20

ACTIVE_CHECK_MAX_RETRIES = 2

ACTIVE_CHECK_RETRY_DELAY = 10
