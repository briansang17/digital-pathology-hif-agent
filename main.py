"""
Digital Pathology HIF Agent — Main CLI Entrypoint

Recommends ranked H&E Human-Interpretable Features (HIFs) that are prognostic
or predictive for a given drug MOA. Tumor-type agnostic — works for any solid
tumor indication. Outputs:
  - Rich table display in terminal
  - output/results.json
  - output/features_summary.csv
  - logs/digpath.log

Example:
    python main.py --drug "pembrolizumab" --moa "PD-1 checkpoint inhibitor"
    python main.py --drug "olaparib" --moa "PARP1/2 inhibitor" --top-n 8
    python main.py --drug "novel-drug-x" --moa "TIGIT checkpoint inhibitor" --backend gemini
    python main.py --drug "sotorasib" --moa "Covalent KRAS G12C inhibitor" --no-llm
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich import print as rprint

from config import (
    LOG_FILE,
    LOG_LEVEL,
    OUTPUT_RESULTS_JSON,
    OUTPUT_FEATURES_CSV,
    DEFAULT_TOP_N,
    get_moa_class,
)
from models.schemas import PathologyOutput, HIFHypothesis

console = Console()


def setup_logging() -> None:
    """Configure structured logging to both file and Rich console."""
    log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    LOG_FILE.parent.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    rich_handler = RichHandler(
        console=console,
        rich_tracebacks=True,
        show_path=False,
        markup=True,
    )
    rich_handler.setLevel(log_level)

    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[file_handler, rich_handler],
        force=True,
    )


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="digpath",
        description=(
            "Digital Pathology HIF Agent — "
            "H&E Human-Interpretable Feature recommendation for drug MOA. "
            "Tumor-type agnostic: works for any solid tumor indication."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --drug "pembrolizumab" --moa "PD-1 checkpoint inhibitor"
  python main.py --drug "olaparib" --moa "PARP1/2 inhibitor" --top-n 8
  python main.py --drug "novel-tigit" --moa "TIGIT checkpoint inhibitor" --backend gemini
  python main.py --drug "sotorasib" --moa "Covalent KRAS G12C inhibitor" --no-llm
        """,
    )
    parser.add_argument(
        "--drug", "-d", required=True, help="Drug name (e.g., 'pembrolizumab')"
    )
    parser.add_argument(
        "--moa", "-m", required=True, help="Mechanism of action description"
    )
    parser.add_argument(
        "--top-n", "-n", type=int, default=DEFAULT_TOP_N,
        help=f"Number of HIF hypotheses to return (default: {DEFAULT_TOP_N})"
    )
    parser.add_argument(
        "--backend", "-b",
        choices=["auto", "gemini", "ollama", "meditron"],
        default="auto",
        help="LLM backend override (default: auto — uses drug-class routing)",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Custom output directory (default: ./output/)"
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Skip LLM synthesis step, return deterministic ranking only"
    )
    return parser.parse_args()


def display_results_table(output: PathologyOutput) -> None:
    """Render HIF hypotheses as a Rich table in the terminal."""
    console.print()
    console.print(Panel(
        f"[bold green]Digital Pathology HIF Agent Results[/bold green]\n"
        f"Drug: [cyan]{output.drug_name}[/cyan] | "
        f"Scope: [yellow]Pan-cancer[/yellow] | "
        f"MOA class: [magenta]{output.moa_class}[/magenta] | "
        f"Evidence items: [blue]{output.total_features_evaluated}[/blue] | "
        f"LLM: [dim]{output.llm_backend_used}[/dim]",
        expand=False,
    ))

    if not output.hypotheses:
        console.print("[red]No H&E HIF hypotheses generated.[/red]")
        return

    table = Table(
        show_header=True,
        header_style="bold white on dark_blue",
        border_style="blue",
        title=f"[bold]Top {len(output.hypotheses)} H&E Human-Interpretable Features[/bold]",
        title_style="bold cyan",
    )

    table.add_column("#", style="bold white", width=3)
    table.add_column("Feature", style="bold yellow", width=30)
    table.add_column("ROI", style="magenta", width=16)
    table.add_column("Category", style="green", width=18)
    table.add_column("Type", style="cyan", width=11)
    table.add_column("Conf.", style="bold", width=6)
    table.add_column("Level", style="red", width=6)
    table.add_column("Basis", style="dim", width=10)

    for hyp in output.hypotheses:
        conf = hyp.confidence_score
        if conf >= 70:
            conf_str = f"[bold green]{conf:.0f}[/bold green]"
        elif conf >= 40:
            conf_str = f"[yellow]{conf:.0f}[/yellow]"
        else:
            conf_str = f"[red]{conf:.0f}[/red]"

        level_str = f"[bold red]{hyp.evidence_level}[/bold red]" if hyp.evidence_level else "-"
        basis = getattr(hyp, "evidence_basis", "direct") or "direct"
        basis_str = f"[dim italic]{basis}[/dim italic]"

        roi_str = hyp.roi.value if hyp.roi else "-"

        table.add_row(
            str(hyp.rank),
            hyp.feature_name,
            roi_str,
            hyp.feature_category.value,
            hyp.feature_type.value,
            conf_str,
            level_str,
            basis_str,
        )

    console.print(table)

    # Detailed narrative for top 5
    console.print()
    console.print("[bold cyan]Feature Measurement Methods & Rationale:[/bold cyan]")
    for hyp in output.hypotheses[:5]:
        basis = getattr(hyp, "evidence_basis", "direct") or "direct"
        basis_tag = "[dim italic](analogical)[/dim italic]" if basis == "analogical" else ""
        console.print(
            f"\n[bold yellow]#{hyp.rank} {hyp.feature_name}[/bold yellow] "
            f"[dim]({hyp.feature_type.value})[/dim] {basis_tag}"
        )
        if hyp.roi:
            console.print(f"  [dim]ROI:[/dim] {hyp.roi.value}")
            if hyp.roi_annotation_guide:
                console.print(f"  [dim]Annotation:[/dim] {hyp.roi_annotation_guide}")
        if hyp.measurement_method:
            console.print(f"  [dim]Measure:[/dim] {hyp.measurement_method}")
        if hyp.hypothesis:
            console.print(f"  [dim]Rationale:[/dim] {hyp.hypothesis}")

    # Sources report
    console.print()
    if output.successful_sources:
        console.print(f"[green]Sources:[/green] {', '.join(set(output.successful_sources))}")
    if output.failed_sources:
        console.print(f"[red]Failed:[/red] {', '.join(set(output.failed_sources))}")

    elapsed = output.run_metadata.get("elapsed_seconds", 0)
    console.print(f"\n[dim]Completed in {elapsed:.1f}s | Log: logs/digpath.log[/dim]")


