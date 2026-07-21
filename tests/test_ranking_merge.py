"""Regression tests for RankingAgent evidence merging.

Guards against a bug where catalog evidence (keyed by source_id) and
PubMed/analogical evidence (keyed by feature_name) for the *same* HIF
created two separate CandidateHIF objects instead of merging into one.
The PubMed-only orphan candidate had no catalog score, so it almost
never survived the top-N cutoff, meaning PubMed evidence found by the
LiteratureAgent silently never affected the final rankings.
"""

from agents.ranking_agent import RankingAgent
from models.schemas import FeatureCategory, FeatureType, NormalizedPathologyFeature


def _catalog_feature(feature_name: str, source_id: str) -> NormalizedPathologyFeature:
    return NormalizedPathologyFeature(
        source="HECatalog",
        source_id=source_id,
        feature_name=feature_name,
        feature_category=FeatureCategory.IMMUNE_PHENOTYPE,
        evidence_type=FeatureType.PREDICTIVE,
        evidence_level="B",
        claim="Catalog claim.",
    )


def _pubmed_feature(feature_name: str, pmid: str, analogical: bool) -> NormalizedPathologyFeature:
    return NormalizedPathologyFeature(
        source="PubMed-Analogical" if analogical else "PubMed",
        source_id=f"PMID:{pmid}",
        feature_name=feature_name,
        feature_category=FeatureCategory.IMMUNE_PHENOTYPE,
        evidence_type=FeatureType.PREDICTIVE,
        claim="Literature claim.",
    )


def test_pubmed_evidence_merges_into_matching_catalog_candidate() -> None:
    """PubMed/analogical hits for a HIF must land on the same candidate as its catalog entry."""
    catalog_feat = _catalog_feature("Immune Phenotype Classification", "he_immune_phenotype")
    pubmed_feats = [
        _pubmed_feature("Immune Phenotype Classification", pmid, analogical=True)
        for pmid in ["11111111", "22222222", "33333333"]
    ]

    ranked = RankingAgent().run(
        all_evidence=[catalog_feat, *pubmed_feats],
        moa_class="checkpoint",
        top_n=10,
    )

    matches = [c for c in ranked if c.feature_name == "Immune Phenotype Classification"]
    assert len(matches) == 1, "catalog and PubMed evidence for the same HIF must not split into duplicates"

    candidate = matches[0]
    assert candidate.in_he_catalog is True
    assert len(candidate.__dict__.get("analogical_ids", [])) == 3
    assert len(candidate.evidence_items) == 4


def test_direct_pubmed_hits_also_merge_with_catalog() -> None:
    """Direct (non-analogical) PubMed hits merge into the same candidate too."""
    catalog_feat = _catalog_feature("Stromal TIL Score", "he_stromal_til")
    pubmed_feat = _pubmed_feature("Stromal TIL Score", "44444444", analogical=False)

    ranked = RankingAgent().run(
        all_evidence=[catalog_feat, pubmed_feat],
        moa_class="checkpoint",
        top_n=10,
    )

    matches = [c for c in ranked if c.feature_name == "Stromal TIL Score"]
    assert len(matches) == 1
    assert matches[0].pubmed_ids == ["44444444"]
    assert matches[0].in_he_catalog is True
