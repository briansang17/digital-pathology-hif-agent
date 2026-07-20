"""
Digital Pathology HIF Agent — Feature Synthesis Agent (LLM Step)
Takes the pre-ranked HIFHypothesis list and generates biological narrative
explaining why each H&E feature is prognostically or predictively relevant
for the given drug MOA.
Validates output with Pydantic and retries once on failure.

Mirrors BiomarkerSynthesisAgent in oncomoa_agent.

Example:
    agent = SynthesisAgent(backend)
    hypotheses = await agent.run(drug_name, moa, ranked_hypotheses, all_evidence)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from llm.backend import LLMBackend, PATHOLOGY_SYSTEM_PROMPT, build_hif_prompt, build_hif_prompt_local
from models.schemas import HIFHypothesis, SupportingEvidence, HIFRankingRationale, FeatureCategory

logger = logging.getLogger(__name__)

_JSON_ARRAY_RE = re.compile(r"\[\s*\{.*?\}\s*\]", re.DOTALL)


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    """
    Extract and parse the first JSON array of objects from LLM output.
    Handles markdown fences, preamble text, and non-standard local model output.
    """
    # Strip markdown code fences
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text).strip()

    # Strategy 1: find '[{' ... '}]' — JSON array of objects (non-greedy from first [{)
    start = text.find("[")
    # Walk forward to find a '[' that is followed (after whitespace) by '{'
    while start != -1:
        rest = text[start:]
        stripped = rest.lstrip("[").lstrip()
        if stripped.startswith("{"):
            # Try to parse from this '[' forward — find matching ']' by depth
            depth = 0
            in_str = False
            escape = False
            end = -1
            for i, ch in enumerate(rest):
                if escape:
                    escape = False
                    continue
                if ch == "\\" and in_str:
                    escape = True
                    continue
                if ch == '"' and not escape:
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end != -1:
                candidate = rest[:end + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, list) and parsed:
                        return parsed
                except json.JSONDecodeError:
                    pass
        next_start = text.find("[", start + 1)
        if next_start == start:
            break
        start = next_start

    # Strategy 2: extract individual JSON objects and wrap in array
    obj_re = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}", re.DOTALL)
    objects = obj_re.findall(text)
    valid_objects = []
    for o in objects:
        try:
            parsed = json.loads(o)
            if isinstance(parsed, dict) and len(parsed) > 1:
                valid_objects.append(parsed)
        except json.JSONDecodeError:
            pass
    if valid_objects:
        return valid_objects

    raise ValueError("No JSON array found in LLM response")


def _build_evidence_context(
    all_evidence: list[Any],
    drug_name: str,
    max_items: int = 60,
) -> str:
    """
    Build a compact evidence context string for the LLM prompt.
    Groups by source type:
      - HECatalog: curated knowledge base
      - PubMed: drug-specific literature
      - PubMed-Analogical: similar MOA class literature (flagged for LLM)

    Analogical entries are prefixed with [ANALOGICAL] so the LLM knows
    to use the "[By analogy from <drug class>]" framing for those features.
    """
    from models.schemas import NormalizedPathologyFeature

    by_source: dict[str, list[NormalizedPathologyFeature]] = {}
    for ev in all_evidence:
        if isinstance(ev, NormalizedPathologyFeature):
            by_source.setdefault(ev.source, []).append(ev)

    lines: list[str] = [f"DRUG: {drug_name}", "SCOPE: Pan-cancer", ""]
    per_source = max(len(by_source), 1)

    for source, items in by_source.items():
        is_analogical = source == "PubMed-Analogical"
        label = "[ANALOGICAL — MOA-class literature]" if is_analogical else f"[{source.upper()}]"
        lines.append(f"{label} ({len(items)} records)")
        for item in items[:max_items // per_source]:
            level_tag = f"[Level {item.evidence_level}] " if item.evidence_level else ""
            type_tag = f"[{item.evidence_type.value}] " if item.evidence_type else ""
            prefix = "[ANALOGICAL] " if is_analogical else ""
            lines.append(
                f"  - {prefix}{item.feature_name} | {type_tag}{level_tag}{item.claim[:200]}"
                f" | Src: {item.source_id}"
            )
        lines.append("")

    return "\n".join(lines)


def _validate_hypothesis(raw: dict[str, Any]) -> HIFHypothesis | None:
    """
    Parse and validate a single hypothesis dict from LLM output.
    Lenient with missing fields so simplified local-model output still parses.
    """
    try:
        # Ensure required fields have defaults if absent (local model output)
        raw.setdefault("rank", 1)
        raw.setdefault("feature_name", raw.get("name", "Unknown Feature"))
        raw.setdefault("hypothesis", "")
        raw.setdefault("measurement_method", "")
        raw.setdefault("measurement_unit", "")
        raw.setdefault("confidence_score", 50.0)
        raw.setdefault("predictive_score", 50.0)
        raw.setdefault("prognostic_score", 50.0)
        raw.setdefault("drug_relevance", "")
        raw.setdefault("supporting_sources", [])
        raw.setdefault("evidence_basis", "direct")

        raw_se = raw.get("supporting_evidence", [])
        if isinstance(raw_se, list):
            raw["supporting_evidence"] = [
                SupportingEvidence(
                    source=str(item.get("source", "")),
                    id=str(item.get("id", "")),
                    claim=str(item.get("claim", ""))[:300],
                )
                for item in raw_se if isinstance(item, dict)
            ]

        raw_rr = raw.get("ranking_rationale", {})
        if isinstance(raw_rr, dict):
            raw["ranking_rationale"] = HIFRankingRationale(
                in_he_catalog=bool(raw_rr.get("in_he_catalog", False)),
                evidence_level=raw_rr.get("evidence_level"),
                pubmed_hits=int(raw_rr.get("pubmed_hits", 0)),
                moa_weight_applied=float(raw_rr.get("moa_weight_applied", 0)),
                moa_class=str(raw_rr.get("moa_class", "")),
            )
        else:
            raw["ranking_rationale"] = HIFRankingRationale()

        if "feature_category" in raw and isinstance(raw["feature_category"], str):
            try:
                raw["feature_category"] = FeatureCategory(raw["feature_category"])
            except ValueError:
                raw["feature_category"] = FeatureCategory.COMPOSITE

        return HIFHypothesis.model_validate(raw)
    except (ValidationError, Exception) as exc:
        logger.debug("[SynthesisAgent] Hypothesis validation failed: %s", exc)
        return None


class SynthesisAgent:
    """
    LLM-powered H&E HIF synthesis agent.
    Generates narrative hypotheses grounded in retrieved evidence, with analogical
    reasoning from similar drug classes where direct evidence is sparse.

    Mirrors BiomarkerSynthesisAgent in oncomoa_agent:
      - Tries Gemini first (if routed there)
      - Detects auth errors and automatically falls back to Ollama
      - Retries once with a correction prompt on JSON parse failure
    """

    def __init__(self, backend: LLMBackend) -> None:
        self.backend = backend

    async def run(
        self,
        drug_name: str,
        moa_description: str,
        moa_class: str,
        pre_ranked_hypotheses: list[HIFHypothesis],
        all_evidence: list[Any],
        top_n: int = 10,
    ) -> list[HIFHypothesis]:
        """
        Generate enriched HIF hypotheses using the LLM.

        The LLM receives pre-ranked hypotheses + evidence context (direct + analogical)
        and synthesizes ranked HIF narratives. Uses auth-aware backend fallback so
        a bad Gemini API key never blocks the run — Ollama picks up automatically.

        Args:
            drug_name: Drug name.
            moa_description: Mechanism of action description.
            moa_class: Resolved MOA class (e.g., "checkpoint", "ddr").
            pre_ranked_hypotheses: Deterministically ranked HIFs from RankingAgent.
            all_evidence: Full evidence list (direct + analogical PubMed).
            top_n: Number of final hypotheses to return.

        Returns:
            List of HIFHypothesis with hypothesis text filled in.
        """
        from llm.backend import OllamaBackend

        logger.info(
            "[SynthesisAgent] Starting LLM synthesis with %s | drug=%s moa_class=%s (pan-cancer)",
            self.backend.name, drug_name, moa_class,
        )

        evidence_context = _build_evidence_context(all_evidence, drug_name)
        full_prompt = build_hif_prompt(
            drug_name=drug_name,
            moa_description=moa_description,
            moa_class=moa_class,
            evidence_summary=evidence_context,
            top_n=top_n,
        )
        # Simpler prompt for local 7B models — fewer fields, shorter context
        local_prompt = build_hif_prompt_local(
            drug_name=drug_name,
            moa_class=moa_class,
            evidence_summary=evidence_context,
            top_n=top_n,
        )

        backends_to_try = [self.backend]

        # If primary is Gemini, queue Ollama as automatic auth-error fallback
        if "gemini" in self.backend.name.lower():
            logger.info(
                "[SynthesisAgent] Gemini primary — Ollama queued as auth-error fallback"
            )
            backends_to_try.append(OllamaBackend())

        for backend in backends_to_try:
            is_local = "ollama" in backend.name.lower()
            prompt = local_prompt if is_local else full_prompt
            result = await self._try_backend(
                backend, prompt, pre_ranked_hypotheses
            )
            if result is not None:
                return result

        # All backends failed — return deterministic ranking with placeholder narrative
        logger.error(
            "[SynthesisAgent] All LLM backends failed. Returning deterministic ranking."
        )
        for h in pre_ranked_hypotheses:
            if not h.hypothesis:
                h.hypothesis = (
                    f"Evidence-based H&E feature for {drug_name} (pan-cancer). "
                    f"Supported by {len(h.supporting_sources)} source(s). "
                    "Run 'ollama pull meditron && ollama serve' for full LLM synthesis."
                )
        return pre_ranked_hypotheses[:top_n]

    async def _try_backend(
        self,
        backend: Any,
        user_prompt: str,
        pre_ranked_hypotheses: list[HIFHypothesis],
    ) -> list[HIFHypothesis] | None:
        """
        Attempt synthesis with one backend.
        Returns parsed hypotheses on success, None on any failure.
        Switches to next backend immediately on auth/key errors.
        """
        AUTH_ERROR_SIGNALS = (
            "API_KEY_INVALID", "API key not valid", "INVALID_ARGUMENT",
            "authentication", "unauthorized", "Unauthorized",
        )

        logger.info("[SynthesisAgent] Trying backend: %s", backend.name)

        # First attempt
        try:
            raw_response = await backend.generate(PATHOLOGY_SYSTEM_PROMPT, user_prompt)
            validated = self._parse_and_validate(raw_response, pre_ranked_hypotheses)
            if validated:
                logger.info(
                    "[SynthesisAgent] %s succeeded: %d hypotheses",
                    backend.name, len(validated),
                )
                return validated
        except Exception as exc:
            exc_str = str(exc)
            if any(sig in exc_str for sig in AUTH_ERROR_SIGNALS):
                logger.warning(
                    "[SynthesisAgent] %s auth error — switching to next backend. (%s)",
                    backend.name, exc_str[:120],
                )
                return None  # Signal: try next backend
            logger.warning(
                "[SynthesisAgent] %s error: %s — retrying with correction prompt.",
                backend.name, exc_str[:120],
            )

        # Retry with correction prompt
        try:
            correction_prompt = (
                f"{user_prompt}\n\n"
                "IMPORTANT: Your previous response was not valid JSON. "
                "Return ONLY a valid JSON array. No text before or after the array. "
                "No markdown code fences. Start your response with '[' and end with ']'."
            )
            raw_response = await backend.generate(PATHOLOGY_SYSTEM_PROMPT, correction_prompt)
            validated = self._parse_and_validate(raw_response, pre_ranked_hypotheses)
            if validated:
                logger.info(
                    "[SynthesisAgent] %s retry succeeded: %d hypotheses",
                    backend.name, len(validated),
                )
                return validated
        except Exception as exc:
            exc_str = str(exc)
            if any(sig in exc_str for sig in AUTH_ERROR_SIGNALS):
                logger.warning(
                    "[SynthesisAgent] %s auth error on retry — switching backend.",
                    backend.name,
                )
                return None
            logger.error(
                "[SynthesisAgent] %s retry failed: %s", backend.name, exc_str[:120]
            )

        return None

    def _parse_and_validate(
        self,
        raw_response: str,
        fallback_hypotheses: list[HIFHypothesis],
    ) -> list[HIFHypothesis]:
        """
        Parse LLM JSON and merge hypothesis narrative into pre-ranked hypotheses.

        Hybrid strategy:
          1. Parse LLM JSON array; handle both 'feature_name' and 'name' keys.
          2. For each LLM item: validate into HIFHypothesis, inherit authoritative
             scores from matching pre-ranked item (name match, then positional).
          3. Pre-ranked items not matched by LLM are padded at the end.
          This ensures: no 'Unknown Feature' from missing keys, no score drift,
          and the final list always has at least as many items as pre_ranked.
        """
        try:
            raw_list = _extract_json_array(raw_response)
        except ValueError:
            logger.warning(
                "[SynthesisAgent] Could not parse JSON from LLM response. "
                "First 300 chars: %r",
                raw_response[:300],
            )
            return []

        logger.info(
            "[SynthesisAgent] Parsed %d LLM items. Pre-ranked: %d.",
            len(raw_list), len(fallback_hypotheses),
        )

        def _norm(s: str) -> str:
            return re.sub(r"[^a-z0-9]", "", s.lower())

        ranked_lookup: dict[str, HIFHypothesis] = {
            _norm(h.feature_name): h for h in fallback_hypotheses
        }

        validated: list[HIFHypothesis] = []
        used_keys: set[str] = set()

        for idx, raw_item in enumerate(raw_list):
            # Normalise: handle both 'feature_name' and 'name' keys
            if "feature_name" not in raw_item and "name" in raw_item:
                raw_item["feature_name"] = raw_item["name"]

            hyp = _validate_hypothesis(raw_item)
            if hyp is None:
                continue

            key = _norm(hyp.feature_name)
            pre = ranked_lookup.get(key)
            if pre is None and idx < len(fallback_hypotheses):
                pre = fallback_hypotheses[idx]

            if pre is not None:
                hyp.confidence_score = max(hyp.confidence_score, pre.confidence_score)
                hyp.predictive_score = max(hyp.predictive_score, pre.predictive_score)
                hyp.prognostic_score = max(hyp.prognostic_score, pre.prognostic_score)
                hyp.rank = pre.rank
                if not hyp.supporting_sources:
                    hyp.supporting_sources = pre.supporting_sources
                if not hyp.supporting_evidence:
                    hyp.supporting_evidence = pre.supporting_evidence
                if hyp.ranking_rationale.raw_score == 0:
                    hyp.ranking_rationale = pre.ranking_rationale
                if pre.roi and not hyp.roi:
                    hyp.roi = pre.roi
                if pre.roi_annotation_guide and not hyp.roi_annotation_guide:
                    hyp.roi_annotation_guide = pre.roi_annotation_guide
                if pre.measurement_method and not hyp.measurement_method:
                    hyp.measurement_method = pre.measurement_method
                used_keys.add(_norm(pre.feature_name))

            validated.append(hyp)

        # Pad with any pre-ranked items the LLM missed (to reach top_n)
        target_n = len(fallback_hypotheses)
        for pre in fallback_hypotheses:
            if len(validated) >= target_n:
                break
            if _norm(pre.feature_name) not in used_keys:
                validated.append(pre)

        # Re-number ranks sequentially (LLM may have used its own ordering)
        for i, hyp in enumerate(validated[:target_n], start=1):
            hyp.rank = i

        return validated[:target_n]
