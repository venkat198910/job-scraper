import unittest
from unittest.mock import MagicMock, patch

import scraper


class NaukriGulfFallbackTests(unittest.TestCase):
    @patch("scraper._linkedin_job_matches_experience_range", return_value=True)
    @patch("scraper._job_matches_excluded_title_keywords", return_value=False)
    @patch("scraper._job_key_exists", return_value=False)
    @patch("scraper.supabase_utils.get_existing_jobs_from_supabase", return_value=(set(), set()))
    @patch("scraper._fetch_naukri_gulf_jobs_with_browser")
    @patch("scraper.requests.get")
    def test_http_200_javascript_shell_uses_browser_fallback(
        self,
        mock_get,
        mock_browser,
        _mock_existing,
        _mock_exists,
        _mock_excluded,
        _mock_experience,
    ):
        response = MagicMock()
        response.status_code = 200
        response.text = "<html><head><title>Naukrigulf</title></head><body></body></html>"
        response.raise_for_status.return_value = None
        mock_get.return_value = response
        browser_job = {
            "job_id": "naukrigulf-123",
            "company": "Established UAE Employer",
            "job_title": "Senior DevOps Engineer",
            "location": "Dubai, United Arab Emirates",
        }
        mock_browser.return_value = [browser_job]

        jobs = scraper.process_naukri_gulf_query(
            "DevOps Engineer", "Dubai, United Arab Emirates", limit=10
        )

        self.assertEqual(jobs, [browser_job])
        mock_browser.assert_called_once_with(
            "DevOps Engineer", "Dubai, United Arab Emirates", limit=10
        )


if __name__ == "__main__":
    unittest.main()
