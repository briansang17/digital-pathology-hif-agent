# Examples

This folder shows the Digital Pathology HIF Agent actually working, without you needing an
API key or network access just to see what it produces.

## Sample run: `belzutifan` (HIF-2alpha inhibitor)

[`sample_run_belzutifan/`](sample_run_belzutifan/) contains a real, unedited run of the
pipeline against the drug **belzutifan** (mechanism: HIF-2alpha inhibitor, hypoxia
pathway, VHL-mutant tumors) using the Gemini backend for narrative synthesis:

| File | What it is |
|---|---|
| [`command.txt`](sample_run_belzutifan/command.txt) | The exact CLI command that produced this output |
| [`terminal_output.txt`](sample_run_belzutifan/terminal_output.txt) | What prints to the terminal (Rich table + narrative), reconstructed from the JSON below |
| [`results.json`](sample_run_belzutifan/results.json) | Full structured output — every ranked feature, its ROI, measurement method, evidence, and LLM-generated hypothesis |
| [`features_summary.csv`](sample_run_belzutifan/features_summary.csv) | Spreadsheet-friendly version of the same ranking |

Top of the ranking for this run:

1. **Tumor-Stroma Ratio (TSR)** — evidence level A, prognostic
2. **Tumor Cell Density** — evidence level B, prognostic
3. **Stromal Ratio** — evidence level B, prognostic
4. **Tumor-Associated Macrophage Density** — evidence level B, both (analogical evidence from hypoxia biology)
5. **Perivascular TIL Density** — evidence level C, predictive

Notice how the ranking is driven by the `hypoxia` MOA class weights (`config.py`) plus
evidence level — no clinical trial data existed for belzutifan + H&E features when this
catalog entry logic was written, so several features (e.g. Stromal TIL Score, Intratumoral
TIL Density) are flagged `"evidence_basis": "analogical"`, meaning they were reasoned about
by analogy from anti-angiogenic drug biology rather than direct published evidence.

## Running it yourself

To reproduce this (or run your own drug/MOA):

```bash
cd digital_pathology
pip install -r requirements.txt
cp .env.example .env
# Fill in GEMINI_API_KEY in .env if you want LLM narrative synthesis,
# otherwise leave it blank and use --no-llm below.

python main.py --drug "belzutifan" --moa "HIF-2alpha inhibitor hypoxia pathway VHL-mutant tumors"
```

Deterministic mode (no LLM narrative, no API key needed — only the ranking, no prose):

```bash
python main.py --drug "belzutifan" --moa "HIF-2alpha inhibitor hypoxia pathway VHL-mutant tumors" --no-llm
```

Every run overwrites `output/results.json` and `output/features_summary.csv` in the repo
root — copy them elsewhere (as done here) if you want to keep a snapshot.

## Try other drugs

The catalog + MOA routing in [`../config.py`](../config.py) covers several mechanism
classes out of the box. A few more commands to try:

```bash
python main.py --drug "pembrolizumab" --moa "PD-1 checkpoint inhibitor"
python main.py --drug "olaparib" --moa "PARP1/2 inhibitor" --no-llm
python main.py --drug "sotorasib" --moa "Covalent KRAS G12C inhibitor" --top-n 5
```

See the main [README](../README.md) for a full explanation of the pipeline, agents, and
scoring logic.
