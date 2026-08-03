import os
from dotenv import load_dotenv
from product_company_career_catalog import NON_STARTUP_PRODUCT_COMPANY_CAREER_PAGE_URLS
from resolved_product_company_career_targets import RESOLVED_PRODUCT_COMPANY_CAREER_TARGETS

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

# Only save jobs from companies in the curated established-employer catalogs
# and active career targets. This intentionally rejects unknown, confidential,
# and startup employers discovered through broad job-board searches.
ESTABLISHED_COMPANIES_ONLY = True
ADDITIONAL_ESTABLISHED_COMPANIES = []

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
    "compensation",
    "total rewards",
    "people partner",
    "people business partner",
    "talent acquisition",
    "recruiter",
    "human resources",
    "hr business partner",
    "payroll",
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

COMPANY_CAREER_TITLE_KEYWORDS = [
    "devops",
    "site reliability",
    "sre",
    "cloud",
    "platform",
    "infrastructure",
    "kubernetes",
    "terraform",
    "devsecops",
    "release",
    "observability",
    "gcp",
    "aws",
    "azure",
]

COMPANY_CAREER_LOCATION_KEYWORDS = [
    "bengaluru",
    "bangalore",
    "bangalore urban",
    "greater bengaluru",
    "dubai",
    "abu dhabi",
    "abu dhabi emirate",
    "united arab emirates",
    "uae",
]

COMPANY_CAREER_TARGET_LIMIT = 300
COMPANY_CAREER_JOBS_PER_TERM = 10
COMPANY_CAREER_TARGETS_PER_RUN = 40

