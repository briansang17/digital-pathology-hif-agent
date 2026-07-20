"""
Digital Pathology HIF Agent — PubMed Literature Search
Searches PubMed for H&E pathology feature evidence for a given drug + tumor type.
Returns NormalizedPathologyFeature records from literature.

Example:
    features = await search_pubmed_for_hif(
        drug_name="pembrolizumab",
        feature_name="Stromal TIL Score",
        tumor_type="NSCLC",
    )
"""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from typing import Any

import aiohttp

from config import PUBMED_EUTILS_BASE, PUBMED_MAX_RESULTS, NCBI_API_KEY, HTTP_TIMEOUT
from models.schemas import (
    NormalizedPathologyFeature,
    FeatureCategory,
    FeatureType,
    EvidenceDirection,
)
from tools.cache import cached_api_call

logger = logging.getLogger(__name__)


def _build_params(extra: dict[str, Any]) -> dict[str, str]:
    """Build base NCBI params dict, appending API key if available."""
    params: dict[str, Any] = {"retmode": "json", **extra}
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    return {k: str(v) for k, v in params.items()}


@cached_api_call("digpath_pubmed_search")
async def search_pubmed_ids(query: str, max_results: int = PUBMED_MAX_RESULTS) -> list[str]:
    """
    Search PubMed using esearch and return a list of PMIDs.

    Args:
        query: Free-text search query.
        max_results: Maximum number of PMIDs to return.

    Returns:
        List of PMID strings.
    """
    url = f"{PUBMED_EUTILS_BASE}/esearch.fcgi"
    params = _build_params({
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "usehistory": "y",
        "sort": "relevance",
    })
    # ssl=False: Python 3.10 on macOS doesn't auto-install SSL certs for stdlib
    connector = aiohttp.TCPConnector(ssl=False)
    try:
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
        ) as session:
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
        pmids = data.get("esearchresult", {}).get("idlist", [])
        logger.info("[PubMed] %d PMIDs for query '%s'", len(pmids), query[:70])
        return pmids
    except Exception as exc:
        logger.error("[PubMed] search_pubmed_ids failed: %s", exc)
        return []


@cached_api_call("digpath_pubmed_fetch")
async def fetch_pubmed_abstracts(pmids: tuple[str, ...]) -> list[dict[str, str]]:
    """
    Fetch titles and abstracts for a list of PMIDs using efetch.

    Args:
        pmids: Tuple of PubMed IDs (tuple for cache-key determinism).

    Returns:
        List of dicts with keys: pmid, title, abstract.
    """
    if not pmids:
        return []

    url = f"{PUBMED_EUTILS_BASE}/efetch.fcgi"
    params = _build_params({
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "abstract",
        "retmode": "xml",
    })

    connector = aiohttp.TCPConnector(ssl=False)
    try:
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
        ) as session:
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                xml_text = await resp.text()
        articles = _parse_pubmed_xml(xml_text)
        logger.info("[PubMed] Fetched %d abstracts", len(articles))
        return articles
    except Exception as exc:
        logger.error("[PubMed] fetch_pubmed_abstracts failed: %s", exc)
        return []


def _parse_pubmed_xml(xml_text: str) -> list[dict[str, str]]:
    """Parse PubMed XML response into article dicts."""
    articles: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
        for article_elem in root.findall(".//PubmedArticle"):
            pmid_elem = article_elem.find(".//PMID")
            pmid = pmid_elem.text if pmid_elem is not None else ""

            title_elem = article_elem.find(".//ArticleTitle")
            title = "".join(title_elem.itertext()) if title_elem is not None else ""

            abstract_parts = []
            for ab_text in article_elem.findall(".//AbstractText"):
                label = ab_text.get("Label", "")
                text = "".join(ab_text.itertext())
                abstract_parts.append(f"{label}: {text}" if label else text)
            abstract = " ".join(abstract_parts)

            if pmid:
                articles.append({"pmid": pmid, "title": title, "abstract": abstract})
    except ET.ParseError as exc:
        logger.error("[PubMed] XML parse error: %s", exc)
    return articles


