import ast
from pathlib import Path
import unittest


def _load_experience_normalizer():
    source_path = Path(__file__).with_name("custom_resume_generator.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Import) and any(alias.name == "re" for alias in node.names):
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CUSTOM_RESUME_TOTAL_EXPERIENCE"
            for target in node.targets
        ):
            selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {
            "_configured_total_experience_phrase",
            "_enforce_total_experience",
        }:
            selected.append(node)

    namespace = {}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace["_enforce_total_experience"]


_enforce_total_experience = _load_experience_normalizer()


class TotalExperienceNormalizationTests(unittest.TestCase):
    def test_replaces_numeric_experience_once(self):
        self.assertEqual(
            _enforce_total_experience("SRE with 9+ years of experience."),
            "SRE with around 10 years of experience.",
        )

    def test_preserves_already_normalized_phrase(self):
        self.assertEqual(
            _enforce_total_experience("SRE with around 10 years of experience."),
            "SRE with around 10 years of experience.",
        )

    def test_repairs_existing_duplicate(self):
        self.assertEqual(
            _enforce_total_experience("SRE with around around 10 years of experience."),
            "SRE with around 10 years of experience.",
        )


if __name__ == "__main__":
    unittest.main()
