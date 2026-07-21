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
