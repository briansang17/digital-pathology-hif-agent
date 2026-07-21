"""
MOA-to-HIF Evidence Prioritization Agent — Literature Agent
Searches PubMed for H&E feature evidence for a given drug across all indications.

Two search tracks run in parallel for every feature:
  1. Specific  — drug name + feature (direct evidence for this drug)
  2. Analogical — MOA class terms + feature (evidence from similar drug mechanisms)

Analogical results are flagged with source="PubMed-Analogical" so the LLM
can label them as "by analogy from [drug class]" in its hypothesis text.

Mirrors LiteratureAgent in oncomoa_agent.

Example:
    agent = LiteratureAgent()
    features, pmids = await agent.run(
        drug_name="pembrolizumab",
        moa_description="PD-1 checkpoint inhibitor",
        catalog_features=features,
    )
"""

from __future__ import annotations

import logging

from config import PUBMED_HIT_WEIGHT, get_moa_class
from models.schemas import NormalizedPathologyFeature
from tools.pubmed import search_pubmed_bulk_hifs

# For novel drugs with sparse literature, use established class proxies
# to pull relevant histology evidence from component-drug studies.
COMPONENT_PROXY_DRUGS: dict[str, list[str]] = {
    "bispecific": ["pembrolizumab", "bevacizumab"],   # PD-1 + VEGF components
    "adc": ["sacituzumab govitecan", "irinotecan"],     # TROP2-ADC + SN-38 payload proxy
    "hypoxia": ["sunitinib", "bevacizumab"],           # anti-VEGF proxies for HIF biology
}

logger = logging.getLogger(__name__)

# Top features to search to avoid over-querying PubMed
MAX_FEATURES_TO_SEARCH = 5
# Analogical hits get a slight weight discount vs. direct drug evidence
ANALOGICAL_WEIGHT_FACTOR = 0.6


class LiteratureAgent:
    """
    Fetches PubMed evidence for H&E HIFs across all tumor types.

    Runs two parallel search tracks per feature:
      - Direct: specific drug name evidence
      - Analogical: broader MOA class evidence (for sparse/novel drugs)

    Mirrors LiteratureAgent in oncomoa_agent.
    """

    async def run(
        self,
        drug_name: str,
        moa_description: str,
        catalog_features: list[NormalizedPathologyFeature],
    ) -> tuple[list[NormalizedPathologyFeature], list[str]]:
        """
        Search PubMed for H&E HIF evidence using direct + analogical queries.

        Args:
            drug_name: Drug name.
            moa_description: MOA description.
            catalog_features: HIF list from HEFeatureAgent (drives search queries).

        Returns:
            Tuple of (evidence_features, all_pmids).
        """
        moa_class = get_moa_class(drug_name, moa_description)
        feature_names = [f.feature_name for f in catalog_features[:MAX_FEATURES_TO_SEARCH]]

        # For novel bispecific/ADC/hypoxia drugs, run extra searches using
        # established component proxies (e.g., pembrolizumab + bevacizumab
        # for an anti-PD-1/VEGF bispecific) to pull relevant histology evidence.
        proxy_drugs = COMPONENT_PROXY_DRUGS.get(moa_class, [])

        logger.info(
            "[LiteratureAgent] Searching PubMed for %d HIFs | drug=%s moa_class=%s "
            "(direct + analogical + %d proxy drugs: %s)",
            len(feature_names), drug_name, moa_class,
            len(proxy_drugs), proxy_drugs,
        )

        # Primary: direct + analogical for this drug
        results = await search_pubmed_bulk_hifs(
            drug_name=drug_name,
            feature_names=feature_names,
            moa_class=moa_class,
            max_per_feature=5,
        )

        # Component proxy searches (bispecific/ADC/novel): each proxy contributes
        # analogical evidence from well-studied component drugs
        import asyncio as _asyncio
        proxy_results_list = await _asyncio.gather(*[
            search_pubmed_bulk_hifs(
                drug_name=proxy,
                feature_names=feature_names,
                moa_class=moa_class,
                max_per_feature=3,
            )
            for proxy in proxy_drugs
        ], return_exceptions=True)

        for proxy_result in proxy_results_list:
            if isinstance(proxy_result, Exception):
                continue
            for fname, feat_list in proxy_result.items():
                existing = results.get(fname, [])
                # Tag proxy hits as analogical so LLM knows the evidence source
                for feat in feat_list:
                    feat.source = "PubMed-Analogical"
                results[fname] = existing + feat_list

        all_features: list[NormalizedPathologyFeature] = []
        all_pmids: list[str] = []
        direct_count = 0
        analogical_count = 0

        for fname, feat_list in results.items():
            for feat in feat_list:
                is_analogical = feat.source == "PubMed-Analogical"
                # Analogical hits weighted slightly lower than direct evidence
                feat.strength = (
                    PUBMED_HIT_WEIGHT * ANALOGICAL_WEIGHT_FACTOR
                    if is_analogical
                    else PUBMED_HIT_WEIGHT
                )
                all_features.append(feat)
                pmid = feat.source_id.replace("PMID:", "")
                if pmid not in all_pmids:
                    all_pmids.append(pmid)
                if is_analogical:
                    analogical_count += 1
                else:
                    direct_count += 1

        logger.info(
            "[LiteratureAgent] Found %d records (%d direct, %d analogical) | %d unique PMIDs",
            len(all_features), direct_count, analogical_count, len(all_pmids),
        )
        return all_features, all_pmids