COMPANY_CAREER_TARGETS = [
    {
        "name": "Synopsys",
        "career_url": "https://careers.synopsys.com/search-jobs",
        "ats": "html",
        "list_url": "https://careers.synopsys.com/search-jobs?k=Site%20Reliability",
        "job_link_pattern": r"/job/[^/]+/[^/]+/\d+/\d+/?$",
        "max_detail_pages": 50,
    },
    # User-priority Workday career pages.
    {
        "name": "CBA India Services Private Limited",
        "career_url": "https://cba.wd3.myworkdayjobs.com/en-US/CommBank_Careers?q=DevOps&locationCountry=c4f78be1a8f14da0ab49ce1162348a5e&hiringCompany=007f52aebee601634bb894dc0d370187",
        "ats": "workday",
        "host": "cba.wd3.myworkdayjobs.com",
        "tenant": "cba",
        "site": "CommBank_Careers",
        "facets": {
            "locationCountry": ["c4f78be1a8f14da0ab49ce1162348a5e"],
            "hiringCompany": ["007f52aebee601634bb894dc0d370187"],
        },
        "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"],
    },
    {
        "name": "Lloyds Technology Centre",
        "career_url": "https://lbg.wd3.myworkdayjobs.com/en-US/Lloyds_Technology_Centre?q=DevOps+Engineer",
        "ats": "workday",
        "host": "lbg.wd3.myworkdayjobs.com",
        "tenant": "lbg",
        "site": "Lloyds_Technology_Centre",
        "search_terms": ["DevOps Engineer", "DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"],
    },
    {
        "name": "Deloitte Ireland",
        "career_url": "https://deloitteie.wd3.myworkdayjobs.com/experienced_professionals",
        "ats": "workday",
        "host": "deloitteie.wd3.myworkdayjobs.com",
        "tenant": "deloitteie",
        "site": "experienced_professionals",
        "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"],
    },
    {
        "name": "PwC Global",
        "career_url": "https://pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers",
        "ats": "workday",
        "host": "pwc.wd3.myworkdayjobs.com",
        "tenant": "pwc",
        "site": "Global_Experienced_Careers",
        "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"],
    },
    {
        "name": "PwC US",
        "career_url": "https://pwc.wd3.myworkdayjobs.com/US_Experienced_Careers",
        "ats": "workday",
        "host": "pwc.wd3.myworkdayjobs.com",
        "tenant": "pwc",
        "site": "US_Experienced_Careers",
        "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"],
    },

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
    {"name": "Kyndryl", "career_url": "https://kyndryl.wd5.myworkdayjobs.com/KyndrylProfessionalCareers", "ats": "workday", "host": "kyndryl.wd5.myworkdayjobs.com", "tenant": "kyndryl", "site": "KyndrylProfessionalCareers", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Synechron", "career_url": "https://synechron.wd1.myworkdayjobs.com/SynechronCareers", "ats": "workday", "host": "synechron.wd1.myworkdayjobs.com", "tenant": "synechron", "site": "SynechronCareers", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "NVIDIA", "career_url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite", "ats": "workday", "host": "nvidia.wd5.myworkdayjobs.com", "tenant": "nvidia", "site": "NVIDIAExternalCareerSite", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Intel", "career_url": "https://intel.wd1.myworkdayjobs.com/External", "ats": "workday", "host": "intel.wd1.myworkdayjobs.com", "tenant": "intel", "site": "External", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Qualcomm", "career_url": "https://qualcomm.wd12.myworkdayjobs.com/External", "ats": "workday", "host": "qualcomm.wd12.myworkdayjobs.com", "tenant": "qualcomm", "site": "External", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Pfizer", "career_url": "https://pfizer.wd1.myworkdayjobs.com/PfizerCareers", "ats": "workday", "host": "pfizer.wd1.myworkdayjobs.com", "tenant": "pfizer", "site": "PfizerCareers", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {
        "name": "SAP",
        "career_url": "https://jobs.sap.com/go/Development-and-Technology/4943701/",
        "ats": "html",
        "list_url": "https://jobs.sap.com/go/Development-and-Technology/4943701/",
        "job_link_pattern": r"/(?:job|jobs)(?:/|[?#-]).+",
        "max_detail_pages": 50,
    },
    {
        "name": "Dover Corporation",
        "career_url": "https://careers.dovercorporation.com/go/View-All-Jobs/2830601/",
        "ats": "html",
        "list_url": "https://careers.dovercorporation.com/go/View-All-Jobs/2830601/",
        "job_link_pattern": r"/(?:job|jobs)(?:/|[?#-]).+",
        "max_detail_pages": 50,
    },
    {"name": "Johnson & Johnson", "career_url": "https://jj.wd5.myworkdayjobs.com/JJ", "ats": "workday", "host": "jj.wd5.myworkdayjobs.com", "tenant": "jj", "site": "JJ", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Medtronic", "career_url": "https://medtronic.wd1.myworkdayjobs.com/MedtronicCareers", "ats": "workday", "host": "medtronic.wd1.myworkdayjobs.com", "tenant": "medtronic", "site": "MedtronicCareers", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Abbott", "career_url": "https://abbott.wd5.myworkdayjobs.com/abbottcareers", "ats": "workday", "host": "abbott.wd5.myworkdayjobs.com", "tenant": "abbott", "site": "abbottcareers", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Roche", "career_url": "https://roche.wd3.myworkdayjobs.com/roche-ext", "ats": "workday", "host": "roche.wd3.myworkdayjobs.com", "tenant": "roche", "site": "roche-ext", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "GE Healthcare", "career_url": "https://gehc.wd5.myworkdayjobs.com/GEHC_ExternalSite", "ats": "workday", "host": "gehc.wd5.myworkdayjobs.com", "tenant": "gehc", "site": "GEHC_ExternalSite", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Intuitive", "career_url": "https://intuitive.wd1.myworkdayjobs.com/irtc_careers", "ats": "workday", "host": "intuitive.wd1.myworkdayjobs.com", "tenant": "intuitive", "site": "irtc_careers", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Novartis", "career_url": "https://novartis.wd3.myworkdayjobs.com/Novartis_Careers", "ats": "workday", "host": "novartis.wd3.myworkdayjobs.com", "tenant": "novartis", "site": "Novartis_Careers", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "AstraZeneca", "career_url": "https://astrazeneca.wd3.myworkdayjobs.com/Careers", "ats": "workday", "host": "astrazeneca.wd3.myworkdayjobs.com", "tenant": "astrazeneca", "site": "Careers", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Sanofi", "career_url": "https://sanofi.wd3.myworkdayjobs.com/SanofiCareers", "ats": "workday", "host": "sanofi.wd3.myworkdayjobs.com", "tenant": "sanofi", "site": "SanofiCareers", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Bristol Myers Squibb", "career_url": "https://bristolmyerssquibb.wd5.myworkdayjobs.com/BMS", "ats": "workday", "host": "bristolmyerssquibb.wd5.myworkdayjobs.com", "tenant": "bristolmyerssquibb", "site": "BMS", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Illumina", "career_url": "https://illumina.wd1.myworkdayjobs.com/illumina-careers", "ats": "workday", "host": "illumina.wd1.myworkdayjobs.com", "tenant": "illumina", "site": "illumina-careers", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Hitachi", "career_url": "https://hitachi.wd1.myworkdayjobs.com/hitachi", "ats": "workday", "host": "hitachi.wd1.myworkdayjobs.com", "tenant": "hitachi", "site": "hitachi", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Micron", "career_url": "https://micron.wd1.myworkdayjobs.com/External", "ats": "workday", "host": "micron.wd1.myworkdayjobs.com", "tenant": "micron", "site": "External", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Siemens Healthineers", "career_url": "https://onehealthineers.wd3.myworkdayjobs.com/SHSJB", "ats": "workday", "host": "onehealthineers.wd3.myworkdayjobs.com", "tenant": "onehealthineers", "site": "SHSJB", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Rockwell Automation", "career_url": "https://rockwellautomation.wd1.myworkdayjobs.com/External_Rockwell_Automation", "ats": "workday", "host": "rockwellautomation.wd1.myworkdayjobs.com", "tenant": "rockwellautomation", "site": "External_Rockwell_Automation", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Workday", "career_url": "https://workday.wd5.myworkdayjobs.com/Workday", "ats": "workday", "host": "workday.wd5.myworkdayjobs.com", "tenant": "workday", "site": "Workday", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Genpact", "career_url": "https://genpact.wd108.myworkdayjobs.com/External_Careers", "ats": "workday", "host": "genpact.wd108.myworkdayjobs.com", "tenant": "genpact", "site": "External_Careers", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {"name": "Arm", "ats": "jibe", "base_url": "https://careers.arm.com", "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"]},
    {
        "name": "AMD",
        "career_url": "https://careers.amd.com",
        "ats": "jibe_api",
        "base_url": "https://careers.amd.com",
        "job_path": "/careers-home/jobs/{slug}",
        "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"],
    },

    # UAE recruitment agencies requested by the user. Prefer their public job
    # feeds where available; the HTML targets parse linked job detail pages.
    {
        "name": "TASC Outsourcing",
        "career_url": "https://tascoutsourcing.com/en/vacancies?query=DevOps&page=1",
        "ats": "tasc",
        "base_url": "https://tascoutsourcing.com",
        "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"],
    },
    {
        "name": "Caliberly",
        "career_url": "https://careers-page.com/caliberly#openings",
        "ats": "manatal",
        "slug": "caliberly",
        "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"],
    },
    {
        "name": "Emaar Hospitality Group",
        "career_url": "https://emhm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs?keyword=DevOps&location=United+Arab+Emirates&locationId=300000000346209&locationLevel=country&mode=location",
        "ats": "oracle",
        "host": "emhm.fa.em2.oraclecloud.com",
        "site": "CX_1001",
        "location_id": "300000000346209",
        "search_terms": ["DevOps", "SRE", "Cloud", "Kubernetes", "Terraform", "Platform"],
    },
    {"name": "Agile Consultants", "ats": "html", "career_url": "https://www.agileconsultants.ae/jobs", "list_url": "https://www.agileconsultants.ae/jobs", "job_link_pattern": r"/jobs/(?!$)[^/#?]+$"},
    {"name": "Michael Page UAE", "ats": "html", "career_url": "https://www.michaelpage.ae/jobs/technology", "list_url": "https://www.michaelpage.ae/jobs/technology", "job_link_pattern": r"/job-detail/"},
    {"name": "AIQU", "ats": "html", "career_url": "https://aiqusolutions.com/vacancies", "list_url": "https://aiqusolutions.com/vacancies", "job_link_pattern": r"/vacancies/(?!$)[^/#?]+$"},
    {"name": "RFS HR Consultancy", "ats": "wordpress", "career_url": "https://rfsonshr.com/jobs/", "base_url": "https://rfsonshr.com", "rest_type": "jobs", "job_path": "/jobs/{slug}/"},
    {"name": "ManpowerGroup UAE", "ats": "volcanic", "career_url": "https://www.manpowergroup.ae/jobs", "base_url": "https://www.manpowergroup.ae", "job_path": "/job/{slug}"},
    {"name": "Adecco UAE", "ats": "html", "career_url": "https://www.adecco.com/en-ae/middle-east-jobs", "list_url": "https://www.adecco.com/en-ae/middle-east-jobs", "job_link_pattern": r"/en-ae/(?:job|jobs)/|/en-ae/middle-east-jobs/[^/#?]+"},
    {"name": "Salt UAE", "ats": "html", "career_url": "https://welovesalt.com/jobs", "list_url": "https://welovesalt.com/jobs", "job_link_pattern": r"/jobs/(?!$)[^/#?]+/?$"},
    {"name": "Marc Ellis", "ats": "wordpress", "career_url": "https://www.marc-ellis.com/jobs/", "base_url": "https://www.marc-ellis.com", "rest_type": "job-listings", "job_path": "/jobs/{slug}/"},

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

    # Established employers operating from Bhartiya City, Bengaluru.
    {"name": "MR Cooper / Rocket India", "ats": "html", "career_url": "https://careers.rocket.com/in/en/search-results", "list_url": "https://careers.rocket.com/in/en/search-results", "job_link_pattern": r"/(?:job|jobs)/.+", "max_detail_pages": 50},
    {"name": "NTT Ltd", "ats": "html", "career_url": "https://www.global.ntt/about-us/join-us/careers/", "list_url": "https://www.global.ntt/about-us/join-us/careers/", "job_link_pattern": r"/(?:job|jobs|careers)/.+", "max_detail_pages": 50},
    {"name": "7-Eleven Global Solution Center India", "ats": "html", "career_url": "https://7-elevengsc.com/about-us/", "list_url": "https://7-elevengsc.com/about-us/", "job_link_pattern": r"/(?:job|jobs|openings|vacancies|candidate)/.+", "max_detail_pages": 50},
    {"name": "Blend Labs", "ats": "html", "career_url": "https://blend.com/company/careers/job-openings/", "list_url": "https://blend.com/company/careers/job-openings/", "job_link_pattern": r"/company/careers/job-openings/.+", "max_detail_pages": 50},
    {"name": "Giant Eagle GCC", "ats": "html", "career_url": "https://jobs.gianteagle.com/in/hi", "list_url": "https://jobs.gianteagle.com/in/hi", "job_link_pattern": r"/(?:in|us)/(?:en|hi)/job/.+", "max_detail_pages": 50},
    {"name": "Takeda Innovation Capability Center", "ats": "html", "career_url": "https://jobs.takeda.com/innovation-capability-centers", "list_url": "https://jobs.takeda.com/innovation-capability-centers", "job_link_pattern": r"/(?:job|jobs)/.+", "max_detail_pages": 50},
    {"name": "TresVista Analytics", "ats": "html", "career_url": "https://www.tresvista.com/careers/", "list_url": "https://www.tresvista.com/careers/", "job_link_pattern": r"/(?:job|jobs|careers)/.+", "max_detail_pages": 50},
]

