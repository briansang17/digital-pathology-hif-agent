# Digital Pathology HIF Agent

**In plain terms:** you tell it a cancer drug's name and how it works, and it tells you what to look for under the microscope on a regular biopsy slide to predict whether that drug will help the patient.

---

## Table of contents

- [The idea](#the-idea)
- [Some background](#some-background)
- [Quickstart](#quickstart)
- [See it in action](#see-it-in-action)
- [What you get back](#what-you-get-back)
- [More examples](#more-examples)
- [How it's organized](#how-its-organized)
- [Frequently asked questions](#frequently-asked-questions)
- [License](#license)

---

## The idea

Every tumor biopsy gets stained with a simple, cheap dye combo called **H&E** (it colors cell nuclei purple and everything else pink). Pathologists have found that certain visible patterns on that slide — like how many immune cells surround a tumor, or how dense the tumor cells are — can hint at whether a drug will work.

Figuring out *which* patterns matter for a *specific* drug normally means a scientist reading dozens of research papers. This tool automates that process in a few seconds:

1. **Look up known patterns** — it checks a curated list of ~30 known slide patterns (called **HIFs**, or Human-Interpretable Features) and how strong the clinical evidence is for each one.
2. **Search fresh literature** — it searches PubMed for papers connecting that specific drug to those patterns, in case there's newer evidence than what's in the built-in list.
3. **Score and rank** — every pattern gets a score using clear, math-based rules. No AI guessing here — this step is 100% reproducible, meaning you'll get the exact same ranking every time you run it.
4. **Explain (optional)** — an AI model (Google Gemini, or a local Ollama model if you'd rather not use a cloud API) writes a short, plain-English explanation for the top results. The AI is only allowed to use the evidence gathered in steps 1–3, so it can't invent facts or citations.

## Some background

**What is a "Human-Interpretable Feature" (HIF)?**
It's just a measurement a pathologist (or a computer program) can make by looking at a slide and reporting a number. A few examples:

- *Stromal TIL Score* — what percentage of the tissue around the tumor is filled with immune cells (lymphocytes)?
- *Tumor Cell Density* — how tightly packed are the cancer cells?
- *Immune Phenotype* — is the tumor "inflamed" (immune cells everywhere), "excluded" (immune cells stuck at the edges), or a "desert" (no immune cells at all)?

**Why start with H&E instead of fancier tests?**
Because literally every patient biopsy already gets an H&E slide — it's the cheapest, most routine test in pathology. If useful information can be pulled from a slide that's already being made anyway, it's available immediately, for every patient, at no extra cost.

**Why does the drug's "mechanism of action" (MOA) matter?**
Different drugs work in different ways, so different slide patterns matter more or less. A drug that boosts the immune system (like a checkpoint inhibitor) cares a lot about immune cell patterns. A drug that blocks tumor blood vessel growth cares more about vascular patterns. This tool takes what you tell it about how the drug works and uses that to weigh which patterns are most relevant.

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

**Requirements:** Python 3.10+. Everything else is optional:

- No AI backend? Add `--no-llm` and you'll still get the full ranked list — just without
  the plain-English explanations.
- Want AI explanations? Either get a free [Gemini API key](https://aistudio.google.com/apikey)
  and put it in `.env`, or run a local model with [Ollama](https://ollama.com/) — no API key
  or internet connection needed.

## See it in action

Don't want to install or run anything? [`examples/sample_run_belzutifan/`](examples/sample_run_belzutifan/)
has a real, complete run for the drug **belzutifan** — the exact command used, a plain-text
version of what prints to the terminal, and the full output files it produced. It's a good
way to see what the tool actually gives you before deciding whether to run it yourself.

## What you get back

Every run produces three things:

| Output | What it's for |
|---|---|
| Terminal table | Quick glance — ranked features, confidence score, evidence level (A–D) |
| `output/results.json` | The full detail — every feature's measurement method, exact region of the slide to look at, supporting evidence, and AI-written rationale |
| `output/features_summary.csv` | The same ranking in a spreadsheet-friendly format you can open in Excel or pull into other tools |

Each ranked feature tells you three practical things: **where** on the slide to look
(e.g., "the connective tissue around the tumor"), **how** to measure it (e.g., "count
immune cells per square millimeter"), and **why** it matters for this specific drug.

## More examples

```bash
# Skip the AI explanation, just get the ranked list (works with no API key at all)
python main.py --drug "olaparib" --moa "PARP1/2 inhibitor" --no-llm

# A brand-new/experimental drug still works — it falls back to general best-evidence patterns
python main.py --drug "my-drug-001" --moa "TIGIT immune checkpoint inhibitor"

# Only show the top 5 features instead of the default
python main.py --drug "sotorasib" --moa "Covalent KRAS G12C inhibitor" --top-n 5

# Force a specific AI backend instead of auto-selecting one
python main.py --drug "bevacizumab" --moa "Anti-VEGF antibody" --backend gemini
```

## How it's organized

```
digital_pathology/
├── main.py            Run this — the command-line tool
├── config.py          Maps drug mechanisms to which slide patterns matter most
├── requirements.txt   Python dependencies
├── .env.example       Template for your API keys / settings
│
├── agents/            The 4 steps of the pipeline (lookup, search, rank, explain)
├── tools/             The pattern catalog, PubMed search, and local caching
├── models/            Data structures used to pass information between steps
├── llm/               AI model connections (Gemini / Ollama)
│
├── examples/          A real sample run you can look at without installing anything
├── output/            Where your own results get saved (results.json, .csv)
└── docs/              Deeper technical documentation
```

For a full technical breakdown — how each pipeline step actually works internally, the
exact scoring formulas, and the reasoning behind specific design choices — see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Frequently asked questions

**Does this replace a pathologist?**
No. It's a research tool that suggests *what to measure* — the actual measuring and
clinical interpretation still needs a trained pathologist or a validated image-analysis
pipeline.

**Where does the evidence come from?**
Two places: a hand-curated catalog of known H&E findings with published support, and a
live PubMed search for that specific drug. The AI step only writes narrative text — it
never decides the ranking and never adds outside facts.

**What happens if I ask about a completely new/experimental drug?**
The tool falls back to a general, broadly-applicable set of well-evidenced patterns
rather than failing. It also still tries a PubMed search in case something relevant has
already been published.

**Do I need the internet?**
Only for PubMed searches and if you use the Gemini backend. Run with `--no-llm` and a
local catalog-only mode works fully offline; using Ollama also avoids sending anything
to the cloud.

## License

Released under the [MIT License](LICENSE).
