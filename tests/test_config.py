"""Unit tests for deterministic mechanism-of-action routing."""

import pytest

from config import EVIDENCE_LEVEL_WEIGHTS, get_moa_class


@pytest.mark.parametrize(
    ("drug_name", "moa", "expected"),
    [
        ("pembrolizumab", "PD-1 checkpoint inhibitor", "checkpoint"),
        ("olaparib", "PARP1/2 inhibitor", "ddr"),
        ("belzutifan", "HIF-2alpha inhibitor", "hypoxia"),
        ("trastuzumab deruxtecan", "antibody-drug conjugate", "adc"),
        ("ivonescimab", "PD-1/VEGF bispecific antibody", "bispecific"),
        ("candidate-001", "novel target", "default"),
    ],
)
def test_get_moa_class_routes_expected_mechanisms(
    drug_name: str, moa: str, expected: str
) -> None:
    """Classify representative mechanisms into their documented weight buckets."""
    assert get_moa_class(drug_name, moa) == expected


def test_evidence_weights_are_monotonic() -> None:
    """Keep stronger evidence levels more influential than weaker evidence."""
    assert (
        EVIDENCE_LEVEL_WEIGHTS["A"]
        > EVIDENCE_LEVEL_WEIGHTS["B"]
        > EVIDENCE_LEVEL_WEIGHTS["C"]
        > EVIDENCE_LEVEL_WEIGHTS["D"]
    )