def _infer_feature_category(title: str, abstract: str) -> FeatureCategory:
    """Infer a feature category from article text."""
    text = f"{title} {abstract}".lower()
    if any(kw in text for kw in ["til score", "tumor-infiltrating lymphocyte", "til%", "stromal til"]):
        return FeatureCategory.TIL_SCORE
    if any(kw in text for kw in ["immune phenotype", "inflamed", "excluded", "desert", "immunoscore"]):
        return FeatureCategory.IMMUNE_PHENOTYPE
    if any(kw in text for kw in ["nearest neighbor", "distance", "proximity"]):
        return FeatureCategory.SPATIAL_DISTANCE
    if any(kw in text for kw in ["clustering", "ripley", "hotspot", "aggregat"]):
        return FeatureCategory.SPATIAL_CLUSTERING
    if any(kw in text for kw in ["colocal", "interaction", "contact", "cross-k"]):
        return FeatureCategory.COLOCALIZATION
    if any(kw in text for kw in ["neighborhood", "composition", "entropy", "diversity"]):
        return FeatureCategory.NEIGHBORHOOD_COMPOSITION
    if any(kw in text for kw in ["density", "cells/mm", "cell count", "infiltrat"]):
        return FeatureCategory.CELL_DENSITY
    return FeatureCategory.COMPOSITE


def _infer_feature_type(title: str, abstract: str) -> FeatureType:
    """Infer predictive/prognostic from article text."""
    text = f"{title} {abstract}".lower()
    is_predictive = any(kw in text for kw in [
        "predictive", "predict response", "predict benefit",
        "pathologic complete response", "pcr", "overall response rate",
    ])
    is_prognostic = any(kw in text for kw in [
        "prognostic", "overall survival", "os ", "disease-free survival",
        "recurrence-free", "independent predictor", "prognosis",
    ])
    if is_predictive and is_prognostic:
        return FeatureType.BOTH
    if is_predictive:
        return FeatureType.PREDICTIVE
    if is_prognostic:
        return FeatureType.PROGNOSTIC
    return FeatureType.UNKNOWN


def _article_to_feature(
    article: dict[str, str],
    drug_name: str,
    feature_name: str,
    moa_class: str,
    is_analogical: bool = False,
) -> NormalizedPathologyFeature:
    """
    Convert a PubMed article dict to a NormalizedPathologyFeature.

    Args:
        is_analogical: True when the article came from a class-level search
                       rather than drug-specific search. Stored in raw_data so
                       the LLM can signal "by analogy" in its hypothesis.
    """
    pmid = article["pmid"]
    title = article["title"]
    abstract = article["abstract"]
    claim = f"{title[:200]}" if title else abstract[:200]

    return NormalizedPathologyFeature(
        source="PubMed" if not is_analogical else "PubMed-Analogical",
        source_id=f"PMID:{pmid}",
        feature_name=feature_name,
        feature_category=_infer_feature_category(title, abstract),
        measurement_method="",
        measurement_unit="",
        tumor_type=None,   # Tumor-type agnostic
        drug=drug_name,
        moa_class=moa_class,
        evidence_type=_infer_feature_type(title, abstract),
        evidence_direction=EvidenceDirection.SUPPORTS,
        evidence_level="C",
        claim=claim,
        strength=0.0,
        raw_data={
            "title": title,
            "abstract": abstract[:500],
            "is_analogical": is_analogical,
        },
    )


async def search_pubmed_for_hif(
    drug_name: str,
    feature_name: str,
    moa_class: str = "",
    max_results: int = PUBMED_MAX_RESULTS,
) -> list[NormalizedPathologyFeature]:
    """
    Search PubMed for evidence linking an H&E feature to a specific drug.
    Tumor-type agnostic — searches across all indications.

    Args:
        drug_name: Drug name (e.g., "pembrolizumab").
        feature_name: H&E HIF name (e.g., "Stromal TIL Score").
        moa_class: MOA class for metadata.
        max_results: Max PubMed results per query.

    Returns:
        List of NormalizedPathologyFeature records from PubMed.

    Example:
        features = await search_pubmed_for_hif("pembrolizumab", "Stromal TIL Score")
    """
    # Primary: drug name + feature (pan-cancer)
    query = f'"{feature_name}" "{drug_name}" pathology cancer'
    pmids = await search_pubmed_ids(query, max_results=max_results)

    # Fallback: drug name + feature keywords only
    if not pmids:
        query = f'"{drug_name}" tumor infiltrating lymphocyte pathology biomarker'
        pmids = await search_pubmed_ids(query, max_results=max_results)

    if not pmids:
        return []

    articles = await fetch_pubmed_abstracts(tuple(pmids))
    return [
        _article_to_feature(a, drug_name, feature_name, moa_class, is_analogical=False)
        for a in articles
    ]


