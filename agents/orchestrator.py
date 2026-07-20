"""
Digital Pathology HIF Agent — Master Orchestrator
Runs the full 4-agent pipeline in the correct order with progress tracking.
Handles errors gracefully: any single agent failure is logged and skipped.
Tumor-type agnostic — no indication is required to run.
Mirrors OncologyOrchestrator in oncomoa_agent.

Pipeline order:
  1. HEFeatureAgent     — H&E catalog query (MOA-weighted, pan-cancer)
  2. LiteratureAgent    — PubMed search (direct drug + analogical MOA-class)
  3. RankingAgent       — Deterministic scoring
  4. SynthesisAgent     — LLM narrative (direct evidence + analogical reasoning)

Example:
    orchestrator = PathologyOrchestrator()
    result = await orchestrator.run("pembrolizumab", "PD-1 checkpoint inhibitor")
    result = await orchestrator.run("novel-drug-x", "TIGIT checkpoint inhibitor")
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from models.schemas import PathologyOutput, HIFHypothesis
from agents.he_feature_agent import HEFeatureAgent
from agents.literature_agent import LiteratureAgent
from agents.ranking_agent import RankingAgent
from agents.synthesis_agent import SynthesisAgent
from llm.backend import get_backend
from config import DEFAULT_TOP_N, get_moa_class

logger = logging.getLogger(__name__)


class PathologyOrchestrator:
    """
    Orchestrates the full digital pathology HIF recommendation pipeline.
    Tumor-type agnostic: no indication needed; all solid tumors supported.

    Pipeline order:
      1. HEFeatureAgent   — H&E catalog lookup (MOA-weighted)
      2. LiteratureAgent  — PubMed direct + analogical evidence
      3. RankingAgent     — Deterministic scoring
      4. SynthesisAgent   — LLM narrative with analogical reasoning
    """

    def __init__(self, backend_override: str = "") -> None:
        self.backend_override = backend_override

    async def run(
        self,
        drug_name: str,
        moa_description: str,
        top_n: int = DEFAULT_TOP_N,
        progress: Progress | None = None,
    ) -> PathologyOutput:
        """
        Execute the full H&E HIF recommendation pipeline.

        Args:
            drug_name: Drug name (e.g., "pembrolizumab" or "novel-drug-001").
            moa_description: Mechanism of action description.
            top_n: Number of HIF hypotheses to return.
            progress: Optional Rich Progress instance for CLI progress bars.

        Returns:
            PathologyOutput with ranked HIFHypotheses and run metadata.
        """
        start_time = time.time()
        failed_sources: list[str] = []
        successful_sources: list[str] = []

        def _add_task(description: str) -> Any:
            if progress:
                return progress.add_task(f"[cyan]{description}", total=None)
            return None

        def _complete_task(task_id: Any) -> None:
            if progress and task_id is not None:
                progress.update(task_id, completed=True)

        moa_class = get_moa_class(drug_name, moa_description)

        logger.info("=" * 60)
        logger.info(
            "DigPath HIF Pipeline START: drug=%s moa_class=%s (pan-cancer)",
            drug_name, moa_class,
        )
        logger.info("=" * 60)

        # ── Step 1: H&E Catalog ───────────────────────────────────────────────
        task = _add_task("[1/4] Querying H&E feature catalog...")
        catalog_features = []
        try:
            he_agent = HEFeatureAgent()
            catalog_features, moa_class = await he_agent.run(drug_name, moa_description)
            if catalog_features:
                successful_sources.append("HECatalog")
        except Exception as exc:
            logger.error("[Orchestrator] HEFeatureAgent failed: %s", exc)
            failed_sources.append("HECatalog")
        _complete_task(task)

        # ── Step 2: PubMed Literature (direct + analogical) ───────────────────
        task = _add_task("[2/4] Searching PubMed (direct + analogical)...")
        lit_features = []
        all_pmids: list[str] = []
        try:
            lit_agent = LiteratureAgent()
            lit_features, all_pmids = await lit_agent.run(
                drug_name=drug_name,
                moa_description=moa_description,
                catalog_features=catalog_features,
            )
            direct_hits = sum(1 for f in lit_features if f.source == "PubMed")
            analogical_hits = sum(1 for f in lit_features if f.source == "PubMed-Analogical")
            if lit_features:
                successful_sources.append("PubMed")
            logger.info(
                "[Orchestrator] Literature: %d direct, %d analogical PMIDs",
                direct_hits, analogical_hits,
            )
        except Exception as exc:
            logger.error("[Orchestrator] LiteratureAgent failed: %s", exc)
            failed_sources.append("PubMed")
        _complete_task(task)

        all_evidence = catalog_features + lit_features

        # ── Step 3: Ranking ───────────────────────────────────────────────────
        task = _add_task("[3/4] Ranking H&E features...")
        pre_ranked: list[HIFHypothesis] = []
        try:
            ranking_agent = RankingAgent()
            ranked_candidates = ranking_agent.run(
                all_evidence=all_evidence,
                moa_class=moa_class,
                top_n=top_n,
            )
            pre_ranked = ranking_agent.to_hypotheses(ranked_candidates)
            successful_sources.append("RankingEngine")
        except Exception as exc:
            logger.error("[Orchestrator] RankingAgent failed: %s", exc)
            failed_sources.append("RankingEngine")
        _complete_task(task)

        # ── Step 4: LLM Synthesis ─────────────────────────────────────────────
        task = _add_task("[4/4] LLM synthesis (direct + analogical reasoning)...")
        final_hypotheses = pre_ranked
        llm_backend_name = "none"
        try:
            backend = get_backend(
                drug_name=drug_name, moa=moa_description, override=self.backend_override
            )
            llm_backend_name = backend.name
            synthesis_agent = SynthesisAgent(backend)
            final_hypotheses = await synthesis_agent.run(
                drug_name=drug_name,
                moa_description=moa_description,
                moa_class=moa_class,
                pre_ranked_hypotheses=pre_ranked,
                all_evidence=all_evidence,
                top_n=top_n,
            )
            successful_sources.append(f"LLM:{llm_backend_name}")
        except Exception as exc:
            logger.error("[Orchestrator] SynthesisAgent failed: %s", exc)
            failed_sources.append(f"LLM:{llm_backend_name}")
        _complete_task(task)

        elapsed = time.time() - start_time
        logger.info(
            "DigPath HIF Pipeline COMPLETE in %.1fs | %d features",
            elapsed, len(final_hypotheses),
        )

        return PathologyOutput(
            drug_name=drug_name,
            moa_description=moa_description,
            tumor_type="pan-cancer",
            moa_class=moa_class,
            llm_backend_used=llm_backend_name,
            hypotheses=final_hypotheses,
            failed_sources=list(set(failed_sources)),
            successful_sources=list(set(successful_sources)),
            total_features_evaluated=len(all_evidence),
            run_metadata={
                "elapsed_seconds": round(elapsed, 2),
                "total_evidence": len(all_evidence),
                "catalog_features": len(catalog_features),
                "pubmed_features": len(lit_features),
                "pubmed_ids_found": len(all_pmids),
                "moa_class": moa_class,
                "analogical_search": True,
            },
        )
