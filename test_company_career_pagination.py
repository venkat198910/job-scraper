import unittest
from unittest.mock import patch

import scraper


class CompanyCareerPaginationTests(unittest.TestCase):
    def test_smartrecruiters_fetches_every_page(self):
        summaries = [
            {
                "id": str(index),
                "name": f"DevOps Engineer {index}",
                "releasedDate": "2026-08-06T00:00:00Z",
                "ref": f"https://jobs.example/{index}",
            }
            for index in range(101)
        ]
        requested_offsets = []

        def fake_fetch_json(url):
            if "?limit=" in url:
                offset = int(url.rsplit("offset=", 1)[1])
                requested_offsets.append(offset)
                return {"content": summaries[offset:offset + 100], "totalFound": len(summaries)}
            summary_id = url.rsplit("/", 1)[1]
            summary = summaries[int(summary_id)]
            return {
                **summary,
                "jobAd": {"sections": {"jobDescription": {"text": "DevOps role"}}},
                "location": {"city": "Bengaluru", "country": "in"},
            }

        with patch.object(scraper, "_fetch_json", side_effect=fake_fetch_json):
            jobs = scraper._fetch_smartrecruiters_jobs(
                {"name": "Example", "slug": "example", "career_url": "https://jobs.example"}
            )

        self.assertEqual(len(jobs), 101)
        self.assertEqual(requested_offsets, [0, 100])

    def test_workday_fetches_every_page(self):
        summaries = [
            {
                "title": f"DevOps Engineer {index}",
                "externalPath": f"/job/DevOps-Engineer-{index}_JR{index}",
                "bulletFields": [f"JR{index}"],
                "postedOn": "2026-08-06T00:00:00Z",
            }
            for index in range(21)
        ]
        requested_offsets = []

        def fake_post_json(_url, payload):
            offset = payload["offset"]
            requested_offsets.append(offset)
            return {"jobPostings": summaries[offset:offset + 20], "total": len(summaries)}

        def fake_fetch_json(url):
            index = int(url.rsplit("_JR", 1)[1])
            return {
                "jobPostingInfo": {
                    "title": f"DevOps Engineer {index}",
                    "location": "Bengaluru, India",
                    "jobDescription": "DevOps role",
                    "startDate": "2026-08-06T00:00:00Z",
                    "externalPath": summaries[index]["externalPath"],
                }
            }

        target = {
            "name": "Example",
            "host": "example.wd5.myworkdayjobs.com",
            "tenant": "example",
            "site": "External",
            "search_terms": ["DevOps"],
        }
        with (
            patch.object(scraper, "_post_json", side_effect=fake_post_json),
            patch.object(scraper, "_fetch_json", side_effect=fake_fetch_json),
        ):
            jobs = scraper._fetch_workday_jobs(target)

        self.assertEqual(len(jobs), 21)
        self.assertEqual(requested_offsets, [0, 20])


if __name__ == "__main__":
    unittest.main()
