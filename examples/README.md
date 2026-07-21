# Examples

This folder shows the MOA-to-HIF Evidence Prioritization Agent actually working, without you needing an
API key or network access just to see what it produces.

All three snapshots below were generated with `--no-llm` (deterministic ranking only,
no API key needed) and are byte-reproducible — running the same command again produces
identical output. Each demonstrates the MOA-routing logic surfacing a completely
different set of top features from the same 31-entry catalog, purely because the drug's
mechanism of action changes which feature categories get weighted higher.

| Drug | Brand | MOA class | Top feature |
|---|---|---|---|
| [`sample_run_pembrolizumab/`](sample_run_pembrolizumab/) | Keytruda | `checkpoint` | Stromal TIL Score |
| [`sample_run_belzutifan/`](sample_run_belzutifan/) | Welireg | `hypoxia` | Tumor-Stroma Ratio (TSR) |
| [`sample_run_trastuzumab_deruxtecan/`](sample_run_trastuzumab_deruxtecan/) | Enhertu | `adc` | Tumor Cell Density |

Two more folders, [`sample_run_pembrolizumab_live_llm/`](sample_run_pembrolizumab_live_llm/) and
[`sample_run_belzutifan_live_llm/`](sample_run_belzutifan_live_llm/), are **live** runs with a real
Gemini API key and a live PubMed search (not reproducible byte-for-byte, since literature
results and LLM phrasing can vary run to run) — see below.

Each folder contains the same four files:

| File | What it is |
|---|---|
| `command.txt` | The exact CLI command that produced this output |
| `terminal_output.txt` | What prints to the terminal (Rich table and measurement metadata) |
| `results.json` | Full structured output — every ranked feature, its ROI, measurement method, and evidence |
| `features_summary.csv` | Spreadsheet-friendly version of the same ranking |

## Sample run: `pembrolizumab` (PD-1 checkpoint inhibitor)

MOA class detected: **`checkpoint`**. Nearly every top-ranked feature is TIL/immune-related:

1. **Stromal TIL Score** — evidence level A, both
2. **Immunoscore** — evidence level A, prognostic
3. **Intratumoral TIL Density** — evidence level B, both
4. **Invasive Margin TIL Density** — evidence level B, both
5. **Immune Phenotype Classification** — evidence level B, predictive

Makes sense: PD-1 blockade's entire mechanism is unleashing T-cell activity, so
immune-infiltration features dominate the ranking.

## Sample run: `belzutifan` (HIF-2alpha inhibitor)

MOA class detected: **`hypoxia`**. Ranking shifts to vascular/necrosis/stromal features:

1. **Tumor-Stroma Ratio (TSR)** — evidence level A, prognostic
2. **Tumor Cell Density** — evidence level B, prognostic
3. **Stromal Ratio** — evidence level B, prognostic
4. **Tumor-Associated Macrophage Density** — evidence level B, both
5. **Tumor Necrosis Fraction** — evidence level B, prognostic

Belzutifan blocks HIF-2alpha, reducing VEGF-driven angiogenesis and hypoxia-related
necrosis — so vascular and necrosis features rank highest, not immune ones.

## Sample run: `trastuzumab deruxtecan` (HER2-targeted ADC)

MOA class detected: **`adc`**. Ranking favors proliferation/density features relevant
to a DNA-damaging cytotoxic payload:

1. **Tumor Cell Density** — evidence level B, prognostic
2. **Stromal Ratio** — evidence level B, prognostic
3. **Tumor-Associated Macrophage Density** — evidence level B, both
4. **Tumor Necrosis Fraction** — evidence level B, prognostic
5. **Stromal Vascular Density** — evidence level B, both

Mitotic Index and Nuclear Pleomorphism Score (ranks 6–7) also surface here — both
reflect vulnerability to topoisomerase/DNA-damaging payloads like deruxtecan, and
don't rank at all for the checkpoint or hypoxia runs above.

## Sample run: `pembrolizumab`, live PubMed + Gemini synthesis

