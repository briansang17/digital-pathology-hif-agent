"""
Digital Pathology HIF Agent — LLM Backend
Provides a unified async interface for Gemini and Ollama (meditron/llama3.2),
with smart drug-class routing and graceful fallback.
Mirrors oncomoa_agent/llm/backend.py exactly, with pathology-specific prompts.

Usage:
    backend = get_backend(drug_name="pembrolizumab", moa="PD-1 checkpoint inhibitor")
    response = await backend.generate(system_prompt, user_prompt)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import aiohttp

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    LLM_BACKEND,
    OLLAMA_BASE_URL,
    OLLAMA_PRIMARY_MODEL,
    OLLAMA_FALLBACK_MODEL,
    HTTP_TIMEOUT,
    requires_gemini,
)

logger = logging.getLogger(__name__)


# ─── Abstract Base ─────────────────────────────────────────────────────────────

class LLMBackend(ABC):
    """Abstract LLM backend interface."""

    @abstractmethod
    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """
        Generate a response given system and user prompts.

        Args:
            system_prompt: Role/instruction context for the model.
            user_prompt: The actual query or task.

        Returns:
            Model response as a string.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name for logging."""
        ...


# ─── Gemini Backend ───────────────────────────────────────────────────────────

class GeminiBackend(LLMBackend):
    """
    Google Gemini backend using google-generativeai SDK.
    Model: gemini-1.5-flash (free tier).
    """

    def __init__(self, api_key: str = GEMINI_API_KEY, model: str = GEMINI_MODEL) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set. Add it to your .env file.")
        self._api_key = api_key
        self._model = model

    @property
    def name(self) -> str:
        return f"Gemini/{self._model}"

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """
        Send a prompt to Gemini and return the text response.
        Retries up to 2 times on 503 (high demand) with a short backoff.
        Falls back to gemini-2.0-flash if 2.5-flash is consistently unavailable.
        """
        import asyncio
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)
        # Build cascade: configured model + stable fallbacks
        models_to_try = [self._model]
        fallbacks = ["gemini-2.5-flash", "gemini-2.0-flash"]
        for fb in fallbacks:
            if fb != self._model:
                models_to_try.append(fb)

        for model in models_to_try:
            model_failed = False
            for attempt in range(3):
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            temperature=0.1,
                            max_output_tokens=8192,
                        ),
                    )
                    text = response.text
                    logger.info("[Gemini/%s] Response: %d chars", model, len(text))
                    return text
                except Exception as exc:
                    exc_str = str(exc)
                    if "503" in exc_str or "UNAVAILABLE" in exc_str:
                        wait = 2 ** attempt  # 1s, 2s, 4s
                        logger.warning(
                            "[GeminiBackend] %s unavailable (attempt %d/3), retrying in %ds",
                            model, attempt + 1, wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
                        # Daily quota exhausted for this model — try next model in cascade
                        logger.warning(
                            "[GeminiBackend] %s quota exhausted (429). Trying next model.",
                            model,
                        )
                        model_failed = True
                        break
                    # For auth and other fatal errors, re-raise immediately
                    logger.error("[GeminiBackend] generate failed: %s", exc)
                    raise
            if not model_failed:
                logger.warning("[GeminiBackend] %s failed all retries, trying next model", model)

        raise RuntimeError("All Gemini models unavailable. Try again later or use --backend ollama.")


# ─── Ollama Backend ───────────────────────────────────────────────────────────

class OllamaBackend(LLMBackend):
    """
    Ollama local LLM backend.
    Tries primary model (meditron) first, falls back to llama3.2.
    """

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        primary_model: str = OLLAMA_PRIMARY_MODEL,
        fallback_model: str = OLLAMA_FALLBACK_MODEL,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._primary_model = primary_model
        self._fallback_model = fallback_model
        self._active_model: str | None = None

    @property
    def name(self) -> str:
        return f"Ollama/{self._active_model or self._primary_model}"

    async def _is_model_available(self, model: str) -> bool:
        """Check if a model is pulled and available in Ollama."""
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            ) as session:
                async with session.get(f"{self._base_url}/api/tags") as resp:
                    if resp.status != 200:
                        return False
                    data = await resp.json()
                    available = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
                    return model in available or model.split(":")[0] in available
        except Exception:
            return False

    async def _generate_with_model(
        self, model: str, system_prompt: str, user_prompt: str
    ) -> str:
        """
        Generate with a specific Ollama model.

        The evidence prompt can be very large (100+ items). For local models,
        we truncate to MAX_LOCAL_CHARS so the context window isn't exceeded
        and inference stays within a reasonable wall-clock budget (~5 minutes).
        """
        MAX_LOCAL_CHARS = 6000  # ~1500 tokens — fits any 7B model safely
        OLLAMA_TIMEOUT = 360    # 6 minutes for local CPU inference

        combined = f"System: {system_prompt}\n\nUser: {user_prompt}"
        if len(combined) > MAX_LOCAL_CHARS:
            combined = combined[:MAX_LOCAL_CHARS] + (
                "\n\n[Context truncated for local model. Return your best JSON "
                "array based on the evidence shown above.]"
            )

        url = f"{self._base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": combined,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 2048,  # Cap output tokens for speed
                "num_ctx": 4096,      # Explicit context window
            },
        }
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=OLLAMA_TIMEOUT)
        ) as session:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
        text = data.get("response", "")
        logger.debug("[Ollama/%s] Response: %d chars", model, len(text))
        return text

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate using meditron; fall back to llama3.2 if unavailable."""
        if await self._is_model_available(self._primary_model):
            try:
                self._active_model = self._primary_model
                return await self._generate_with_model(
                    self._primary_model, system_prompt, user_prompt
                )
            except Exception as exc:
                logger.warning(
                    "[Ollama] Primary model %s failed: %s. Trying fallback.",
                    self._primary_model, exc,
                )

        if await self._is_model_available(self._fallback_model):
            try:
                self._active_model = self._fallback_model
                return await self._generate_with_model(
                    self._fallback_model, system_prompt, user_prompt
                )
            except Exception as exc:
                logger.error("[Ollama] Fallback model %s failed: %s", self._fallback_model, exc)
                raise

        raise RuntimeError(
            f"No Ollama models available. Run: ollama pull {self._primary_model}"
        )


