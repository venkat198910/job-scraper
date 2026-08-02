import unittest

import config
from product_company_career_catalog import NON_STARTUP_PRODUCT_COMPANY_CAREER_PAGE_URLS
from resolved_product_company_career_targets import RESOLVED_PRODUCT_COMPANY_CAREER_TARGETS
from scripts.resolve_product_company_careers import _detect_ats


class CompanyCareerResolutionTests(unittest.TestCase):
    def test_google_discovery_pages_are_never_active_targets(self):
        for target in config.COMPANY_CAREER_TARGETS:
            urls = f"{target.get('career_url', '')} {target.get('list_url', '')}".lower()
            self.assertNotIn("www.google.com/search", urls, target.get("name"))

    def test_target_names_are_unique(self):
        names = [str(target.get("name") or "").strip().lower() for target in config.COMPANY_CAREER_TARGETS]
        self.assertEqual(len(names), len(set(names)))

    def test_discovery_catalog_is_resolved_except_non_hiring_holding_company(self):
        placeholders = {
            name
            for name, url in NON_STARTUP_PRODUCT_COMPANY_CAREER_PAGE_URLS.items()
            if "www.google.com/search" in url.lower()
        }
        self.assertEqual(placeholders - set(RESOLVED_PRODUCT_COMPANY_CAREER_TARGETS), {"Berkshire Hathaway"})

    def test_supported_ats_urls_are_detected(self):
        self.assertEqual(_detect_ats("https://jobs.lever.co/example")["slug"], "example")
        self.assertEqual(_detect_ats("https://boards.greenhouse.io/example")["slug"], "example")
        workday = _detect_ats("https://example.wd5.myworkdayjobs.com/External")
        self.assertEqual(workday["tenant"], "example")
        self.assertEqual(workday["site"], "External")

    def test_workday_login_path_is_not_treated_as_a_site(self):
        self.assertIsNone(_detect_ats("https://example.wd5.myworkdayjobs.com/jobs/login"))


if __name__ == "__main__":
    unittest.main()