async def search_pubmed_analogical(
    moa_class: str,
    feature_name: str,
    drug_name: str = "",
    max_results: int = PUBMED_MAX_RESULTS,
) -> list[NormalizedPathologyFeature]:
    """
    Search PubMed using the broader drug CLASS rather than the specific drug name.
    Finds evidence from similar mechanisms when drug-specific data is sparse.
    Results are flagged as analogical so the LLM can label them appropriately.

    Args:
        moa_class: MOA bucket (e.g., "checkpoint", "ddr", "kinase").
        feature_name: H&E HIF name to search with.
        drug_name: Original drug name (used for feature metadata only).
        max_results: Max PubMed results.

    Returns:
        List of NormalizedPathologyFeature records (source="PubMed-Analogical").

    Example:
        # For a novel PARP inhibitor with no published pathology data:
        features = await search_pubmed_analogical("ddr", "Stromal TIL Score")
        # Returns: literature on PARP inhibitors + stromal TILs across any cancer type
    """
    from config import MOA_CLASS_SEARCH_TERMS

    class_terms = MOA_CLASS_SEARCH_TERMS.get(moa_class, MOA_CLASS_SEARCH_TERMS["default"])
    query = f'("{feature_name}") AND ({class_terms}) AND pathology'
    pmids = await search_pubmed_ids(query, max_results=max_results)

    if not pmids:
        # Broader fallback: MOA class + cancer pathology
        query = f'({class_terms}) AND "tumor microenvironment" AND pathology'
        pmids = await search_pubmed_ids(query, max_results=max_results)

    if not pmids:
        return []

    articles = await fetch_pubmed_abstracts(tuple(pmids))
    return [
        _article_to_feature(a, drug_name, feature_name, moa_class, is_analogical=True)
        for a in articles
    ]


async def search_pubmed_bulk_hifs(
    drug_name: str,
    feature_names: list[str],
    moa_class: str = "",
    max_per_feature: int = 5,
) -> dict[str, list[NormalizedPathologyFeature]]:
    """
    Run parallel PubMed searches (specific + analogical) for multiple H&E features.
    Each feature gets two searches: one drug-specific, one MOA-class-level.

    Args:
        drug_name: Drug name.
        feature_names: List of HIF names to search.
        moa_class: MOA class for analogical search.
        max_per_feature: Max results per search.

    Returns:
        Dict mapping feature_name → combined list of NormalizedPathologyFeature.
    """
    # Build task pairs: (specific, analogical) for each feature
    specific_tasks = [
        search_pubmed_for_hif(drug_name, fname, moa_class, max_per_feature)
        for fname in feature_names
    ]
    analogical_tasks = [
        search_pubmed_analogical(moa_class, fname, drug_name, max_per_feature)
        for fname in feature_names
    ]

    all_tasks = specific_tasks + analogical_tasks
    all_results = await asyncio.gather(*all_tasks, return_exceptions=True)

    n = len(feature_names)
    output: dict[str, list[NormalizedPathologyFeature]] = {}

    for i, fname in enumerate(feature_names):
        specific = all_results[i]
        analogical = all_results[i + n]

        combined: list[NormalizedPathologyFeature] = []
        if not isinstance(specific, Exception):
            combined.extend(specific)  # type: ignore[arg-type]
        elif specific:
            logger.error("[PubMed] Specific search error for '%s': %s", fname, specific)

        if not isinstance(analogical, Exception):
            combined.extend(analogical)  # type: ignore[arg-type]
        elif analogical:
            logger.error("[PubMed] Analogical search error for '%s': %s", fname, analogical)

        output[fname] = combined

    return output