# ─── Backend Factory ──────────────────────────────────────────────────────────

def get_backend(
    drug_name: str = "",
    moa: str = "",
    override: str = "",
) -> LLMBackend:
    """
    Resolve the appropriate LLM backend using smart routing rules.

    Priority:
    1. CLI override (--backend flag)
    2. LLM_BACKEND env var (if not "auto")
    3. Drug/MOA routing:
       - IO drugs (checkpoint, bispecific) → Gemini
       - ADCs → Gemini
       - All others → Ollama (meditron → llama3.2)

    Args:
        drug_name: Drug name (used for auto-routing).
        moa: MOA description (used for auto-routing).
        override: Explicit backend choice ("gemini" | "ollama" | "meditron" | "auto").

    Returns:
        An instantiated LLMBackend.
    """
    choice = (override or LLM_BACKEND).lower()

    if choice == "gemini":
        logger.info("[LLM] Backend: Gemini (explicit)")
        return GeminiBackend()

    if choice in ("ollama", "meditron"):
        logger.info("[LLM] Backend: Ollama/%s (explicit)", OLLAMA_PRIMARY_MODEL)
        return OllamaBackend()

    # Auto routing
    if drug_name and requires_gemini(drug_name, moa):
        logger.info(
            "[LLM] Backend: Gemini (auto-routed — IO/ADC drug class for '%s')", drug_name
        )
        if GEMINI_API_KEY:
            return GeminiBackend()
        logger.warning(
            "[LLM] Gemini routing triggered for '%s' but GEMINI_API_KEY not set. "
            "Falling back to Ollama.",
            drug_name,
        )

    logger.info("[LLM] Backend: Ollama (auto-routed → meditron → llama3.2)")
    return OllamaBackend()


# ─── Pathology System Prompt ──────────────────────────────────────────────────

PATHOLOGY_SYSTEM_PROMPT = """You are a senior computational pathologist and translational oncology researcher 
with expertise in digital pathology, tumor microenvironment biology, and clinical biomarker development.
You work across all cancer types — your recommendations are indication-agnostic unless the evidence is specific.

RULES — follow all of these:
1. Ground your PRIMARY findings in the retrieved evidence provided in this prompt.
2. For features with strong retrieved evidence (catalog Level A/B or direct PubMed hits), report
   what the evidence says — cite it, explain it, and describe how to measure it precisely.
3. For features where the specific drug has limited evidence, you MAY reason by analogy from
   similar drug mechanisms or drug classes. You MUST signal this clearly in your hypothesis
   text using the phrase: "[By analogy from <drug class>]". For example:
   "[By analogy from checkpoint inhibitors] Stromal TIL score is expected to predict response
   given the shared PD-1/PD-L1 axis with established checkpoint biology."
4. You MUST NOT hallucinate citations, PMIDs, or clinical trial results.
5. Return ONLY valid JSON — no markdown, no explanation text, no code fences.
6. Rank features by evidence strength first, then MOA relevance, then analogy confidence.
7. Use standard H&E pathology terminology. Describe the measurement method precisely enough
   that a digital pathologist could implement it in QuPath or similar software.
8. This is tumor-type agnostic — do not restrict your reasoning to a single cancer type
   unless the evidence is specific to one indication.

Your task is to synthesize the provided retrieved H&E pathology evidence into ranked 
Human-Interpretable Feature (HIF) hypotheses for the given drug, combining what was 
directly found in the literature with biologically reasoned analogies from related mechanisms."""


