# MOA-to-HIF Evidence Prioritization Agent

Given a drug name and its mechanism of action (MOA), this tool returns a ranked, evidence-graded list of H&E-derived Human-Interpretable Features (HIFs) likely to be predictive or prognostic for that drug — with ROI annotation guidance, measurement methodology, and evidence provenance for each.

It's built for the situation where you don't yet have trial pathology data: a new or repositioned compound where MOA is the only signal available, and you need a defensible starting hypothesis set for which H&E-derived features to prioritize in a translational/companion-diagnostic workup.

> **Scope:** This is an evidence-synthesis and hypothesis-prioritization tool. It does not ingest whole-slide images, train computer-vision models, extract HIFs from slides, or provide diagnostic or treatment recommendations.

---

## Table of contents

- [Why RAG, not just an LLM](#why-rag-not-just-an-llm)
- [Pipeline](#pipeline)
- [Scoring](#scoring)
- [Quickstart](#quickstart)
- [See it in action](#see-it-in-action)
- [Output schema](#output-schema)
- [More examples](#more-examples)
- [Repo layout](#repo-layout)
- [Design notes / FAQ](#design-notes--faq)
- [License](#license)

---

## Why RAG, not just an LLM

Asking Gemini/GPT/Llama "what H&E features predict response to drug X" directly is unreliable for this task, for reasons specific to the domain:

- **Evidence-level conflation.** An LLM will not reliably distinguish Level A evidence (multiple RCTs, e.g. stromal TIL in TNBC/NSCLC) from Level C/D evidence (single retrospective cohort, or mechanistic inference only) unless that grading is fed to it explicitly. Left alone, it tends to present speculative and well-validated features with equal confidence.
- **Citation fabrication.** LLMs will invent PMIDs or misattribute claims to papers that don't support them — unacceptable when the output is meant to inform a wet-lab or translational workup.
- **MOA-specific weighting is not general medical knowledge.** Whether TILs matter more than TAM density for a given MOA is a function of curated pathway biology (e.g., hypoxia → M2 macrophage polarization; anti-VEGF → vessel normalization → T-cell extravasation) that isn't reliably reconstructed from model weights on demand, and the weighting needs to be inspectable/auditable, not implicit in a generated paragraph.
- **Reproducibility.** A ranking that changes between runs (or with prompt phrasing) is not usable as a scientific output. Stakeholders need to be able to ask "why did feature X outrank feature Y" and get a formula-based answer, not a re-generated LLM justification.

The architecture here enforces a hard separation: **retrieval and ranking are deterministic and LLM-free**; the LLM is invoked only at the end, strictly scoped to the evidence already retrieved, to produce the narrative rationale. It cannot alter scores, add unretrieved evidence, or invent citations. If the LLM call fails or returns malformed output, the pipeline falls back silently to the deterministic ranking with no narrative — it never blocks on the generation step.

Retrieval draws from two sources:

1. **`tools/he_catalog.py`** — a static, hand-curated catalog of ~30 H&E HIFs, each with `evidence_level` (A–D), `moa_classes`, `tumor_types`, ROI annotation guide, measurement method, and supporting PMIDs. Precision-controlled and works fully offline.
2. **`tools/pubmed.py`** — live pan-cancer E-utilities queries per (drug, feature) pair, parsed into evidence records with feature type (predictive/prognostic) inferred from abstract text, to surface drug-specific evidence not yet in the catalog.

## Pipeline

```
drug + MOA description
      │
      ├─ config.py: classify into MOA bucket (checkpoint / ddr / kinase /
      │             antiangiogenic / cell_cycle / hypoxia / bispecific / adc / default)
      │             → category-level feature weights, LLM backend routing
      │
      ├─ HEFeatureAgent: filter catalog by MOA class, score = evidence_level_weight × moa_weight
      │
      ├─ LiteratureAgent: PubMed search per top feature (+ analogical search via proxy
      │                   drugs for bispecific/ADC/hypoxia MOAs lacking direct literature)
      │
      ├─ RankingAgent: aggregate catalog + PubMed + analogical evidence into a single
      │                score per feature, apply macrophage-reliability penalty, normalize
      │                to 0–100, sort. Fully deterministic — no LLM.
      │
      └─ SynthesisAgent: send ranked feature names + their evidence context to Gemini/Ollama
                          with a closed-context prompt ("use ONLY the evidence given").
                          It may fill narrative text only; it cannot alter rank, scores,
                          evidence, or metadata. Falls back to deterministic ranking on failure.
```

Four agents (`agents/`), one orchestrator (`agents/orchestrator.py`) that runs them in sequence with per-step error isolation — a failure in the literature search or LLM step degrades gracefully rather than aborting the run.

## Scoring

```
total_score = catalog_score + pubmed_score + moa_alignment_score
catalog_score = evidence_level_weight × moa_weight × macrophage_penalty
pubmed_score = pubmed_hits × 0.15 × moa_weight
```

- `evidence_level_weight`: A=5, B=4, C=3, D=1.5 (`config.EVIDENCE_LEVEL_WEIGHTS`)
- `moa_weight`: per-category multiplier from `config.MOA_FEATURE_WEIGHTS`, keyed by MOA class (e.g. `checkpoint` weights TIL/TLS/immune-phenotype categories 4–5×; `hypoxia` weights vascular/necrosis categories similarly)
- Macrophage penalty exists because TAMs are unreliable to call from H&E morphology alone (large pale nuclei overlap with plasma cells/dendritic cells on H&E; CD68/CD163 IHC is needed for confident identification) — the 0.25× penalty keeps TAM-based features from outranking more H&E-reliable lymphocyte/stromal features regardless of raw evidence strength.
- Analogical evidence: when no direct literature exists for a MOA (e.g. a first-in-class bispecific), the literature agent searches proxy drugs from a related, better-characterized MOA class (`agents/literature_agent.py: COMPONENT_PROXY_DRUGS`) and evidence is tagged `"evidence_basis": "analogical"` in the output so it's never conflated with direct evidence.

## Quickstart

```bash
cd digital_pathology
pip install -r requirements.txt
# For the validated direct-dependency versions used in CI:
# pip install -r requirements-lock.txt

cp .env.example .env
# GEMINI_API_KEY for narrative synthesis, or omit and use --no-llm for ranking-only

python main.py --drug "pembrolizumab" --moa "PD-1 checkpoint inhibitor"
```

Requires Python 3.10+. `--no-llm` runs the full retrieval + ranking pipeline with zero external dependencies (no API key, no internet needed beyond PubMed if you want live literature — the catalog alone is sufficient to get a ranking).

## See it in action

[`examples/`](examples/) contains three deterministic (`--no-llm`), byte-reproducible sample runs, each showing the same 31-feature catalog producing a completely different ranking depending on MOA class:

| Drug | MOA class | Top feature |
|---|---|---|
| [pembrolizumab](examples/sample_run_pembrolizumab/) (Keytruda) | `checkpoint` | Stromal TIL Score |
| [belzutifan](examples/sample_run_belzutifan/) (Welireg) | `hypoxia` | Tumor-Stroma Ratio (TSR) |
| [trastuzumab deruxtecan](examples/sample_run_trastuzumab_deruxtecan/) (Enhertu, ADC) | `adc` | Tumor Cell Density |

Each folder has the exact command, reconstructed terminal output, and full `results.json`/`features_summary.csv` — useful for inspecting evidence provenance (`evidence_basis: direct` vs `analogical`) and the per-feature ranking rationale breakdown. See [`examples/README.md`](examples/README.md) for the full comparison.

## Output schema

Each ranked `HIFHypothesis` (see `models/schemas.py`) includes:

| Field | Content |
|---|---|
| `roi` / `roi_annotation_guide` | Which region to annotate (stroma, tumor nest, invasive margin, TLS, etc.) and how |
| `measurement_method` | Exact quantification procedure (e.g., "count lymphocytes within stromal ROI, normalize by area") |
| `evidence_level` (A–D) + `evidence_basis` (`direct`/`analogical`) | Strength and provenance of supporting evidence |
| `feature_type` | `predictive`, `prognostic`, or `both` |
| `confidence_score`, `predictive_score`, `prognostic_score` | Normalized 0–100 scores |
| `ranking_rationale` | Full breakdown: catalog inclusion, evidence level, PubMed hit count, analogical hit count, MOA weight applied, raw score — everything needed to audit the ranking without re-running anything |
| `hypothesis` | LLM-generated rationale grounded strictly in `supporting_evidence` (omitted/placeholder if `--no-llm` or LLM failure) |

Written to `output/results.json` (full detail) and `output/features_summary.csv` (flattened, spreadsheet-friendly).

## More examples

```bash
# Deterministic ranking only, no API key needed
python main.py --drug "olaparib" --moa "PARP1/2 inhibitor" --no-llm

# Novel/unclassified MOA falls back to default pan-cancer weighting rather than failing
python main.py --drug "my-drug-001" --moa "TIGIT immune checkpoint inhibitor"

# Truncate to top 5
python main.py --drug "sotorasib" --moa "Covalent KRAS G12C inhibitor" --top-n 5

# Override auto MOA-based backend routing
python main.py --drug "bevacizumab" --moa "Anti-VEGF antibody" --backend gemini
```

## Validation and intended use

This repository demonstrates a reproducible, auditable workflow; it is **not clinically
validated**. Rankings are hypothesis-generating and must be reviewed by qualified
pathologists and translational scientists before use in experimental design. In particular,
PubMed feature type is inferred from abstract text, analogical evidence is explicitly labeled,
and the curated catalog requires periodic expert review.

The tool is for research decision support only—not diagnosis, treatment selection, or any
regulated clinical use. Do not submit patient data, protected health information, or
confidential study information to third-party LLM backends. `--no-llm` avoids LLM calls.

## Repo layout

```
digital_pathology/
├── main.py            CLI entry point, Rich table rendering, JSON/CSV export
├── config.py          MOA classification, evidence/category weights, LLM routing rules
├── agents/            he_feature_agent, literature_agent, ranking_agent, synthesis_agent, orchestrator
├── tools/
│   ├── he_catalog.py  Curated HIF catalog (~30 entries, evidence-graded)
│   ├── pubmed.py       Async NCBI E-utilities client, analogical/proxy-drug search
│   └── cache.py        SQLite-backed diskcache (7-day TTL) for API calls
├── models/schemas.py  Pydantic models: NormalizedPathologyFeature, CandidateHIF, HIFHypothesis, PathologyOutput
├── llm/backend.py     Gemini + Ollama backends, MOA-based auto-routing, grounded prompts
├── examples/          Sample run with full input/output for inspection without execution
├── output/            Your run outputs land here
└── docs/ARCHITECTURE.md   Agent-by-agent internals, full scoring derivation, design rationale
```

## Design notes / FAQ

**Why is ranking fully separated from generation?** So the ranking is auditable and reproducible independent of LLM behavior/availability — a requirement for anything meant to inform a real translational decision, not just a demo.

**What's the fallback behavior if the LLM call fails?** Silent degrade to deterministic ranking with a placeholder hypothesis string; the pipeline's `successful_sources`/`failed_sources` fields in `results.json` record exactly what happened, so failures are visible in output even when the run doesn't error.

**How does an unclassified/novel MOA get handled?** Falls back to `config.py`'s `default` bucket — balanced weighting across all feature categories rather than refusing to run, on the assumption that a broad, well-evidenced pan-cancer feature set is more useful than nothing when MOA-specific data doesn't exist yet.

**Where's the deeper technical writeup?** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — full agent internals, the six-way MOA routing table with example drugs, the ROI-type catalog structure, and worked-through interview-style Q&A on design decisions.

## License

Released under the [MIT License](LICENSE).
