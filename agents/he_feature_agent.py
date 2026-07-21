"""
MOA-to-HIF Evidence Prioritization Agent — H&E Feature Agent
Queries the H&E catalog to retrieve all Human-Interpretable Features (HIFs)
relevant for a given drug MOA. Tumor-type agnostic — every indication is supported.

Example:
    agent = HEFeatureAgent()
    features, moa_class = await agent.run("pembrolizumab", "PD-1 checkpoint inhibitor")
    features, moa_class = await agent.run("novel-drug-x", "TIGIT checkpoint inhibitor")
"""

from __future__ import annotations

import logging

from config import get_moa_class, CATALOG_BASE_WEIGHT, EVIDENCE_LEVEL_WEIGHTS, MOA_FEATURE_WEIGHTS
from models.schemas import NormalizedPathologyFeature
from tools.he_catalog import get_he_features

logger = logging.getLogger(__name__)


class HEFeatureAgent:
    """
    Retrieves all H&E HIF catalog entries, weighted by drug MOA class.
    Tumor-type agnostic: the full catalog is always returned and scored.
    Mirrors DrugAgent / TargetBiologyAgent in oncomoa_agent.
    """

    async def run(
        self,
        drug_name: str,
        moa_description: str,
    ) -> tuple[list[NormalizedPathologyFeature], str]:
        """
        Retrieve and score all H&E HIFs from the catalog for the given drug/MOA.

        MOA class determines which feature categories are weighted higher —
        but all features are always returned so nothing is excluded for any indication.

        Args:
            drug_name: Drug name (e.g., "pembrolizumab" or "novel-drug-001").
            moa_description: Mechanism of action description.

        Returns:
            Tuple of (features: list[NormalizedPathologyFeature], moa_class: str).
        """
        moa_class = get_moa_class(drug_name, moa_description)
        logger.info(
            "[HEFeatureAgent] drug=%s | moa_class=%s (tumor-type agnostic)",
            drug_name, moa_class,
        )

        features = get_he_features(moa_class=moa_class)

        moa_weights = MOA_FEATURE_WEIGHTS.get(moa_class, MOA_FEATURE_WEIGHTS["default"])
        for feat in features:
            ev_weight = EVIDENCE_LEVEL_WEIGHTS.get(feat.evidence_level or "D", 1.0)
            cat_weight = moa_weights.get(feat.feature_category.value, 1.0)
            # Apply macrophage penalty if flagged
            mac_penalty = (
                0.25
                if feat.raw_data.get("is_macrophage_primary", False)
                else 1.0
            )
            feat.strength = CATALOG_BASE_WEIGHT * ev_weight * cat_weight * mac_penalty

        features.sort(key=lambda f: f.strength, reverse=True)

        logger.info(
            "[HEFeatureAgent] Retrieved %d H&E features from catalog", len(features)
        )
        return features, moa_class