# Direct posting URLs that repair known legacy records where only a company's
# career homepage was stored. Keys are normalized company/title pairs.
DIRECT_JOB_URL_OVERRIDES = {
    (
        "synopsys",
        "senior staff site reliability engineer",
    ): "https://synopsys.avature.net/careers/Login?formValues=&jobId=17592&source=&tags=&user=",
}

# Official career pages for 30 major IT services and consulting companies.
# ATS-backed entries are also added to COMPANY_CAREER_TARGETS when the site has
# a public endpoint supported by the scraper.
SERVICE_BASED_COMPANY_CAREER_PAGE_URLS = {
    "Accenture": "https://www.accenture.com/in-en/careers/jobsearch",
    "Tata Consultancy Services": "https://www.tcs.com/careers/india",
    "Infosys": "https://career.infosys.com/",
    "Wipro": "https://careers.wipro.com/",
    "HCLTech": "https://careers.hcltech.com/",
    "Cognizant": "https://careers.cognizant.com/india-en/",
    "Capgemini": "https://www.capgemini.com/in-en/careers/",
    "Tech Mahindra": "https://careers.techmahindra.com/",
    "LTIMindtree": "https://careers.ltimindtree.com/",
    "Mphasis": "https://careers.mphasis.com/",
    "Persistent Systems": "https://careers.persistent.com/",
    "Coforge": "https://careers.coforge.com/",
    "Hexaware": "https://jobs.hexaware.com/",
    "Birlasoft": "https://www.birlasoft.com/careers",
    "KPIT Technologies": "https://www.kpit.com/careers-overview/",
    "Zensar Technologies": "https://www.zensar.com/careers",
    "Sonata Software": "https://www.sonata-software.com/careers",
    "Cyient": "https://www.cyient.careers/",
    "NTT DATA": "https://careers-inc.nttdata.com/",
    "DXC Technology": "https://careers.dxc.com/",
    "CGI": "https://www.cgi.com/en/careers",
    "Genpact": "https://genpact.wd108.myworkdayjobs.com/External_Careers",
    "EPAM Systems": "https://careers.epam.com/en/jobs",
    "Thoughtworks": "https://www.thoughtworks.com/careers/jobs",
    "Publicis Sapient": "https://careers.publicissapient.com/",
    "Deloitte": "https://www.deloitte.com/global/en/careers/job-search.html",
    "PwC": "https://www.pwc.com/gx/en/careers.html",
    "EY": "https://careers.ey.com/",
    "KPMG": "https://kpmg.com/xx/en/careers/job-search.html",
    "IBM": "https://www.ibm.com/careers",
}

