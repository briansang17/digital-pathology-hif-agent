# Digital Pathology HIF Agent

**What it does in one sentence:**
You give it a cancer drug name, how the drug works (its mechanism of action), and optionally a tumor type — and it returns a ranked list of Human-Interpretable Features (HIFs) that a pathologist should look for and measure on an H&E slide to determine whether a patient is likely to respond to that drug or has a better or worse prognosis.

---

## Quickstart

```bash
cd digital_pathology
pip install -r requirements.txt

cp .env.example .env
# Add GEMINI_API_KEY for LLM narrative synthesis, or leave blank and use --no-llm

python main.py --drug "pembrolizumab" --moa "PD-1 checkpoint inhibitor"
```

That's it — ranked H&E features print to the terminal and are saved to
`output/results.json` and `output/features_summary.csv`. See
[`examples/`](examples/) for a real sample run (input + full output) you can inspect
without running anything yourself.

**Requirements:** Python 3.10+. Optional: a [Gemini API key](https://aistudio.google.com/apikey)
for LLM narrative synthesis, or a local [Ollama](https://ollama.com/) install for the
`ollama`/`meditron` backends. Neither is required to get ranked results — use `--no-llm`
for the deterministic ranking only.

## Contents

- [The Problem It Solves](#the-problem-it-solves)
- [What Is an H&E Slide?](#what-is-an-he-slide)
- [What Is a Human-Interpretable Feature (HIF)?](#what-is-a-human-interpretable-feature-hif)
- [Why This Is an LLM + RAG System](#why-this-is-an-llm--rag-system)
- [How the Pipeline Works — Step by Step](#how-the-pipeline-works--step-by-step)
- [The Four Agents](#the-four-agents--what-each-one-does-and-why-it-exists)
- [The Knowledge Base](#the-knowledge-base--toolshe_catalogpy)
- [The MOA Routing System](#the-moa-routing-system--configpy)
- [Files at a Glance](#files-at-a-glance)
- [How to Run It](#how-to-run-it)
- [See It in Action](#see-it-in-action)
- [Interview Talking Points](#interview-talking-points)
- [License](#license)

---

## The Problem It Solves

When a new drug enters clinical development, one of the first questions a translational scientist asks is:

> *"If I look at a tumor biopsy under the microscope — just a standard H&E stain — what should I actually be looking for? What cell types, spatial patterns, or tissue features tell me something meaningful about whether this drug will work?"*

This is not a trivial question. The answer depends on the drug's mechanism, the biology of the tumor microenvironment, and decades of pathology literature. Answering it manually means reading hundreds of papers, synthesizing evidence across different cancer types, and knowing which features are reliably measurable on H&E versus requiring special stains.

This system automates that synthesis. It is designed specifically for **new or novel drugs** where the mechanism of action (MOA) gives clues about what to look for — even before any clinical trial pathology data exists.

---

## What Is an H&E Slide?

H&E stands for Hematoxylin and Eosin — the standard stain used in pathology for over 100 years. Hematoxylin stains cell nuclei blue-purple. Eosin stains cytoplasm and connective tissue pink. Together they show the architecture of a tumor: how the cancer cells are arranged, what the surrounding tissue looks like, and crucially — whether immune cells are present and where.

**Why H&E first?** Because every clinical biopsy gets an H&E slide. It is cheap, universal, and done routinely. Unlike molecular assays or special IHC stains, you do not need to order anything extra. If you can extract meaningful prognostic or predictive information from H&E alone, that information is available for every patient in your trial immediately.

---

## What Is a Human-Interpretable Feature (HIF)?

A HIF is a measurable quantity from a pathology image that a human — either a pathologist or a computational tool — can extract and report as a number. Examples:

- **Stromal TIL Score**: What percentage of the stroma (the connective tissue around the tumor) is occupied by lymphocytes? Reported as a percentage (e.g., 30%).
- **Intratumoral TIL Density**: How many lymphocytes per mm² are inside the tumor cell nests?
- **Immune Phenotype**: Is the tumor "inflamed" (immune cells throughout), "excluded" (immune cells only at the border), or "desert" (no immune cells)?
- **TLS Presence**: Are there organized clusters of lymphocytes forming tertiary lymphoid structures — essentially mini lymph nodes inside the tumor?

Each HIF has a specific Region of Interest (ROI) where it is measured and a defined method so that different pathologists or algorithms produce the same number.

---

## Why This Is an LLM + RAG System

This system uses two distinct AI components: **RAG** (Retrieval-Augmented Generation) and an **LLM** (Large Language Model). It is important to understand what each one does and why both are needed.

### What Is RAG?

RAG stands for Retrieval-Augmented Generation. The idea is simple: instead of asking an LLM a question from memory alone (which leads to hallucination), you first **retrieve** relevant facts from trusted sources, then **augment** the LLM's input with those facts, and only then ask the LLM to **generate** a response.

In this system, the retrieval step has two sources:

1. **The H&E Feature Catalog** (`tools/he_catalog.py`) — a structured, curated knowledge base of 25+ H&E HIFs, each with evidence levels, measurement methods, ROI annotation guides, and supporting PMIDs. This is hand-curated domain knowledge — it cannot hallucinate because it is a static structured database.

2. **PubMed Literature Search** (`tools/pubmed.py`) — a live query to PubMed that searches for articles connecting the specific drug, the specific H&E feature, and the specific tumor type. This ensures the system is grounded in published literature for that exact drug context.

**Why not just ask the LLM directly?**
An LLM like Gemini or Llama has general medical knowledge, but it does not know specifically which H&E features have Level A clinical evidence in NSCLC for PD-1 checkpoint inhibitors versus Level C evidence for KRAS inhibitors. It will blend and confuse. By retrieving structured evidence first and feeding it into the LLM as a controlled input, the LLM can only interpret what is there — it cannot invent citations or inflate evidence levels.

---

## How the Pipeline Works — Step by Step

```
You run:
  python main.py --drug "pembrolizumab" --moa "PD-1 checkpoint inhibitor"

                        ↓

Step 1 — MOA Classification (config.py)
  The drug + MOA is classified into a bucket:
  "checkpoint" → tells the system to heavily weight TIL, immune phenotype, TLS features
  "kinase" → weights tumor cell density, general TME features
  "ddr" → weights TIL features + DNA damage context
  etc.
  This happens deterministically — no LLM needed.

                        ↓

Step 2 — H&E Catalog Query (HEFeatureAgent)
  The catalog is filtered by MOA class and scored.
  A "checkpoint" MOA query returns stromal TIL score with a 5× weight,
  TLS features with a 4× weight, and macrophage features with a 0.25× penalty.
  Every feature gets a strength score = evidence_level_weight × moa_category_weight.

                        ↓

Step 3 — PubMed Literature Search (LiteratureAgent)
  For each top feature from the catalog, PubMed is queried:
  e.g., "Stromal TIL Score" + "pembrolizumab" + "NSCLC"
  Results are parsed and turned into evidence records with inferred feature type
  (predictive vs prognostic) based on keywords in the abstract.
  These records add to each feature's evidence pool.

                        ↓

Step 4 — Deterministic Ranking (RankingAgent)
  All evidence (catalog + PubMed) is aggregated per feature.
  Each feature gets a composite score:
    catalog_score = evidence_level_weight × moa_weight
    pubmed_score  = 0.15 per article × moa_weight
    moa_score     = category alignment weight
    + analogical evidence from similar MOA drug class
    + macrophage penalty if applicable
  Features are sorted. The top N are converted to HIFHypothesis objects.
  No LLM is involved in this step. The ranking is reproducible and auditable.

                        ↓

Step 5 — LLM Narrative Synthesis (SynthesisAgent)
  The pre-ranked features + evidence context are sent to the LLM with a strict prompt:
  "Use ONLY the retrieved evidence. Write a 2-3 sentence biological rationale
   for why this feature matters for this drug and how to measure it."
  The LLM adds the narrative (the "why") but cannot change the ranking or invent sources.
  If the LLM fails, the system falls back to the deterministic ranking silently.

                        ↓

Output:
  - Terminal Rich table
  - output/results.json
  - output/features_summary.csv
```

---

## The Four Agents — What Each One Does and Why It Exists

### 1. HEFeatureAgent (`agents/he_feature_agent.py`)

**What it does:**
Queries the structured H&E catalog and returns all features that are relevant for the given MOA class and tumor type. Assigns strength scores based on clinical evidence level and MOA alignment.

**Why it exists:**
You need a deterministic, auditable first pass before the LLM gets involved. The catalog is the ground truth — it encodes what we already know from the literature. The agent's job is to filter and score that knowledge, not to invent new knowledge.

**Why MOA matters here:**
A checkpoint inhibitor and a CDK4/6 inhibitor both get stromal TIL scored — but the weight is different. TILs are highly predictive for checkpoint inhibitors (Level A evidence across multiple RCTs) and moderately prognostic for CDK4/6 inhibitors. By assigning MOA-specific weights at this step, the ranking naturally surfaces the most drug-relevant features at the top.

---

### 2. LiteratureAgent (`agents/literature_agent.py`)

**What it does:**
Searches PubMed for each top H&E feature combined with the drug name and tumor type. Returns NormalizedPathologyFeature records from matched abstracts, with evidence type (predictive vs prognostic) inferred from the abstract text.

**Why it exists:**
The catalog is curated but cannot cover every drug-feature combination. For a new drug, there may be pre-clinical or early clinical data in PubMed that is not yet in the catalog. The literature agent provides fresh, drug-specific evidence that personalizes the ranking beyond generic pathway knowledge.

**Why this is RAG and not just prompting:**
The PubMed results are fetched, parsed, and structured *before* the LLM sees anything. The LLM is never asked to recall papers from memory. This is the fundamental difference between RAG and naive prompting: the facts come from a retrieval system, not from model weights.

---

### 3. RankingAgent (`agents/ranking_agent.py`)

**What it does:**
Aggregates all evidence into per-feature scoring accumulators (CandidateHIF objects), normalizes scores to 0–100, and returns a ranked list ready for LLM synthesis.

**Why it exists:**
This is perhaps the most important architectural decision in the system. The LLM never decides the ranking. A dedicated, deterministic scoring engine does. This means:

- The output is reproducible — run it twice, get the same ranking
- The ranking logic is transparent — you can inspect every weight
- The LLM cannot hallucinate a poorly-evidenced feature into the top spot
- You can audit why feature X ranked above feature Y without asking the LLM to explain itself

The scoring formula is:
```
total_score = (evidence_level × moa_weight) + (pubmed_hits × 0.15 × moa_weight)
            + tumor_type_boost (if applicable)
            × macrophage_penalty (if applicable, × 0.25)
```

**Why macrophage features are penalized:**
Macrophages are extremely hard to identify reliably on H&E alone. Their large, pale nuclei can look similar to other mononuclear cells (plasma cells, dendritic cells). To confidently identify macrophages, you need IHC with CD68 or CD163. If this system recommended macrophage density as a top H&E feature, it would be scientifically misleading. The 0.25× penalty ensures macrophage-based features always rank below lymphocyte and stromal features, which are far more reliable on H&E.

---

### 4. SynthesisAgent (`agents/synthesis_agent.py`)

**What it does:**
Sends the pre-ranked features plus the retrieved evidence context to the LLM. The LLM generates a 2-3 sentence biological rationale for each feature explaining the drug relevance and measurement approach. Validates the output with Pydantic and retries once on JSON failure.

**Why it exists:**
Numbers alone are not enough. A researcher reading the output needs to understand *why* stromal TIL score matters for a PD-1 inhibitor specifically — not just that it ranks first. The LLM is very good at synthesizing causal explanations from structured evidence. By restricting it strictly to the provided evidence context, we get the fluency of an LLM with the factual grounding of a retrieval system.

**Why the fallback matters:**
If the LLM is unavailable, too slow, or returns malformed JSON, the system silently returns the deterministic ranking with a placeholder hypothesis. The pipeline never fails because of an LLM failure. This is by design — the ranking is the scientific output. The narrative is a UX enhancement.

---

## The Knowledge Base — `tools/he_catalog.py`

This is the heart of the system. It is a curated list of H&E HIFs organized around:

**ROI Type** — which region of the slide to annotate before measuring:

| ROI | What it is | Example features |
|---|---|---|
| `stroma` | Fibrous connective tissue around tumor nests | Stromal TIL Score (%) |
| `tumor_nest` | Inside the tumor cell clusters | Intratumoral TIL Density, Tumor Cell Density |
| `invasive_margin` | Leading edge where tumor meets stroma | Margin TIL Density, Immunoscore |
| `tls` | Organized lymphoid follicles near tumor | TLS Presence, TLS Maturity |
| `peritumoral` | ~2mm zone surrounding the tumor | Peritumoral Immune Infiltrate |
| `intraepithelial` | Inside the epithelial layer | Intraepithelial Lymphocyte Count |
| `whole_section` | No specific ROI needed | Immune Phenotype, TIL Heterogeneity |

Each catalog entry contains:
- `evidence_level` (A/B/C/D) — how strong the clinical evidence is
- `moa_classes` — which drug classes this feature is relevant for
- `tumor_types` — tumor types with published evidence (empty = pan-cancer)
- `roi_annotation_guide` — step-by-step instruction for annotating the ROI
- `measurement_method` — exactly how to compute the feature
- `claim` — one-sentence summary of the evidence
- `references` — supporting PMIDs

**Why hardcode this knowledge base rather than retrieve it from a database?**
Because the H&E feature evidence space is relatively stable and well-defined. The major TIL scoring guidelines (TIIC Working Group, Immunoscore, TLS maturity criteria) do not change frequently. A curated catalog guarantees precision, controls what the LLM sees, and makes the system runnable offline without external dependencies.

---

## The MOA Routing System — `config.py`

When you input a drug + MOA, the system classifies it into one of six buckets:

| MOA Class | Example drugs | What H&E features get boosted |
|---|---|---|
| `checkpoint` | pembrolizumab, nivolumab, atezolizumab | Stromal TIL, intratumoral TIL, immune phenotype, TLS |
| `ddr` | olaparib, niraparib, platinum | TIL (BRCAness), lymphocyte infiltrate |
| `kinase` | osimertinib, sotorasib, abemaciclib | Tumor cell density, stromal ratio, general TME |
| `antiangiogenic` | bevacizumab, ramucirumab | Stromal features, vascular context |
| `cell_cycle` | palbociclib, ribociclib | Cell density, mitotic index, TIL |
| `default` | Any novel or unclassified drug | Balanced weights across all categories |

For **new drugs** where the MOA is experimental, the system falls back to `default` weights — which means it surfaces all well-evidenced H&E features equally. This is intentional: if you do not know what to look for, the catalog provides a comprehensive survey of the most clinically validated H&E features across all tumor types.

The same routing logic also controls which LLM backend is used:
- IO drugs (checkpoint, bispecific, ADC) → routed to **Gemini** (complex TIL landscape)
- All other drugs → **Ollama/meditron** locally (simpler TME biology)

---

## How Everything Fits Together

```
Drug + MOA + Tumor Type
        │
        ├─ config.py classifies MOA → weights for each feature category
        │
        ├─ HEFeatureAgent queries he_catalog.py → retrieves relevant HIFs
        │        ↑
        │   RETRIEVAL (R in RAG) — structured knowledge base
        │
        ├─ LiteratureAgent queries PubMed → retrieves drug-specific papers
        │        ↑
        │   RETRIEVAL (R in RAG) — live literature
        │
        ├─ RankingAgent scores all evidence deterministically
        │        ↑
        │   No LLM — pure scoring math
        │
        └─ SynthesisAgent sends ranked features + evidence → LLM
                 ↑
          GENERATION (G in RAG) — LLM writes rationale ONLY from retrieved evidence
                 │
                 ↓
        HIFHypothesis list with narrative, scores, ROI, measurement method
```

The strict separation between retrieval, ranking, and generation is what makes this system trustworthy for clinical research use.

---

## Files at a Glance

```
digital_pathology/
├── main.py                  CLI entry point
├── config.py                MOA routing, scoring weights, LLM routing
├── .env.example             Environment variable template
├── requirements.txt         Python dependencies
│
├── models/
│   └── schemas.py           All Pydantic data models
│                            NormalizedPathologyFeature — evidence record (like a DB row)
│                            CandidateHIF — scoring accumulator (internal)
│                            HIFHypothesis — final ranked output object
│                            PathologyOutput — top-level pipeline result
│                            ROIType enum — stroma/tumor_nest/tls/etc.
│
├── tools/
│   ├── he_catalog.py        Curated H&E HIF knowledge base (25+ features)
│   ├── pubmed.py            PubMed E-utilities API client (async, cached)
│   └── cache.py             SQLite-backed diskcache (7-day TTL)
│
├── agents/
│   ├── he_feature_agent.py  Step 1: catalog query + MOA weighting
│   ├── literature_agent.py  Step 2: PubMed search per feature
│   ├── ranking_agent.py     Step 3: deterministic scoring engine
│   ├── synthesis_agent.py   Step 4: LLM narrative (grounded)
│   └── orchestrator.py      Master pipeline coordinator
│
├── llm/
│   └── backend.py           Gemini + Ollama backends, smart routing
│
├── output/                  results.json, features_summary.csv
└── logs/                    digpath.log
```

---

## How to Run It

```bash
# Install dependencies
cd digital_pathology
pip install -r requirements.txt

# Copy and fill in environment variables
cp .env.example .env
# Add GEMINI_API_KEY if using Gemini, or leave blank for local Ollama

# Run for a checkpoint inhibitor
python main.py --drug "pembrolizumab" --moa "PD-1 checkpoint inhibitor"

# Run for a PARP inhibitor, skip LLM narrative
python main.py --drug "olaparib" --moa "PARP1/2 inhibitor" --no-llm

# Run for a novel drug — uses default pan-cancer weights
python main.py --drug "my-drug-001" --moa "TIGIT immune checkpoint inhibitor"

# Run for any drug, get top 5 features
python main.py --drug "sotorasib" --moa "Covalent KRAS G12C inhibitor" --top-n 5
```

**Outputs:**
- Terminal: ranked table with feature name, category, type, confidence score, evidence level
- `output/results.json` — full structured output including ROI annotation guides
- `output/features_summary.csv` — spreadsheet-friendly version

---

## See It in Action

[`examples/sample_run_belzutifan/`](examples/sample_run_belzutifan/) contains a real,
unedited run against **belzutifan** (a HIF-2alpha inhibitor) — the exact command, the
reconstructed terminal output, and the full `results.json` / `features_summary.csv` it
produced. Top of that ranking:

1. **Tumor-Stroma Ratio (TSR)** — evidence level A, prognostic
2. **Tumor Cell Density** — evidence level B, prognostic
3. **Stromal Ratio** — evidence level B, prognostic
4. **Tumor-Associated Macrophage Density** — evidence level B, both (analogical evidence)
5. **Perivascular TIL Density** — evidence level C, predictive

See [`examples/README.md`](examples/README.md) for the full breakdown and more commands
to try against other drug classes.

---

## Interview Talking Points

**"What problem does this solve?"**
In early oncology drug development, teams need to decide which pathology features to measure in their biopsy specimens. Doing this manually requires reading 50+ papers per drug. This system does it in minutes by retrieving structured evidence and using an LLM only for narrative synthesis — not for discovery.

**"How is this different from just asking ChatGPT?"**
ChatGPT would hallucinate references, confuse evidence levels across different drugs, and not know which specific features have clinical-grade evidence versus pre-clinical data. This system retrieves from a curated structured database first, ranks deterministically without any LLM, and only uses the LLM for the narrative — strictly constrained to the retrieved evidence.

**"What is RAG?"**
Retrieval-Augmented Generation. You retrieve facts first (from databases and PubMed), attach them to the LLM's input, and the LLM generates language grounded in what was retrieved — not from its training weights. It prevents hallucination for domain-specific scientific applications.

**"Why is the ranking done without an LLM?"**
Because rankings need to be reproducible and auditable. An LLM ranking would change slightly each time, be influenced by phrasing, and could not explain its reasoning in a formula. A deterministic scoring engine produces the same output every time and every weight is inspectable. The LLM adds fluency to the output — it does not control what the output says.

**"How does the system handle a brand new drug nobody has written about?"**
It falls back to `default` MOA weights and returns the most broadly-evidenced H&E features for pan-cancer use. It also runs a PubMed search against the drug name even if nothing comes back — in which case the ranking is entirely catalog-driven. The system degrades gracefully rather than failing.

---

## License

Released under the [MIT License](LICENSE).
