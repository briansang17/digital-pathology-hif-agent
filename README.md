# Digital Pathology HIF Agent

**In plain terms:** you tell it a cancer drug's name and how it works, and it tells you what to look for under the microscope on a regular biopsy slide to predict whether that drug will help the patient.

---

## The idea

Every tumor biopsy gets stained with a simple, cheap dye combo called **H&E** (it colors cell nuclei purple and everything else pink). Pathologists have found that certain visible patterns on that slide — like how many immune cells surround a tumor, or how dense the tumor cells are — can hint at whether a drug will work.

Figuring out *which* patterns matter for a *specific* drug normally means a scientist reading dozens of research papers. This tool automates that:

1. It looks up a curated list of ~30 known slide patterns (called **HIFs** — Human-Interpretable Features) and how strong the evidence is for each one.
2. It searches PubMed for papers connecting that specific drug to those patterns.
3. It scores and ranks the patterns using clear, math-based rules (no AI guessing here — this part is 100% reproducible).
4. Optionally, it uses an AI model (Gemini or a local Ollama model) to write a short, plain-English explanation for the top results — but the AI can only use the evidence it was given, so it can't make things up.

## Quickstart

```bash
cd digital_pathology
pip install -r requirements.txt

cp .env.example .env
# Add a GEMINI_API_KEY to get AI-written explanations, or skip this and use --no-llm

python main.py --drug "pembrolizumab" --moa "PD-1 checkpoint inhibitor"
```

You'll see a ranked table print to your terminal, and it also gets saved to
`output/results.json` and `output/features_summary.csv`.

**Requirements:** Python 3.10+. Everything else (an AI backend) is optional — the tool
works fully offline with `--no-llm`.

## See it in action

Don't want to run anything? [`examples/sample_run_belzutifan/`](examples/sample_run_belzutifan/)
has a real, complete run for the drug **belzutifan** — the command used, the output it
produced, and a plain-text version of what prints to the terminal.

## More examples

```bash
# Skip the AI explanation, just get the ranked list
python main.py --drug "olaparib" --moa "PARP1/2 inhibitor" --no-llm

# A brand-new/experimental drug still works — it falls back to general best-evidence patterns
python main.py --drug "my-drug-001" --moa "TIGIT immune checkpoint inhibitor"

# Only show the top 5
python main.py --drug "sotorasib" --moa "Covalent KRAS G12C inhibitor" --top-n 5
```

## How it's organized

```
digital_pathology/
├── main.py           Run this — the command-line tool
├── config.py         Maps drug mechanisms to which slide patterns matter most
├── agents/            The 4 steps of the pipeline (lookup, search, rank, explain)
├── tools/             The pattern catalog + PubMed search + caching
├── models/            Data structures used throughout
├── llm/               AI model connections (Gemini / Ollama)
├── examples/          A real sample run you can look at
└── output/            Where your results get saved
```

For a full technical breakdown of how each step works, the scoring formulas, and the
reasoning behind design choices, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## License

Released under the [MIT License](LICENSE).