# Official career page URL catalog requested by the user. Not every URL has a
# public ATS API connector yet; COMPANY_CAREER_TARGETS above controls what is
# actively scraped today, while this catalog preserves the requested sources for
# incremental connector coverage.
COMPANY_CAREER_PAGE_URLS = {
    **SERVICE_BASED_COMPANY_CAREER_PAGE_URLS,
    **NON_STARTUP_PRODUCT_COMPANY_CAREER_PAGE_URLS,
    "TASC Outsourcing": "https://tascoutsourcing.com/en/vacancies?query=DevOps&page=1",
    "Caliberly": "https://careers-page.com/caliberly#openings",
    "Agile Consultants": "https://www.agileconsultants.ae/jobs",
    "Michael Page UAE": "https://www.michaelpage.ae/jobs/technology",
    "AIQU": "https://aiqusolutions.com/vacancies",
    "Emaar Hospitality Group": "https://emhm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs?keyword=DevOps&location=United+Arab+Emirates&locationId=300000000346209&locationLevel=country&mode=location",
    "RFS HR Consultancy": "https://rfsonshr.com/jobs/",
    "ManpowerGroup UAE": "https://www.manpowergroup.ae/jobs",
    "Adecco UAE": "https://www.adecco.com/en-ae/middle-east-jobs",
    "Salt UAE": "https://welovesalt.com/jobs",
    "Marc Ellis": "https://www.marc-ellis.com/jobs/",
    "MR Cooper / Rocket India": "https://careers.rocket.com/in/en/search-results",
    "Kyndryl": "https://kyndryl.wd5.myworkdayjobs.com/KyndrylProfessionalCareers",
    "NTT Ltd": "https://www.global.ntt/about-us/join-us/careers/",
    "7-Eleven Global Solution Center India": "https://7-elevengsc.com/about-us/",
    "Synechron": "https://synechron.wd1.myworkdayjobs.com/SynechronCareers",
    "Blend Labs": "https://blend.com/company/careers/job-openings/",
    "Giant Eagle GCC": "https://jobs.gianteagle.com/in/hi",
    "Takeda Innovation Capability Center": "https://jobs.takeda.com/innovation-capability-centers",
    "TresVista Analytics": "https://www.tresvista.com/careers/",
    "CBA India Services Private Limited": "https://cba.wd3.myworkdayjobs.com/en-US/CommBank_Careers?q=DevOps&locationCountry=c4f78be1a8f14da0ab49ce1162348a5e&hiringCompany=007f52aebee601634bb894dc0d370187",
    "Lloyds": "https://lbg.wd3.myworkdayjobs.com/en-US/Lloyds_Technology_Centre?q=DevOps+Engineer",
    "Deloitte US": "https://apply.deloitte.com/en_US/careers/SearchJobs",
    "Deloitte Ireland": "https://deloitteie.wd3.myworkdayjobs.com/experienced_professionals",
    "KPMG US": "https://www.kpmguscareers.com/job-search/",
    "KPMG Global Services": "https://ejgk.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_3",
    "EY Global": "https://eyglobal.yello.co/job_boards/c1riT--B2O-KySgYWsZO1Q",
    "PwC Global": "https://pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers",
    "PwC US": "https://pwc.wd3.myworkdayjobs.com/US_Experienced_Careers",
    "Google": "https://careers.google.com",
    "Microsoft": "https://careers.microsoft.com",
    "Amazon (AWS)": "https://www.amazon.jobs",
    "Apple": "https://jobs.apple.com",
    "Meta": "https://www.metacareers.com",
    "Netflix": "https://explore.jobs.netflix.net",
    "ASML": "https://www.asml.com/en/careers/find-your-job",
    "NVIDIA": "https://www.nvidia.com/en-us/about-nvidia/careers",
    "OpenAI": "https://openai.com/careers",
    "Adobe": "https://careers.adobe.com",
    "Atlassian": "https://www.atlassian.com/company/careers",
    "ServiceNow": "https://careers.servicenow.com",
    "Salesforce": "https://careers.salesforce.com",
    "SAP": "https://www.sap.com/about/careers.html",
    "Oracle": "https://careers.oracle.com",
    "Cisco": "https://jobs.cisco.com",
    "Intel": "https://jobs.intel.com",
    "AMD": "https://careers.amd.com",
    "Qualcomm": "https://www.qualcomm.com/company/careers",
    "Texas Instruments": "https://careers.ti.com",
    "Broadcom": "https://careers.broadcom.com",
    "VMware (Broadcom)": "https://careers.broadcom.com",
    "Red Hat": "https://www.redhat.com/en/jobs",
    "HashiCorp": "https://www.hashicorp.com/careers",
    "Cloudflare": "https://www.cloudflare.com/careers",
    "Datadog": "https://careers.datadoghq.com",
    "Snowflake": "https://careers.snowflake.com",
    "Docker": "https://www.docker.com/careers",
    "GitLab": "https://about.gitlab.com/jobs",
    "Workday": "https://workday.wd5.myworkdayjobs.com/Workday",
    "PayPal": "https://careers.pypl.com",
    "Stripe": "https://stripe.com/jobs",
    "Visa": "https://corporate.visa.com/en/careers.html",
    "Mastercard": "https://careers.mastercard.com",
    "American Express": "https://www.americanexpress.com/en-us/careers",
    "Intuit": "https://jobs.intuit.com",
    "Walmart Global Tech": "https://tech.walmart.com/content/walmart-global-tech/en_us/careers.html",
    "Target Tech": "https://india.target.com/careers",
    "Flipkart": "https://www.flipkartcareers.com",
    "PhonePe": "https://www.phonepe.com/careers",
    "Razorpay": "https://razorpay.com/jobs",
    "Freshworks": "https://www.freshworks.com/company/careers",
    "Zoho": "https://www.zoho.com/careers",
    "Swiggy": "https://careers.swiggy.com",
    "Zomato": "https://www.zomato.com/careers",
    "CRED": "https://careers.cred.club",
    "Meesho": "https://careers.meesho.com",
    "Uber": "https://www.uber.com/careers",
    "Airbnb": "https://careers.airbnb.com",
    "LinkedIn": "https://careers.linkedin.com",
    "Dropbox": "https://jobs.dropbox.com",
    "HubSpot": "https://www.hubspot.com/careers",
    "Signify": "https://www.careers.signify.com",
    "Bosch": "https://www.bosch.in/careers/",
    "Volvo Group": "https://jobs.volvogroup.com",
    "Ford Motor": "https://www.careers.ford.com/search-jobs",
    "Mercedes-Benz": "https://group.mercedes-benz.com/careers/",
    "BMW": "https://jobs.bmwgroup.com/job_search?language=en&locale=en_US",
    "Toyota Motor": "https://careers.toyota.com/us/en",
    "Caterpillar (CAT)": "https://careers.caterpillar.com",
    "Honeywell": "https://careers.honeywell.com",
    "Philips": "https://www.careers.philips.com",
    "Siemens": "https://jobs.siemens.com",
    "GE Aerospace": "https://jobs.geaerospace.com",
    "Shell": "https://www.shell.com/careers.html",
    "Palo Alto Networks": "https://jobs.paloaltonetworks.com",
    "CrowdStrike": "https://www.crowdstrike.com/careers",
    "Zscaler": "https://www.zscaler.com/careers",
    "Fortinet": "https://www.fortinet.com/corporate/careers",
    "Juniper Networks": "https://careers.juniper.net",
    "Arista Networks": "https://www.arista.com/en/careers",
    "Pure Storage": "https://www.purestorage.com/company/careers.html",
    "NetApp": "https://www.netapp.com/company/careers",
    "Dell Technologies": "https://jobs.dell.com",
    "HPE (Hewlett Packard Enterprise)": "https://careers.hpe.com",
    "Lenovo": "https://jobs.lenovo.com",
    "Splunk": "https://www.splunk.com/en_us/careers.html",
    "MongoDB": "https://www.mongodb.com/company/careers",
    "Confluent": "https://careers.confluent.io",
    "Elastic": "https://www.elastic.co/careers",
    "Redis": "https://redis.io/careers",
    "Okta": "https://www.okta.com/company/careers/",
    "PagerDuty": "https://careers.pagerduty.com",
    "New Relic": "https://newrelic.com/careers",
    "JPMorgan Chase": "https://careers.jpmorgan.com",
    "Goldman Sachs": "https://www.goldmansachs.com/careers",
    "Morgan Stanley": "https://www.morganstanley.com/careers",
    "Commonwealth Bank": "https://cba.wd3.myworkdayjobs.com/CommBank_Careers",
    "Capital One": "https://www.capitalonecareers.com",
    "Pfizer": "https://www.pfizer.com/about/careers",
    "Eli Lilly": "https://jobsearch.lilly.com/",
    "Hitachi": "https://careers.hitachi.com",
    "Hitachi Vantara": "https://www.hitachivantara.com/en-us/company/careers.html",
    "Roche": "https://careers.roche.com",
    "Johnson & Johnson": "https://www.careers.jnj.com/en/",
    "Medtronic": "https://www.medtronic.com/in-en/our-company/careers.html",
    "Thermo Fisher Scientific": "https://jobs.thermofisher.com/global/en",
    "Abbott": "https://www.jobs.abbott",
    "Siemens Healthineers": "https://www.siemens-healthineers.com/careers",
    "GE Healthcare": "https://careers.gehealthcare.com",
    "Intuitive": "https://careers.intuitive.com/en/",
    "Nike": "https://careers.nike.com/",
    "Coca-Cola": "https://careers.coca-colacompany.com/",
    "Novartis": "https://www.novartis.com/careers",
    "AstraZeneca": "https://careers.astrazeneca.com",
    "Bayer": "https://career.bayer.com",
    "Sanofi": "https://jobs.sanofi.com",
    "Bristol Myers Squibb": "https://careers.bms.com",
    "Illumina": "https://careers.illumina.com",
    "Danaher": "https://jobs.danaher.com",
    "Caterpillar": "https://careers.caterpillar.com",
    "Schneider Electric": "https://www.se.com/careers",
    "Emerson": "https://www.emerson.com/careers",
    "Rockwell Automation": "https://www.rockwellautomation.com/careers",
    "ABB": "https://global.abb/group/en/careers",
    "Ericsson": "https://www.ericsson.com/en/careers",
    "Nokia": "https://www.nokia.com/about-us/careers",
    "Keysight Technologies": "https://jobs.keysight.com",
    "Western Digital": "https://jobs.westerndigital.com",
    "Micron": "https://careers.micron.com",
    "KLA": "https://www.kla.com/careers",
    "Applied Materials": "https://careers.appliedmaterials.com",
    "Lam Research": "https://careers.lamresearch.com",
    "Synopsys": "https://careers.synopsys.com",
    "Cadence": "https://careers.cadence.com",
    "Databricks": "https://www.databricks.com/company/careers",
    "GitHub": "https://github.careers",
    "Arctic Wolf": "https://arcticwolf.com/company/careers",
    "Tesla": "https://www.tesla.com/careers",
    "Boeing": "https://jobs.boeing.com",
    "Emirates Group": "https://www.emiratesgroupcareers.com",
    "Etihad Airways": "https://careers.etihad.com",
    "flydubai": "https://careers.flydubai.com",
    "e& (Etisalat)": "https://careers.eand.com",
    "du": "https://careers.du.ae",
    "First Abu Dhabi Bank (FAB)": "https://www.bankfab.com/en-ae/about-fab/careers",
    "Emirates NBD": "https://www.emiratesnbd.com/en/careers",
    "ADCB": "https://careers.adcb.com",
    "ADIB": "https://careers.adib.ae",
    "Mashreq": "https://www.mashreq.com/en/uae/careers",
    "Commercial Bank of Dubai": "https://careers.cbd.ae",
    "Dubai Islamic Bank": "https://careers.dib.ae",
    "Careem": "https://www.careem.com/careers",
    "Noon": "https://careers.noon.com",
    "Talabat": "https://careers.talabat.com",
    "Kitopi": "https://www.kitopi.com/careers",
    "Binance": "https://www.binance.com/en/careers",
    "OKX": "https://www.okx.com/careers",
    "Deriv": "https://deriv.com/careers",
    "ByteDance": "https://jobs.bytedance.com",
    "TikTok": "https://careers.tiktok.com",
    # Additional product-based company career pages.
    "Autodesk": "https://www.autodesk.com/careers",
    "Akamai": "https://www.akamai.com/careers",
    "Fastly": "https://www.fastly.com/about/careers",
    "DigitalOcean": "https://www.digitalocean.com/careers",
    "Equinix": "https://careers.equinix.com",
    "Nutanix": "https://www.nutanix.com/company/careers",
    "Rubrik": "https://www.rubrik.com/company/careers",
    "Cohesity": "https://www.cohesity.com/company/careers/",
    "Veeam": "https://www.veeam.com/careers.html",
    "UiPath": "https://www.uipath.com/careers",
    "Zoom": "https://careers.zoom.us",
    "Slack": "https://slack.com/careers",
    "Asana": "https://asana.com/jobs",
    "Notion": "https://www.notion.com/careers",
    "Figma": "https://www.figma.com/careers/",
    "Canva": "https://www.canva.com/careers/",
    "Miro": "https://miro.com/careers/",
    "Monday.com": "https://monday.com/careers",
    "Smartsheet": "https://www.smartsheet.com/careers",
    "Box": "https://www.box.com/about-us/careers",
    "DocuSign": "https://careers.docusign.com",
    "Zendesk": "https://www.zendesk.com/company/careers/",
    "Intercom": "https://www.intercom.com/careers",
    "ServiceTitan": "https://www.servicetitan.com/careers",
    "Samsara": "https://www.samsara.com/company/careers",
    "Toast": "https://careers.toasttab.com",
    "Block": "https://block.xyz/careers",
    "Coinbase": "https://www.coinbase.com/careers",
    "Robinhood": "https://careers.robinhood.com",
    "Plaid": "https://plaid.com/careers/",
    "Brex": "https://www.brex.com/careers",
    "Adyen": "https://careers.adyen.com",
    "Wise": "https://wise.jobs",
    "Revolut": "https://www.revolut.com/careers/",
    "Nubank": "https://international.nubank.com.br/careers/",
    "Grab": "https://www.grab.careers",
    "Gojek": "https://www.gojek.io/careers",
    "Sea Limited": "https://www.sea.com/careers",
    "Shopee": "https://careers.shopee.sg",
    "GoDaddy": "https://careers.godaddy",
    "Vercel": "https://vercel.com/careers",
    "Netlify": "https://www.netlify.com/careers/",
    "Snyk": "https://snyk.io/careers/",
    "Wiz": "https://www.wiz.io/careers",
    "Lacework": "https://www.lacework.com/careers",
    "SentinelOne": "https://www.sentinelone.com/careers/",
    "Tenable": "https://www.tenable.com/careers",
    "Rapid7": "https://www.rapid7.com/careers/",
    "Check Point": "https://www.checkpoint.com/about-us/careers/",
    "CyberArk": "https://www.cyberark.com/careers/",
    "SailPoint": "https://www.sailpoint.com/company/careers/",
    "OneTrust": "https://www.onetrust.com/careers/",
    "Grafana Labs": "https://grafana.com/about/careers/",
    "Chronosphere": "https://chronosphere.io/careers/",
    "Honeycomb": "https://www.honeycomb.io/careers",
    "Sumo Logic": "https://www.sumologic.com/company/careers/",
    "Dynatrace": "https://careers.dynatrace.com",
    "DataStax": "https://www.datastax.com/careers",
    "Cockroach Labs": "https://www.cockroachlabs.com/careers/",
    "Neo4j": "https://neo4j.com/careers/",
    "PlanetScale": "https://planetscale.com/careers",
    "Supabase": "https://supabase.com/careers",
    "Timescale": "https://www.timescale.com/careers",
    "Yugabyte": "https://www.yugabyte.com/careers/",
    "SingleStore": "https://www.singlestore.com/careers/",
    "Cloudera": "https://www.cloudera.com/about/careers.html",
    "Starburst": "https://www.starburst.io/careers/",
    "Fivetran": "https://www.fivetran.com/careers",
    "dbt Labs": "https://www.getdbt.com/careers",
    "Airbyte": "https://airbyte.com/company/careers",
    "ThoughtSpot": "https://www.thoughtspot.com/careers",
    "Qlik": "https://www.qlik.com/us/company/careers",
    "Informatica": "https://www.informatica.com/about-us/careers.html",
    "Alteryx": "https://www.alteryx.com/careers",
    "Palantir": "https://www.palantir.com/careers/",
    "Anduril": "https://www.anduril.com/careers/",
    "SpaceX": "https://www.spacex.com/careers/",
    "Blue Origin": "https://www.blueorigin.com/careers",
    "Rivian": "https://rivian.com/careers",
    "Lucid Motors": "https://lucidmotors.com/careers",
    "Waymo": "https://waymo.com/careers/",
    "Zoox": "https://zoox.com/careers/",
    "BrowserStack": "https://www.browserstack.com/careers",
    "Postman": "https://www.postman.com/company/careers/",
    "Hasura": "https://hasura.io/careers/",
    "Uniphore": "https://www.uniphore.com/careers/",
    "Chargebee": "https://www.chargebee.com/careers/",
    "Druva": "https://www.druva.com/about/careers/",
    "MoEngage": "https://www.moengage.com/careers/",
    "CleverTap": "https://clevertap.com/careers/",
    "Zeta": "https://www.zeta.tech/careers/",
    "InMobi": "https://www.inmobi.com/company/careers/",
    "Glance": "https://glance.com/careers/",
    "ShareChat": "https://sharechat.com/careers",
    "Groww": "https://groww.in/careers",
    "Zerodha": "https://zerodha.com/careers/",
    "Navi": "https://navi.com/careers",
    "Udaan": "https://careers.udaan.com",
    "MakeMyTrip": "https://careers.makemytrip.com",
    "Ather Energy": "https://www.atherenergy.com/careers",
}