def build_hif_prompt_local(
    drug_name: str,
    moa_class: str,
    evidence_summary: str,
    top_n: int = 5,
) -> str:
    """
    Simplified prompt for local 7B models (meditron, llama3.2).
    Asks for only the essential fields to stay within context limits
    and get reliable JSON output.
    """
    return f"""DRUG: {drug_name}
MOA CLASS: {moa_class}

EVIDENCE:
{evidence_summary[:2000]}

List the top {top_n} H&E pathology features that predict or indicate response to {drug_name}.
Return ONLY a JSON array. Start with [ and end with ]. No other text.

[
  {{
    "rank": 1,
    "feature_name": "feature name",
    "roi": "stroma|tumor_nest|invasive_margin|whole_section|tls",
    "feature_category": "til_score|immune_phenotype|cell_density|spatial_clustering|composite",
    "feature_type": "predictive|prognostic|both",
    "measurement_method": "how to measure on H&E",
    "confidence_score": 80,
    "hypothesis": "2-3 sentence rationale"
  }}
]"""


def build_hif_prompt(
    drug_name: str,
    moa_description: str,
    moa_class: str,
    evidence_summary: str,
    top_n: int = 10,
    pre_ranked_names: list[str] | None = None,
) -> str:
    """
    Build the structured user prompt for HIF hypothesis generation.

    Tumor-type agnostic: no indication is required; evidence spans all cancers.
    Analogical evidence (source="PubMed-Analogical") is flagged in the summary
    so the LLM knows when to prefix with "[By analogy from <drug class>]".

    Args:
        drug_name: Drug name.
        moa_description: Mechanism of action description.
        moa_class: Resolved MOA class (e.g., "checkpoint", "ddr").
        evidence_summary: Pre-formatted evidence context string (direct + analogical).
        top_n: Number of HIFs to generate.
        pre_ranked_names: Unused; kept for API compatibility.

    Returns:
        Formatted prompt string for the LLM.
    """
    return f"""DRUG: {drug_name}
MECHANISM OF ACTION: {moa_description}
MOA CLASS: {moa_class}
SCOPE: Pan-cancer / tumor-type agnostic (all solid tumors unless evidence is indication-specific)

=== RETRIEVED H&E PATHOLOGY EVIDENCE ===
Evidence sources: direct (drug-specific) and analogical (same MOA drug class).
Analogical entries are prefixed with [ANALOGICAL].

{evidence_summary}
=========================================

Generate exactly {top_n} ranked H&E Human-Interpretable Feature (HIF) hypotheses for {drug_name}.
Scope is pan-cancer — applicable to any solid tumor indication.

For features with DIRECT evidence: report the retrieved findings, cite them, explain the mechanism.
For features with ANALOGICAL evidence only: use the "[By analogy from <drug class>]" prefix in
your hypothesis text to signal that you are reasoning from similar mechanisms.
Do NOT hallucinate PMIDs or citation details.

Return a JSON array with this exact schema for each item:
{{
  "rank": <integer>,
  "feature_name": "<HIF name>",
  "roi": "<stroma|tumor_nest|invasive_margin|peritumoral|tls|intraepithelial|vascular|whole_section>",
  "roi_annotation_guide": "<1-sentence guide for annotating this ROI on H&E>",
  "feature_category": "<cell_density|til_score|immune_phenotype|spatial_distance|spatial_clustering|colocalization|neighborhood_composition|composite>",
  "feature_type": "<predictive|prognostic|both|unknown>",
  "measurement_method": "<exact method for H&E digital pathology — precise enough for QuPath>",
  "measurement_unit": "<unit string>",
  "confidence_score": <0-100 float>,
  "predictive_score": <0-100 float>,
  "prognostic_score": <0-100 float>,
  "evidence_level": "<A|B|C|D|null>",
  "evidence_basis": "<direct|analogical|mixed>",
  "drug_relevance": "<brief explanation tying this feature to the drug MOA>",
  "supporting_sources": ["<source_id_1>", "<source_id_2>"],
  "supporting_evidence": [
    {{"source": "<name>", "id": "<id>", "claim": "<claim text>"}}
  ],
  "ranking_rationale": {{
    "in_he_catalog": <true|false>,
    "evidence_level": "<A|B|C|D|null>",
    "pubmed_hits": <integer>,
    "analogical_hits": <integer>,
    "moa_weight_applied": <float>,
    "moa_class": "{moa_class}"
  }},
  "hypothesis": "<2-4 sentences: pathobiological rationale, mechanism link, how to measure. Prefix with [By analogy from {moa_class}] when using analogical reasoning only.>"
}}

Return ONLY the JSON array. Start your response with '[' and end it with ']'. No other text."""
