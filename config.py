import os
from dotenv import load_dotenv

load_dotenv()
load_dotenv("jobs-scrapper-web/.env.local")


def _clean_env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value else None

# =================================================================
# 1. CORE SYSTEM CONFIGURATION
# =================================================================

SUPABASE_URL: str = _clean_env("SUPABASE_URL") or _clean_env("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY: str = _clean_env("SUPABASE_SERVICE_ROLE_KEY") or _clean_env("NEXT_PUBLIC_SUPABASE_SERVICE_ROLE_KEY")

SUPABASE_TABLE_NAME: str = "jobs"
SUPABASE_CUSTOMIZED_RESUMES_TABLE_NAME = "customized_resumes"

SUPABASE_STORAGE_BUCKET = "personalized_resumes"
SUPABASE_RESUME_STORAGE_BUCKET = "resumes"

SUPABASE_BASE_RESUME_TABLE_NAME = "base_resume"

BASE_RESUME_PATH = "resume.json"

# Optional email alerts for newly scraped jobs. Configure these as GitHub
# Actions secrets to receive a digest after each pipeline run.
JOB_ALERT_EMAIL_TO = _clean_env("JOB_ALERT_EMAIL_TO") or _clean_env("ALERT_EMAIL_TO")
JOB_ALERT_EMAIL_FROM = _clean_env("JOB_ALERT_EMAIL_FROM") or _clean_env("SMTP_FROM") or JOB_ALERT_EMAIL_TO
SMTP_HOST = _clean_env("SMTP_HOST")
SMTP_PORT = int(_clean_env("SMTP_PORT") or "587")
SMTP_USERNAME = _clean_env("SMTP_USERNAME") or _clean_env("SMTP_USER")
SMTP_PASSWORD = _clean_env("SMTP_PASSWORD") or _clean_env("SMTP_PASS")

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
    "Senior DevOps Engineer",
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

# Locations
LINKEDIN_LOCATIONS = [
    "Dubai, United Arab Emirates",
    "Abu Dhabi, United Arab Emirates",
    "Bengaluru, Karnataka, India",
    "Bangalore, Karnataka, India",
]

# Backward-compatible default for older scripts.
LINKEDIN_LOCATION = LINKEDIN_LOCATIONS[0]

# LinkedIn GEO IDs by location.
LINKEDIN_GEO_IDS = {
    "Dubai, United Arab Emirates": 106204383,
    "Abu Dhabi, United Arab Emirates": 103720977,
    "Bengaluru, Karnataka, India": 105214831,
    "Bangalore, Karnataka, India": 105214831,
}

# Backward-compatible default for older scripts.
LINKEDIN_GEO_ID = LINKEDIN_GEO_IDS[LINKEDIN_LOCATION]

# Job Type
# F=Full-time
# C=Contract
# P=Part-time
# T=Temporary
# I=Internship

LINKEDIN_JOB_TYPE = "F"

# Experience filter
# LinkedIn f_E values: 2=Entry, 3=Associate, 4=Mid-Senior, 5=Director, 6=Executive
LINKEDIN_EXPERIENCE_LEVELS = [4]

# Local description filter. Jobs must clearly ask for experience within this range.
LINKEDIN_MIN_EXPERIENCE_YEARS = 6
LINKEDIN_MAX_EXPERIENCE_YEARS = 12
LINKEDIN_REQUIRE_EXPERIENCE_RANGE_MATCH = True

# Do not drop UAE jobs just because the posting omits visa/sponsorship wording.
# Sponsorship answers are handled later during application automation.
LINKEDIN_UAE_REQUIRE_SPONSORSHIP = False
LINKEDIN_UAE_SPONSORSHIP_KEYWORDS = [
    "visa sponsorship",
    "sponsorship provided",
    "provide sponsorship",
    "provides sponsorship",
    "will sponsor",
    "employment visa",
    "work visa",
    "visa provided",
    "company sponsored visa",
    "company-sponsored visa",
    "immigration support",
    "relocation support",
]

# Skip LinkedIn jobs that already have more than this many applicants.
# Set to 0 to disable the applicant-count filter. If LinkedIn does not expose
# an applicant count, the job is kept.
LINKEDIN_MAX_APPLICANTS = 30

# Local title/domain guard. Broad searches like "Cloud Engineer" can return
# data engineering jobs; skip them before saving/scoring.
EXCLUDED_JOB_TITLE_KEYWORDS = [
    "data engineer",
    "cloud data engineer",
    "big data",
    "data platform",
    "data pipeline",
    "etl",
    "analytics engineer",
    "bi engineer",
    "business intelligence",
    "data warehouse",
    "snowflake",
    "databricks",
    "solution engineer",
    "solutions engineer",
    "advanced solution engineer",
    "solution consultant",
    "solutions consultant",
    "functional consultant",
    "technical consultant",
    "implementation consultant",
    "oracle fusion",
    "fusion cloud",
    "oracle cloud hcm",
    "cloud hcm",
    "hcm",
    "human capital management",
    "workday hcm",
    "sap successfactors",
    "successfactors",
    "salesforce",
    "crm",
    "erp",
    "netsuite",
    "servicenow consultant",
]

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
# COMPANY CAREERS SEARCH CONFIGURATION
# =================================================================

# Company career pages are scraped through public ATS APIs where available.
# Add more targets here without touching scraper logic.
COMPANY_CAREER_ROLE_KEYWORDS = [
    "devops",
    "site reliability",
    "sre",
    "cloud engineer",
    "cloud platform",
    "platform engineer",
    "infrastructure",
    "kubernetes",
    "terraform",
    "devsecops",
    "release engineer",
    "observability",
]

COMPANY_CAREER_LOCATION_KEYWORDS = [
    "bengaluru",
    "bangalore",
    "karnataka",
    "india",
    "dubai",
    "abu dhabi",
    "united arab emirates",
    "uae",
    "remote",
]

COMPANY_CAREER_TARGET_LIMIT = 300

COMPANY_CAREER_TARGETS = [
    # User-priority Workday career pages.
    {"name": "CBA India Services Private Limited", "ats": "workday", "host": "cba.wd3.myworkdayjobs.com", "tenant": "cba", "site": "CommBank_Careers", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Lloyds Technology Centre", "ats": "workday", "host": "lbg.wd3.myworkdayjobs.com", "tenant": "lbg", "site": "Lloyds_Technology_Centre", "search_terms": ["DevOps Engineer", "DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},

    # Automotive/product engineering companies requested first.
    {"name": "Mercedes-Benz", "ats": "smartrecruiters", "slug": "MercedesBenz"},
    {"name": "Mercedes-Benz Group", "ats": "smartrecruiters", "slug": "MercedesBenzGroup"},
    {"name": "BMW", "ats": "smartrecruiters", "slug": "BMW"},
    {"name": "BMW Group", "ats": "smartrecruiters", "slug": "BMWGroup"},
    {"name": "Volvo Group", "ats": "smartrecruiters", "slug": "VolvoGroup"},
    {"name": "Volvo Cars", "ats": "smartrecruiters", "slug": "VolvoCars"},
    {"name": "Bosch", "ats": "smartrecruiters", "slug": "BoschGroup"},

    # Workday/Jibe career sites verified from public career pages.
    {"name": "Philips", "ats": "workday", "host": "philips.wd3.myworkdayjobs.com", "tenant": "philips", "site": "jobs-and-careers", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Signify", "ats": "workday", "host": "lighting.wd3.myworkdayjobs.com", "tenant": "lighting", "site": "jobs-and-careers", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Arm", "ats": "jibe", "base_url": "https://careers.arm.com", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},

    # Greenhouse boards commonly used by product/platform companies.
    {"name": "Airbnb", "ats": "greenhouse", "slug": "airbnb"},
    {"name": "Anduril", "ats": "greenhouse", "slug": "andurilindustries"},
    {"name": "Applied Intuition", "ats": "greenhouse", "slug": "appliedintuition"},
    {"name": "Asana", "ats": "greenhouse", "slug": "asana"},
    {"name": "Benchling", "ats": "greenhouse", "slug": "benchling"},
    {"name": "Box", "ats": "greenhouse", "slug": "boxinc"},
    {"name": "Brex", "ats": "greenhouse", "slug": "brex"},
    {"name": "Canonical", "ats": "greenhouse", "slug": "canonical"},
    {"name": "Cloudflare", "ats": "greenhouse", "slug": "cloudflare"},
    {"name": "Coinbase", "ats": "greenhouse", "slug": "coinbase"},
    {"name": "Databricks", "ats": "greenhouse", "slug": "databricks"},
    {"name": "DoorDash", "ats": "greenhouse", "slug": "doordashusa"},
    {"name": "Dropbox", "ats": "greenhouse", "slug": "dropbox"},
    {"name": "Figma", "ats": "greenhouse", "slug": "figma"},
    {"name": "GitHub", "ats": "greenhouse", "slug": "github"},
    {"name": "Gusto", "ats": "greenhouse", "slug": "gusto"},
    {"name": "HashiCorp", "ats": "greenhouse", "slug": "hashicorp"},
    {"name": "Instacart", "ats": "greenhouse", "slug": "instacart"},
    {"name": "Lyft", "ats": "greenhouse", "slug": "lyft"},
    {"name": "MongoDB", "ats": "greenhouse", "slug": "mongodb"},
    {"name": "Notion", "ats": "greenhouse", "slug": "notion"},
    {"name": "Okta", "ats": "greenhouse", "slug": "okta"},
    {"name": "Pinterest", "ats": "greenhouse", "slug": "pinterest"},
    {"name": "Plaid", "ats": "greenhouse", "slug": "plaid"},
    {"name": "Reddit", "ats": "greenhouse", "slug": "reddit"},
    {"name": "Rippling", "ats": "greenhouse", "slug": "rippling"},
    {"name": "Roblox", "ats": "greenhouse", "slug": "roblox"},
    {"name": "Scale AI", "ats": "greenhouse", "slug": "scaleai"},
    {"name": "Snowflake", "ats": "greenhouse", "slug": "snowflakecomputing"},
    {"name": "SoFi", "ats": "greenhouse", "slug": "sofi"},
    {"name": "Stripe", "ats": "greenhouse", "slug": "stripe"},
    {"name": "Twilio", "ats": "greenhouse", "slug": "twilio"},
    {"name": "Uber", "ats": "greenhouse", "slug": "uber"},
    {"name": "Wayfair", "ats": "greenhouse", "slug": "wayfair"},
    {"name": "Zapier", "ats": "greenhouse", "slug": "zapier"},

    # Lever boards.
    {"name": "Netflix", "ats": "lever", "slug": "netflix"},
    {"name": "Spotify", "ats": "lever", "slug": "spotify"},
    {"name": "Slack", "ats": "lever", "slug": "slack"},
    {"name": "Verkada", "ats": "lever", "slug": "verkada"},
    {"name": "LaunchDarkly", "ats": "lever", "slug": "launchdarkly"},
    {"name": "Samsara", "ats": "lever", "slug": "samsara"},
    {"name": "Sourcegraph", "ats": "lever", "slug": "sourcegraph"},
    {"name": "Vercel", "ats": "lever", "slug": "vercel"},

    # Ashby boards.
    {"name": "Anthropic", "ats": "ashby", "slug": "anthropic"},
    {"name": "Cursor", "ats": "ashby", "slug": "cursor"},
    {"name": "Linear", "ats": "ashby", "slug": "linear"},
    {"name": "Perplexity", "ats": "ashby", "slug": "perplexity"},
]

# =================================================================
# PROCESSING LIMITS
# =================================================================

SCRAPING_SOURCES = [
    "linkedin",
    "company_careers",
    # "careers_future"
]

JOBS_TO_SCORE_PER_RUN = 10

JOBS_TO_CUSTOMIZE_PER_RUN = 5

JOBS_TO_RESCORE_PER_RUN = 5

MAX_JOBS_PER_SEARCH = {
    "linkedin": 20,
    "careers_future": 10,
    "company_careers": 300,
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
