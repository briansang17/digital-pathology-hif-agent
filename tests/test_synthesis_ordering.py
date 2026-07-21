"""Regression tests for deterministic ranking preservation during LLM synthesis."""

from agents.synthesis_agent import SynthesisAgent
from models.schemas import HIFHypothesis


def _hypothesis(rank: int, name: str, score: float) -> HIFHypothesis:
    """Create a minimal deterministic ranking result for synthesis tests."""
    return HIFHypothesis(
        rank=rank,
        feature_name=name,
        confidence_score=score,
        hypothesis=f"Fallback narrative for {name}.",
    )


def test_synthesis_only_enriches_matching_feature_narratives() -> None:
    """Keep deterministic order and metadata when an LLM returns a reordered response."""
    ranked = [
        _hypothesis(1, "Tumor-Stroma Ratio", 100.0),
        _hypothesis(2, "Stromal TIL Score", 85.0),
    ]
    llm_response = """
    [
      {"feature_name": "Stromal TIL Score", "hypothesis": "LLM narrative for TIL."},
      {"feature_name": "Tumor-Stroma Ratio", "hypothesis": "LLM narrative for TSR."}
    ]
    """

    enriched = SynthesisAgent(backend=None)._parse_and_validate(llm_response, ranked)

    assert [item.rank for item in enriched] == [1, 2]
    assert [item.feature_name for item in enriched] == [
        "Tumor-Stroma Ratio",
        "Stromal TIL Score",
    ]
    assert [item.confidence_score for item in enriched] == [100.0, 85.0]
    assert enriched[0].hypothesis == "LLM narrative for TSR."
    assert enriched[1].hypothesis == "LLM narrative for TIL."


def test_synthesis_ignores_unknown_features() -> None:
    """Prevent an LLM-only feature from entering the deterministic ranked output."""
    ranked = [_hypothesis(1, "Tumor-Stroma Ratio", 100.0)]
    llm_response = """
    [
      {"feature_name": "Invented Feature", "hypothesis": "Unsupported text."}
    ]
    """

    enriched = SynthesisAgent(backend=None)._parse_and_validate(llm_response, ranked)

    assert len(enriched) == 1
    assert enriched[0].feature_name == "Tumor-Stroma Ratio"
    assert enriched[0].hypothesis == "Fallback narrative for Tumor-Stroma Ratio."
