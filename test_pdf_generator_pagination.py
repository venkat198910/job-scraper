import io
import unittest

import pdfplumber

from models import Experience, Resume
from pdf_generator import _reference_top_padding, create_resume_pdf


class ResumePaginationTests(unittest.TestCase):
    def test_experience_page_break_is_based_on_content_height(self):
        resume = Resume(
            name="Test Candidate",
            experience=[
                Experience(
                    company=f"Company {index}",
                    job_title="DevOps Engineer",
                    description="Improved deployment reliability with automated delivery pipelines.",
                )
                for index in range(1, 6)
            ],
        )

        with pdfplumber.open(io.BytesIO(create_resume_pdf(resume))) as pdf:
            self.assertEqual(len(pdf.pages), 1)
            page_text = pdf.pages[0].extract_text() or ""

        self.assertIn("Company 5", page_text)

    def test_top_padding_tightens_for_content_heavy_resume(self):
        short_resume = Resume(summary="Short summary")
        long_resume = Resume(summary="Detailed summary " * 400)

        self.assertGreater(_reference_top_padding(short_resume), _reference_top_padding(long_resume))
        self.assertGreaterEqual(_reference_top_padding(long_resume), 30.0)
        self.assertLessEqual(_reference_top_padding(short_resume), 46.0)

if __name__ == "__main__":
    unittest.main()
