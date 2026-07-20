"""
Digital Pathology HIF Agent — Feature Ranking Agent
Deterministic evidence scoring engine for H&E Human-Interpretable Features.
Aggregates catalog + PubMed evidence into per-HIF CandidateHIF objects,
computes composite scores, and returns a ranked list ready for LLM synthesis.

Scoring logic (mirrors RankingAgent in oncomoa_agent):
  Catalog evidence level: A=5, B=4, C=3, D=1.5
  MOA category weight: from config.MOA_FEATURE_WEIGHTS
  PubMed hit: 0.15 per article
  Predictive vs prognostic: assigned from evidence_type flags

Example:
    agent = RankingAgent()
    ranked = agent.run(all_evidence, moa_class="checkpoint", top_n=10)
    hypotheses = agent.to_hypotheses(ranked)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from config import (
    EVIDENCE_LEVEL_WEIGHTS,
    PUBMED_HIT_WEIGHT,
    MOA_FEATURE_WEIGHTS,
    PREDICTIVE_THRESHOLD,
    PROGNOSTIC_THRESHOLD,
    DEFAULT_TOP_N,
)
from models.schemas import (
    NormalizedPathologyFeature,
    CandidateHIF,
    FeatureType,
    HIFHypothesis,
    HIFRankingRationale,
    SupportingEvidence,
)

logger = logging.getLogger(__name__)


def _get_evidence_level_order(level: str) -> int:
    """Return sort order for evidence levels (A=0 is best)."""
    return {"A": 0, "B": 1, "C": 2, "D": 3}.get(level, 4)


class RankingAgent:
    """
    Deterministic H&E HIF scoring and ranking engine.
    Operates entirely on normalized evidence — no LLM required.
    Mirrors RankingAgent in oncomoa_agent.
    """

    def run(
        self,
        all_evidence: list[NormalizedPathologyFeature],
        moa_class: str = "default",
        top_n: int = DEFAULT_TOP_N,
    ) -> list[CandidateHIF]:
        """
        Score and rank candidate H&E HIFs from all evidence sources.

        Args:
            all_evidence: Normalized features from catalog + PubMed.
            moa_class: MOA class for category weighting.
            top_n: Number of top HIFs to return.

        Returns:
            Ranked list of CandidateHIF objects (normalized scores 0–100).
        """
        logger.info(
            "[RankingAgent] Scoring %d evidence items | moa_class=%s",
            len(all_evidence), moa_class,
        )

        moa_weights = MOA_FEATURE_WEIGHTS.get(moa_class, MOA_FEATURE_WEIGHTS["default"])
        candidates: dict[str, CandidateHIF] = {}

        def get_or_create(feat: NormalizedPathologyFeature) -> CandidateHIF:
            key = feat.source_id if feat.source == "HECatalog" else feat.feature_name
            if key not in candidates:
                candidates[key] = CandidateHIF(
                    feature_id=key,
                    feature_name=feat.feature_name,
                    feature_category=feat.feature_category,
                    measurement_method=feat.measurement_method,
                    measurement_unit=feat.measurement_unit,
                    moa_class=moa_class,
                )
            return candidates[key]

        # Score each evidence item
        for ev in all_evidence:
            cand = get_or_create(ev)
            cand.evidence_items.append(ev)

            if ev.source == "HECatalog":
                cand.in_he_catalog = True
                cand.catalog_ids.append(ev.source_id)

                # Propagate ROI from catalog entry
                if hasattr(ev, "roi") and ev.roi:
                    cand.roi = ev.roi
                if hasattr(ev, "roi_annotation_guide") and ev.roi_annotation_guide:
                    cand.roi_annotation_guide = ev.roi_annotation_guide

                ev_weight = EVIDENCE_LEVEL_WEIGHTS.get(ev.evidence_level or "D", 1.0)
                cat_weight = moa_weights.get(ev.feature_category.value, 1.0)

                # Macrophage penalty: deprioritize features primarily classified by macrophage
                mac_penalty = (
                    0.25
                    if ev.raw_data.get("is_macrophage_primary", False)
                    else 1.0
                )
                score = ev_weight * cat_weight * mac_penalty
                cand.catalog_score += score

                if cand.best_evidence_level is None or (
                    _get_evidence_level_order(ev.evidence_level or "D") <
                    _get_evidence_level_order(cand.best_evidence_level)
                ):
                    cand.best_evidence_level = ev.evidence_level

                if ev.evidence_type == FeatureType.PREDICTIVE:
                    cand.predictive_raw += score
                elif ev.evidence_type == FeatureType.PROGNOSTIC:
                    cand.prognostic_raw += score
                elif ev.evidence_type == FeatureType.BOTH:
                    cand.predictive_raw += score
                    cand.prognostic_raw += score

                cand.moa_score += cat_weight

            elif ev.source in ("PubMed", "PubMed-Analogical"):
                is_analogical = ev.source == "PubMed-Analogical"
                pmid = ev.source_id.replace("PMID:", "")
                # Track direct and analogical hits separately
                if not is_analogical and pmid not in cand.pubmed_ids:
                    cand.pubmed_ids.append(pmid)
                elif is_analogical and pmid not in getattr(cand, "analogical_ids", []):
                    if not hasattr(cand, "analogical_ids"):
                        cand.__dict__.setdefault("analogical_ids", [])
                    cand.__dict__["analogical_ids"].append(pmid)

                cat_weight = moa_weights.get(ev.feature_category.value, 1.0)
                # Analogical hits carry reduced weight vs. direct drug evidence
                hit_weight = PUBMED_HIT_WEIGHT * (0.6 if is_analogical else 1.0)
                cand.pubmed_score += hit_weight * cat_weight

                if ev.evidence_type == FeatureType.PREDICTIVE:
                    cand.predictive_raw += hit_weight * 0.5
                elif ev.evidence_type == FeatureType.PROGNOSTIC:
                    cand.prognostic_raw += hit_weight * 0.5
                elif ev.evidence_type == FeatureType.BOTH:
                    cand.predictive_raw += hit_weight * 0.4
                    cand.prognostic_raw += hit_weight * 0.4

        all_candidates = list(candidates.values())
        if not all_candidates:
            return []

        # Normalize scores to 0–100
        max_raw = max(c.total_raw_score for c in all_candidates) or 1.0
        max_pred = max(c.predictive_raw for c in all_candidates) or 1.0
        max_prog = max(c.prognostic_raw for c in all_candidates) or 1.0

        for cand in all_candidates:
            cand.catalog_score = min(100.0, (cand.total_raw_score / max_raw) * 100.0)
            cand.predictive_raw = min(100.0, (cand.predictive_raw / max_pred) * 100.0)
            cand.prognostic_raw = min(100.0, (cand.prognostic_raw / max_prog) * 100.0)

        # Sort by total raw score descending
        all_candidates.sort(key=lambda c: c.total_raw_score, reverse=True)

        # Filter: must have at least catalog or PubMed evidence
        valid = [c for c in all_candidates if c.has_minimum_evidence]

        logger.info(
            "[RankingAgent] %d valid candidates | top: %s (score=%.1f)",
            len(valid),
            valid[0].feature_name if valid else "N/A",
            valid[0].total_raw_score if valid else 0.0,
        )

        return valid[:top_n]

    def to_hypotheses(
        self,
        ranked_candidates: list[CandidateHIF],
    ) -> list[HIFHypothesis]:
        """
        Convert ranked CandidateHIF objects to HIFHypothesis schema.
        Assigns feature_type based on predictive/prognostic score thresholds.
        Mirrors RankingAgent.to_hypotheses() in oncomoa_agent.
        """
        hypotheses: list[HIFHypothesis] = []

        for rank, cand in enumerate(ranked_candidates, start=1):
            pred_score = cand.predictive_raw
            prog_score = cand.prognostic_raw

            if pred_score >= PREDICTIVE_THRESHOLD and prog_score >= PROGNOSTIC_THRESHOLD:
                feat_type = FeatureType.BOTH
            elif pred_score >= PREDICTIVE_THRESHOLD:
                feat_type = FeatureType.PREDICTIVE
            elif prog_score >= PROGNOSTIC_THRESHOLD:
                feat_type = FeatureType.PROGNOSTIC
            else:
                feat_type = FeatureType.UNKNOWN

            # Collect supporting sources (up to 5)
            sources: list[str] = []
            for ev in cand.evidence_items[:5]:
                sources.append(ev.source_id)

            supporting_evidence = [
                SupportingEvidence(
                    source=ev.source,
                    id=ev.source_id,
                    claim=ev.claim[:250],
                )
                for ev in cand.evidence_items[:5]
            ]

            # Drug relevance string based on MOA class
            moa_labels = {
                "checkpoint": "Checkpoint inhibitor TME biomarker",
                "ddr": "DNA damage repair response indicator",
                "kinase": "Kinase inhibitor TME context",
                "antiangiogenic": "Anti-angiogenic TME marker",
                "cell_cycle": "Cell cycle therapy TME indicator",
                "default": "General H&E prognostic/predictive feature",
            }
            relevance = moa_labels.get(cand.moa_class, moa_labels["default"])

            # Determine evidence basis: direct, analogical, or mixed
            has_direct = any(
                ev.source in ("HECatalog", "PubMed") for ev in cand.evidence_items
            )
            has_analogical = any(
                ev.source == "PubMed-Analogical" for ev in cand.evidence_items
            )
            if has_direct and has_analogical:
                evidence_basis = "mixed"
            elif has_analogical:
                evidence_basis = "analogical"
            else:
                evidence_basis = "direct"

            analogical_hits = len(cand.__dict__.get("analogical_ids", []))

            hypotheses.append(
                HIFHypothesis(
                    rank=rank,
                    feature_name=cand.feature_name,
                    roi=cand.roi,
                    roi_annotation_guide=cand.roi_annotation_guide,
                    feature_category=cand.feature_category,
                    feature_type=feat_type,
                    measurement_method=cand.measurement_method,
                    measurement_unit=cand.measurement_unit,
                    confidence_score=cand.catalog_score,
                    predictive_score=pred_score,
                    prognostic_score=prog_score,
                    evidence_level=cand.best_evidence_level,
                    evidence_basis=evidence_basis,
                    drug_relevance=relevance,
                    supporting_sources=sources,
                    supporting_evidence=supporting_evidence,
                    ranking_rationale=HIFRankingRationale(
                        in_he_catalog=cand.in_he_catalog,
                        evidence_level=cand.best_evidence_level,
                        pubmed_hits=len(cand.pubmed_ids),
                        analogical_hits=analogical_hits,
                        moa_weight_applied=cand.moa_score,
                        moa_class=cand.moa_class,
                        raw_score=cand.total_raw_score,
                    ),
                    hypothesis="",  # Filled by SynthesisAgent
                )
            )

        return hypotheses
