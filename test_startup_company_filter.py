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

    def test_filter_can_be_disabled(self):
        with patch.object(scraper.config, "ESTABLISHED_COMPANIES_ONLY", False):
            self.assertTrue(scraper._job_is_from_established_company({"company": "Any Startup"}))


if __name__ == "__main__":
    unittest.main()
