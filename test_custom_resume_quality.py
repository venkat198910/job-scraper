import unittest

from custom_resume_generator import (
    _clean_resume_bullets,
    build_evidence_based_summary,
    build_professional_title,
    merge_verified_skills,
)
from models import Certification, Experience, Resume


class CustomResumeQualityTests(unittest.TestCase):
    def setUp(self):
        self.resume = Resume(
            experience=[
                Experience(
                    job_title="Technical Lead",
                    company="Example",
                    description="Built AWS infrastructure with Terraform.\nManaged EKS and Jenkins pipelines.",
                )
            ],
            certifications=[Certification(name="Google Cloud Professional Cloud Architect")],
            skills=["AWS", "GCP", "Terraform", "Kubernetes", "Jenkins"],
        )

    def test_headline_does_not_claim_jd_only_gcp_delivery(self):
        title = build_professional_title(
            {"job_title": "Senior GCP DevOps Engineer", "level": "Senior", "description": "GCP and GKE"},
            self.resume,
        )
        self.assertNotIn("GCP", title)
        self.assertTrue(any(skill in title for skill in ("AWS", "Terraform", "Kubernetes", "CI/CD")))

    def test_summary_is_evidence_based_and_uses_requested_tenure(self):
        summary = build_evidence_based_summary(self.resume)
        self.assertIn("around 10 years", summary)
        self.assertIn("AWS", summary)
        self.assertNotIn("expert", summary.lower())

    def test_skill_merge_rejects_unverified_llm_skills(self):
        skills = merge_verified_skills(
            ["GCP", "Rust", "Terraform"], self.resume.skills, {"description": "GCP Terraform"}
        )
        self.assertNotIn("Rust", skills)
        self.assertEqual(skills[:2], ["GCP", "Terraform"])

    def test_common_bullet_grammar_is_repaired(self):
        cleaned = _clean_resume_bullets(
            "Lead production incident response & restored service.\n"
            "Built pipelines, accelerated deployment velocity."
        )
        self.assertIn("Led production incident response and restored service.", cleaned)
        self.assertIn("accelerating deployment velocity", cleaned)


if __name__ == "__main__":
    unittest.main()