# Replace discovery-only search URLs with resolver-verified official pages.
COMPANY_CAREER_PAGE_URLS.update(
    {
        name: str(target["career_url"])
        for name, target in RESOLVED_PRODUCT_COMPANY_CAREER_TARGETS.items()
        if target.get("career_url")
    }
)
# Keep unresolved discovery hints out of both the official-page catalog and the
# active scraper. They can be retried by the resolver without consuming a job
# pipeline chunk in the meantime.
COMPANY_CAREER_PAGE_URLS = {
    name: career_url
    for name, career_url in COMPANY_CAREER_PAGE_URLS.items()
    if "www.google.com/search" not in str(career_url).lower()
}

CATALOG_COMPANY_CAREER_JOB_LINK_PATTERN = (
    r"/(?:job|jobs|careers|career|positions|openings|opportunities|vacancy|vacancies)"
    r"(?:/|[?#-]).+"
)


def _catalog_company_career_targets() -> list[dict]:
    configured_names = {
        str(target.get("name") or "").strip().lower()
        for target in COMPANY_CAREER_TARGETS
        if isinstance(target, dict)
    }
    targets: list[dict] = []
    for name, career_url in COMPANY_CAREER_PAGE_URLS.items():
        if str(name).strip().lower() in configured_names:
            continue
        # Search result pages are discovery hints, never job feeds.
        if "www.google.com/search" in str(career_url).lower():
            continue
        targets.append(
            {
                "name": name,
                "ats": "html",
                "career_url": career_url,
                "list_url": career_url,
                "job_link_pattern": CATALOG_COMPANY_CAREER_JOB_LINK_PATTERN,
                "max_detail_pages": 1,
            }
        )
    return targets