def save_outputs(output: PathologyOutput, output_dir: Path | None = None) -> None:
    """Save all output files: results JSON and features CSV."""
    from config import OUTPUT_DIR

    out_dir = output_dir or OUTPUT_DIR
    out_dir.mkdir(exist_ok=True)

    # results.json
    results_path = out_dir / "results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(output.model_dump(), f, indent=2, default=str)
    console.print(f"[green]Saved:[/green] {results_path}")

    # features_summary.csv
    if output.hypotheses:
        try:
            csv_path = out_dir / "features_summary.csv"
            rows = []
            for hyp in output.hypotheses:
                rows.append({
                    "rank": hyp.rank,
                    "feature_name": hyp.feature_name,
                    "roi": hyp.roi.value if hyp.roi else "",
                    "roi_annotation_guide": hyp.roi_annotation_guide or "",
                    "feature_category": hyp.feature_category.value,
                    "feature_type": hyp.feature_type.value,
                    "measurement_method": hyp.measurement_method,
                    "measurement_unit": hyp.measurement_unit,
                    "confidence_score": round(hyp.confidence_score, 2),
                    "predictive_score": round(hyp.predictive_score, 2),
                    "prognostic_score": round(hyp.prognostic_score, 2),
                    "evidence_level": hyp.evidence_level or "",
                    "evidence_basis": getattr(hyp, "evidence_basis", "direct") or "direct",
                    "drug_relevance": hyp.drug_relevance,
                    "pubmed_hits": hyp.ranking_rationale.pubmed_hits,
                    "moa_class": hyp.ranking_rationale.moa_class,
                    "supporting_sources": "|".join(hyp.supporting_sources[:5]),
                    "hypothesis": hyp.hypothesis[:300] if hyp.hypothesis else "",
                })
            df = pd.DataFrame(rows)
            df.to_csv(csv_path, index=False)
            console.print(f"[green]Saved:[/green] {csv_path}")
        except Exception as exc:
            logging.getLogger(__name__).error("CSV save failed: %s", exc)


async def main() -> None:
    """Main async entrypoint."""
    setup_logging()
    args = parse_args()

    moa_class = get_moa_class(args.drug, args.moa)

    console.print(Panel(
        "[bold cyan]Digital Pathology HIF Agent[/bold cyan]\n"
        "[dim]H&E Human-Interpretable Feature Recommendation · Pan-Cancer[/dim]",
        expand=False,
    ))
    console.print(f"[bold]Drug:[/bold] [yellow]{args.drug}[/yellow]")
    console.print(f"[bold]MOA:[/bold] {args.moa}")
    console.print(f"[bold]Scope:[/bold] [magenta]Pan-cancer (all solid tumors)[/magenta]")
    console.print(f"[bold]MOA Class:[/bold] [cyan]{moa_class}[/cyan]")
    console.print(f"[bold]Top N:[/bold] {args.top_n}")
    console.print(f"[bold]Backend:[/bold] {args.backend}")
    console.print(f"[bold]Analogical search:[/bold] [green]enabled[/green]")
    console.print()

    backend_override = args.backend
    if args.no_llm:
        backend_override = "none"
        console.print("[yellow]--no-llm: skipping LLM synthesis[/yellow]")

    from agents.orchestrator import PathologyOrchestrator

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        orchestrator = PathologyOrchestrator(backend_override=backend_override)
        output = await orchestrator.run(
            drug_name=args.drug,
            moa_description=args.moa,
            top_n=args.top_n,
            progress=progress,
        )

    display_results_table(output)
    save_outputs(output, output_dir=args.output)


if __name__ == "__main__":
    asyncio.run(main())
