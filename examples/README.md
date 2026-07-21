# Examples

This folder shows the MOA-to-HIF Evidence Prioritization Agent actually working, without you needing an
API key or network access just to see what it produces.

## Sample run: `belzutifan` (HIF-2alpha inhibitor)

[`sample_run_belzutifan/`](sample_run_belzutifan/) contains a deterministic,
catalog-only run of the pipeline against **belzutifan** (HIF-2alpha inhibitor,
hypoxia pathway, VHL-mutant tumors). It was generated with `--no-llm`; therefore,
the snapshot contains no model-generated narrative or external PubMed results.

| File | What it is |
|---|---|
| [`command.txt`](sample_run_belzutifan/command.txt) | The exact CLI command that produced this output |
| [`terminal_output.txt`](sample_run_belzutifan/terminal_output.txt) | What prints to the terminal (Rich table and measurement metadata) |
| [`results.json`](sample_run_belzutifan/results.json) | Full structured output — every ranked feature, its ROI, measurement method, and evidence |
| [`features_summary.csv`](sample_run_belzutifan/features_summary.csv) | Spreadsheet-friendly version of the same ranking |

Top of the ranking for this run:

1. **Tumor-Stroma Ratio (TSR)** — evidence level A, prognostic
2. **Tumor Cell Density** — evidence level B, prognostic
3. **Stromal Ratio** — evidence level B, prognostic
4. **Tumor-Associated Macrophage Density** — evidence level B, both
5. **Tumor Necrosis Fraction** — evidence level B, prognostic

Notice how the ranking is driven by the `hypoxia` MOA class weights (`config.py`) plus
evidence level — no clinical trial data existed for belzutifan + H&E features when this
catalog entry logic was written, this snapshot is deliberately catalog-only. Use a live
PubMed run to retrieve and label any direct or analogical literature evidence.

## Running it yourself

To reproduce this (or run your own drug/MOA):

```bash
cd digital_pathology
pip install -r requirements.txt
cp .env.example .env
# Fill in GEMINI_API_KEY in .env if you want LLM narrative synthesis,
# otherwise leave it blank and use --no-llm below.

python main.py --drug "belzutifan" --moa "HIF-2alpha inhibitor hypoxia pathway VHL-mutant tumors" --no-llm
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
