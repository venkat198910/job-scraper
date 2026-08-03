import unittest
from unittest.mock import patch

import scraper


class EstablishedCompanyFilterTests(unittest.TestCase):
    def setUp(self):
        scraper._ESTABLISHED_COMPANY_NAME_CACHE = None

    def test_keeps_curated_established_company(self):
        self.assertTrue(scraper._job_is_from_established_company({"company": "Microsoft"}))

    def test_keeps_known_company_name_variant(self):
        self.assertTrue(
            scraper._job_is_from_established_company(
                {"company": "Amazon Web Services (AWS) India"}
            )
        )

    def test_rejects_unknown_startup(self):
        self.assertFalse(
            scraper._job_is_from_established_company(
                {"company": "Tiny Seed Startup Labs"}
            )
        )

    def test_rejects_confidential_or_missing_company(self):
        self.assertFalse(scraper._job_is_from_established_company({"company": "Confidential"}))
        self.assertFalse(scraper._job_is_from_established_company({}))

    def test_keeps_non_startup_uae_employer_not_yet_in_catalog(self):
        self.assertTrue(
            scraper._job_is_from_established_company(
                {"company": "Confidential", "location": "Dubai, United Arab Emirates"}
            )
        )

    def test_rejects_explicit_uae_startup(self):
        self.assertFalse(
            scraper._job_is_from_established_company(
                {
                    "company": "Tiny Seed Labs",
                    "location": "Abu Dhabi, United Arab Emirates",
                    "description": "Join our early-stage company",
                }
            )
        )

    def test_filter_can_be_disabled(self):
        with patch.object(scraper.config, "ESTABLISHED_COMPANIES_ONLY", False):
            self.assertTrue(scraper._job_is_from_established_company({"company": "Any Startup"}))


if __name__ == "__main__":
    unittest.main()
