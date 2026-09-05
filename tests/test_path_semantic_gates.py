from __future__ import annotations

import unittest

from wq_alpha_os.research.field_profiles import FieldProfile
from wq_alpha_os.research.path_templates import eligible_templates


def _profile(*, cadence: str, sparsity: str, theme: str = "analyst_revision", form: str = "score") -> FieldProfile:
    return FieldProfile(
        field_key="f",
        name="f",
        dataset_name="d",
        data_type="MATRIX",
        economic_theme=theme,
        secondary_themes=(),
        semantic_form=form,
        update_cadence=cadence,
        signedness="signed",
        unit_family="score",
        sparsity_class=sparsity,
        peer_dependence="high",
        direction_prior="ambiguous",
        direction_confidence="low",
        horizon_prior=(20, 63, 126) if cadence == "medium" else (126, 252, 504, 756),
        preferred_roles=(),
        discouraged_roles=(),
        classification_source="test",
        confidence=0.9,
    )


class PathSemanticGateTests(unittest.TestCase):
    def test_information_staleness_rejects_medium_continuous_score(self):
        profile = _profile(cadence="medium", sparsity="dense")
        paths = {item.id for item in eligible_templates([profile])}
        self.assertNotIn("information_staleness", paths)

    def test_information_staleness_accepts_slow_stepwise_field(self):
        profile = _profile(cadence="slow", sparsity="slow_stepwise")
        paths = {item.id for item in eligible_templates([profile])}
        self.assertIn("information_staleness", paths)


if __name__ == "__main__":
    unittest.main()