COMPANY_CAREER_TARGETS.extend(
    {
        "name": name,
        **target,
    }
    for name, target in RESOLVED_PRODUCT_COMPANY_CAREER_TARGETS.items()
    if str(name).strip().lower()
    not in {
        str(existing.get("name") or "").strip().lower()
        for existing in COMPANY_CAREER_TARGETS
        if isinstance(existing, dict)
    }
)
COMPANY_CAREER_TARGETS.extend(_catalog_company_career_targets())
COMPANY_CAREER_TARGET_LIMIT = len(COMPANY_CAREER_TARGETS)
COMPANY_CAREER_TARGETS_PER_RUN = 0

# =================================================================
# PROCESSING LIMITS
# =================================================================

SCRAPING_SOURCES = [
    "linkedin",
    "company_careers",
    "naukri_gulf",
    # "careers_future"
    # "naukri",
]

JOBS_TO_SCORE_PER_RUN = 10

JOBS_TO_CUSTOMIZE_PER_RUN = 5

# 0 disables custom-resume re-scoring. Custom resume generation still runs.
JOBS_TO_RESCORE_PER_RUN = 0

MAX_JOBS_PER_SEARCH = {
    "linkedin": 20,
    "careers_future": 10,
    "company_careers": 300,
    "naukri": 10,
    "naukri_gulf": 10,
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

# Keep applied jobs visible before allowing inactive cleanup to remove them.
APPLIED_JOB_RETENTION_DAYS = 50

JOB_CHECK_LIMIT = 50

ACTIVE_CHECK_TIMEOUT = 20

ACTIVE_CHECK_MAX_RETRIES = 2

ACTIVE_CHECK_RETRY_DELAY = 10