Unlike the three snapshots above (`--no-llm`, catalog only), this run used a real
`GEMINI_API_KEY` and let the `LiteratureAgent` hit the live NCBI PubMed API instead of
relying only on the curated catalog. It found real literature and folded it into the
ranking:

```
[LiteratureAgent] Found 5 records (0 direct, 5 analogical) | 5 unique PMIDs
```

**Immune Phenotype Classification** — normally ranked #5 on catalog evidence alone —
picked up 5 real PubMed abstracts via analogical search (MOA-class-level query, since no
drug-specific hits existed) and moved up to **rank #3**, with `evidence_basis: "mixed"`:

```json
"evidence_basis": "mixed",
"supporting_sources": ["he_immune_phenotype", "PMID:34571969", "PMID:35538548", "PMID:33579421", "PMID:31942077"],
"ranking_rationale": { "analogical_hits": 5, "raw_score": 94.18 }
```

The `hypothesis` field is Gemini's narrative summary — written from the retrieved
evidence only, with no ability to alter rank, score, or evidence_basis (see
[`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) for how that separation is enforced).

Note: NCBI's public E-utilities API rate-limits unauthenticated traffic to ~3
requests/sec. Since this pipeline fires several parallel PubMed queries per run, some
queries may return `429 Too Many Requests` — cached/retried queries usually succeed on a
second run. Set `NCBI_API_KEY` in `.env` for a much higher rate limit in production use.

## Sample run: `belzutifan`, live PubMed + Gemini synthesis

Same idea, different MOA class (`hypoxia`, which auto-routes to Ollama by default — this
run used `--backend gemini` to force the Gemini narrative path instead). Again, live
PubMed evidence changed the ranking, not just the prose:

```
[LiteratureAgent] Found 5 records (0 direct, 5 analogical) | 5 unique PMIDs
```

**Tumor Cell Density** (already rank #1 on catalog evidence) picked up 5 real
hypoxia/anti-angiogenic PubMed abstracts via analogical search — papers on HIF-1α
suppression in NSCLC, tumor hypoxia/radiation dynamics, and MRI-based hypoxia risk
assessment in cervical cancer — pushing its `evidence_basis` to `"mixed"`:

```json
"evidence_basis": "mixed",
"supporting_sources": ["he_tumor_cell_density", "PMID:16494521", "PMID:41041327", "PMID:38556173", "PMID:26461001"],
"ranking_rationale": { "analogical_hits": 5, "raw_score": 106.5 }
```

Gemini's narrative even flags analogical reasoning explicitly for one feature: *"[By
analogy from hypoxia] HIF-2alpha inhibition by belzutifan may reduce hypoxia-driven M2
polarization..."* — because that feature's only literature support came from the
MOA-class-level search, not belzutifan-specific studies (belzutifan is a newer drug with
sparse dedicated pathology literature).

## Running it yourself

To reproduce any of these (or run your own drug/MOA):

```bash
cd digital_pathology
pip install -r requirements.txt
cp .env.example .env
# Fill in GEMINI_API_KEY in .env if you want LLM narrative synthesis,
# otherwise leave it blank and use --no-llm below.

python main.py --drug "belzutifan" --moa "HIF-2alpha inhibitor hypoxia pathway VHL-mutant tumors" --no-llm
```

Every run overwrites `output/results.json` and `output/features_summary.csv` in the repo
root — copy them elsewhere (as done here) if you want to keep a snapshot.

## Try other drugs

The catalog + MOA routing in [`../config.py`](../config.py) covers several mechanism
classes out of the box. A few more commands to try:

```bash
python main.py --drug "olaparib" --moa "PARP1/2 inhibitor" --no-llm
python main.py --drug "lenvatinib" --moa "Multi-kinase inhibitor targeting VEGFR1-3, FGFR1-4, and RET; anti-angiogenic" --no-llm
python main.py --drug "sotorasib" --moa "Covalent KRAS G12C inhibitor" --top-n 5
```

See the main [README](../README.md) for a full explanation of the pipeline, agents, and
scoring logic.
