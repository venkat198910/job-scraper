import unittest

from application_assistant import build_apply_url


class WorkdayDirectJobUrlTests(unittest.TestCase):
    def test_uses_direct_url_preserved_in_job_notes(self):
        direct_url = (
            "https://example.wd5.myworkdayjobs.com/External/"
            "job/India-Bengaluru/Senior-Site-Reliability-Engineer_JR1234567"
        )
        job = {
            "job_id": "workday-example-External-jr1234567",
            "provider": "company_careers_workday",
            "company": "Example Corp",
            "job_title": "Senior Site Reliability Engineer",
            "notes": {"apply_url": direct_url},
        }

        self.assertEqual(build_apply_url(job), direct_url)

    def test_replaces_stale_nvidia_requisition_with_active_posting(self):
        job = {
            "job_id": "workday-nvidia-NVIDIAExternalCareerSite-jr2022689",
            "provider": "company_careers_workday",
            "company": "NVIDIA",
            "job_title": "Senior Site Reliability Engineering - Storage",
            "notes": {
                "apply_url": (
                    "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/"
                    "job/India-Bengaluru/Senior-Site-Reliability-Engineering---Storage_JR2022689"
                )
            },
        }

        self.assertTrue(build_apply_url(job).endswith("_JR2018610"))


if __name__ == "__main__":
    unittest.main()
