"""
MOA-to-HIF Evidence Prioritization Agent — Central Configuration
H&E Human-Interpretable Feature recommendation pipeline.
All parameters, scoring weights, MOA routing rules, and API URLs live here.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Project Paths ────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent
OUTPUT_DIR = ROOT_DIR / "output"
LOG_DIR = ROOT_DIR / "logs"
CACHE_DIR = Path(os.getenv("CACHE_DIR", str(ROOT_DIR / ".cache" / "digpath")))

OUTPUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_RESULTS_JSON = OUTPUT_DIR / "results.json"
OUTPUT_FEATURES_CSV = OUTPUT_DIR / "features_summary.csv"
LOG_FILE = LOG_DIR / "digpath.log"

# ─── Cache ────────────────────────────────────────────────────────────────────
CACHE_TTL: int = int(os.getenv("CACHE_TTL", 604800))  # 7 days

# ─── LLM Configuration ────────────────────────────────────────────────────────
LLM_BACKEND: str = os.getenv("LLM_BACKEND", "auto")  # auto | gemini | ollama | meditron
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = "gemini-2.5-flash"

OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_PRIMARY_MODEL: str = "meditron"
OLLAMA_FALLBACK_MODEL: str = "llama3.2"

# ─── Smart LLM Routing — MOA Class Rules ─────────────────────────────────────
# Immuno-oncology and ADC MOAs have complex TIL landscapes → route to Gemini

IO_MOA_KEYWORDS: list[str] = [
    "checkpoint", "pd-1", "pd-l1", "ctla-4", "lag-3", "tim-3",
    "bispecific", "car-t", "immunotherapy", "immune checkpoint",
]

ADC_SUFFIXES: list[str] = [
    "vedotin", "emtansine", "deruxtecan", "govitecan",
    "ozogamicin", "mafodotin", "tesirine", "ixtecan",
]


def requires_gemini(drug_name: str, moa: str = "") -> bool:
    """
    Return True if the drug/MOA class warrants Gemini backend routing.
    IO drugs and ADCs involve complex TIL/immune biology.
    """
    combined = f"{drug_name} {moa}".lower()
    if any(kw in combined for kw in IO_MOA_KEYWORDS):
        return True
    if any(drug_name.lower().endswith(suffix) for suffix in ADC_SUFFIXES):
        return True
    return False


# ─── MOA → H&E Feature Relevance Weights ─────────────────────────────────────
# Maps MOA keyword groups to feature category boost weights.
# Features whose categories match the drug's MOA get a higher relevance score.

MOA_FEATURE_WEIGHTS: dict[str, dict[str, float]] = {
    # Checkpoint / IO: TIL-centric immune features most relevant
    "checkpoint": {
        "til_score": 5.0,
        "immune_phenotype": 5.0,
        "spatial_distance": 4.0,
        "spatial_clustering": 4.0,
        "colocalization": 4.0,
        "cell_density": 3.0,
        "neighborhood_composition": 3.0,
        "composite": 3.0,
    },
    # DNA damage repair (PARP, platinum): immune + proliferation features
    "ddr": {
        "til_score": 4.0,
        "immune_phenotype": 3.0,
        "cell_density": 3.0,
        "spatial_distance": 2.5,
        "colocalization": 2.5,
        "spatial_clustering": 2.0,
        "neighborhood_composition": 2.0,
        "composite": 2.0,
    },
    # Targeted kinase (EGFR, ALK, ROS1, KRAS, HER2): general TME
    "kinase": {
        "cell_density": 4.0,
        "til_score": 3.0,
        "immune_phenotype": 2.5,
        "spatial_distance": 2.5,
        "colocalization": 2.0,
        "spatial_clustering": 2.0,
        "neighborhood_composition": 2.0,
        "composite": 2.5,
    },
    # Anti-angiogenic (VEGF, VEGFR): stromal and vascular features
    "antiangiogenic": {
        "cell_density": 4.0,
        "spatial_distance": 3.5,
        "colocalization": 3.0,
        "til_score": 2.5,
        "spatial_clustering": 2.5,
        "neighborhood_composition": 2.5,
        "immune_phenotype": 2.0,
        "composite": 3.0,
    },
    # Cell cycle (CDK4/6, WEE1): proliferation + immune infiltrate
    "cell_cycle": {
        "cell_density": 4.0,
        "til_score": 3.5,
        "immune_phenotype": 2.5,
        "spatial_distance": 2.0,
        "colocalization": 2.0,
        "spatial_clustering": 2.0,
        "neighborhood_composition": 2.0,
        "composite": 2.5,
    },
    # Bispecific (e.g., anti-PD-L1/VEGF): IO + angiogenic TME combined
    "bispecific": {
        "til_score": 5.0,
        "immune_phenotype": 5.0,
        "spatial_distance": 4.5,
        "spatial_clustering": 4.5,
        "colocalization": 4.0,
        "cell_density": 4.0,
        "neighborhood_composition": 3.5,
        "composite": 4.0,
    },
    # ADC (antibody-drug conjugate): target expression + proliferation + DNA damage
    "adc": {
        "cell_density": 5.0,
        "til_score": 4.0,
        "composite": 4.0,
        "immune_phenotype": 3.5,
        "spatial_distance": 3.0,
        "colocalization": 3.0,
        "spatial_clustering": 2.5,
        "neighborhood_composition": 2.5,
    },
    # Hypoxia / HIF pathway (HIF-2α inhibitors like belzutifan): vascular + stromal
    "hypoxia": {
        "cell_density": 4.5,
        "spatial_distance": 4.5,
        "colocalization": 4.0,
        "composite": 4.0,
        "til_score": 3.0,
        "immune_phenotype": 3.0,
        "spatial_clustering": 3.0,
        "neighborhood_composition": 3.5,
    },
    # Default: balanced weights
    "default": {
        "til_score": 3.0,
        "immune_phenotype": 3.0,
        "cell_density": 3.0,
        "spatial_distance": 2.0,
        "spatial_clustering": 2.0,
        "colocalization": 2.0,
        "neighborhood_composition": 2.0,
        "composite": 2.0,
    },
}

# Keywords for MOA class detection
MOA_CLASS_KEYWORDS: dict[str, list[str]] = {
    "checkpoint": [
        "checkpoint", "pd-1", "pd-l1", "ctla-4", "lag-3", "tim-3",
        "immunotherapy", "anti-pd", "anti-ctla",
    ],
    "ddr": [
        "parp", "dna repair", "hrd", "homologous recombination",
        "platinum", "atm", "brca",
    ],
    "kinase": [
        "egfr", "alk", "ros1", "kras", "braf", "mek", "erk",
        "her2", "met", "ret", "ntrk", "fgfr", "tyrosine kinase",
        "rtk", "mtor", "pi3k", "akt",
    ],
    "antiangiogenic": [
        "vegf", "vegfr", "angiogenesis", "anti-angiogenic",
        "bevacizumab", "ramucirumab",
    ],
    "cell_cycle": [
        "cdk4", "cdk6", "cdk", "wee1", "chk1", "aurora",
        "cell cycle", "cyclin", "rb pathway",
    ],
    # Bispecific antibodies targeting two pathways (e.g., PD-L1+VEGF, PD-1+LAG-3)
    "bispecific": [
        "bispecific", "bsab", "dual inhibit", "anti-pd-l1/vegf",
        "pd-l1/vegf", "pd-1/vegf", "pd-l1 vegf", "ivonescimab",
        "anti-vegf/pd", "dual blockade",
    ],
    # Antibody-drug conjugates
    "adc": [
        "antibody-drug conjugate", "adc", "maytansine", "auristatin",
        "deruxtecan", "govitecan", "calicheamicin", "pyrrolobenzodiazepine",
        "payload", "trastuzumab deruxtecan", "t-dxd",
    ],
    # Hypoxia / HIF pathway inhibitors (e.g., belzutifan, PT2977)
    "hypoxia": [
        "hif", "hif-2", "hif2", "hypoxia", "belzutifan", "welireg",
        "vhl", "epas1", "pt2977", "mki-0206", "hypoxia inducible",
    ],
}


def get_moa_class(drug_name: str, moa: str) -> str:
    """
    Classify the MOA into a feature-weight bucket.

    Args:
        drug_name: Drug name string.
        moa: Mechanism of action description.

    Returns:
        MOA class string matching a key in MOA_FEATURE_WEIGHTS.

    Example:
        cls = get_moa_class("pembrolizumab", "PD-1 checkpoint inhibitor")
        # "checkpoint"
    """
    combined = f"{drug_name} {moa}".lower()
    # Check specific classes before generic ones to avoid mis-classification
    priority_order = ["bispecific", "adc", "hypoxia", "ddr", "cell_cycle",
                      "antiangiogenic", "kinase", "checkpoint"]
    for cls in priority_order:
        keywords = MOA_CLASS_KEYWORDS.get(cls, [])
        if any(kw in combined for kw in keywords):
            return cls
    return "default"


def get_moa_weights(drug_name: str, moa: str) -> dict[str, float]:
    """
    Return the feature category weight dict for the given drug/MOA.

    Args:
        drug_name: Drug name.
        moa: Mechanism of action description.

    Returns:
        Dict mapping feature_category → relevance weight.
    """
    return MOA_FEATURE_WEIGHTS[get_moa_class(drug_name, moa)]


# ─── H&E Feature Categories ───────────────────────────────────────────────────
FEATURE_CATEGORIES: list[str] = [
    "cell_density",
    "til_score",
    "immune_phenotype",
    "spatial_distance",
    "spatial_clustering",
    "colocalization",
    "neighborhood_composition",
    "composite",
]

# ─── Evidence Level Weights ───────────────────────────────────────────────────
# A = multiple RCTs/meta-analyses, B = retrospective cohorts,
# C = exploratory/single cohort, D = pre-clinical / mechanistic
EVIDENCE_LEVEL_WEIGHTS: dict[str, float] = {
    "A": 5.0,
    "B": 4.0,
    "C": 3.0,
    "D": 1.5,
}

# ─── H&E Reliability Penalty ─────────────────────────────────────────────────
# Macrophage classification is unreliable on H&E alone (IHC required for CD68/CD163).
# Features tagged as macrophage-primary are penalized so they rank below lymphocyte
# and stromal features when scoring deterministically.
MACROPHAGE_SCORE_PENALTY: float = 0.25   # Multiplied into catalog_score for mac features

# Tumor-type specificity boost: features whose tumor_types list matches the input
# get this multiplier applied on top of the base score.
TUMOR_TYPE_MATCH_BOOST: float = 1.2

# ─── Scoring Parameters ───────────────────────────────────────────────────────
PUBMED_HIT_WEIGHT: float = 0.15
CATALOG_BASE_WEIGHT: float = 2.0    # Base score for every catalogued HIF
MOA_MATCH_WEIGHT: float = 1.0       # Multiplied by MOA category weight

# Thresholds for feature type classification
PREDICTIVE_THRESHOLD: float = 20.0
PROGNOSTIC_THRESHOLD: float = 20.0

# Top-N features to return (overridable via CLI)
DEFAULT_TOP_N: int = 10

# ─── PubMed Search Config ─────────────────────────────────────────────────────
PUBMED_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUBMED_MAX_RESULTS: int = 5
NCBI_API_KEY: str = os.getenv("NCBI_API_KEY", "")

# PubMed search terms for analogical (MOA-class-level) literature search.
# Used when drug-specific evidence is sparse — searches for the broader class
# so the LLM can reason from related mechanisms.
MOA_CLASS_SEARCH_TERMS: dict[str, str] = {
    "checkpoint": (
        "checkpoint inhibitor OR anti-PD-1 OR anti-PD-L1 OR "
        "immunotherapy OR immune checkpoint blockade"
    ),
    "ddr": (
        "PARP inhibitor OR DNA damage response OR homologous recombination "
        "deficiency OR platinum chemotherapy"
    ),
    "kinase": (
        "tyrosine kinase inhibitor OR targeted therapy OR EGFR inhibitor "
        "OR KRAS inhibitor OR ALK inhibitor"
    ),
    "antiangiogenic": (
        "anti-angiogenic therapy OR VEGF inhibitor OR bevacizumab "
        "OR VEGFR inhibitor OR angiogenesis"
    ),
    "cell_cycle": (
        "CDK4/6 inhibitor OR cell cycle inhibitor OR palbociclib "
        "OR ribociclib OR abemaciclib"
    ),
    "bispecific": (
        "bispecific antibody OR dual checkpoint OR anti-PD-L1 VEGF "
        "OR ivonescimab OR PD-1 VEGF immunotherapy"
    ),
    "adc": (
        "antibody-drug conjugate OR TROP2 ADC OR sacituzumab govitecan "
        "OR trastuzumab deruxtecan OR SN-38 topoisomerase cancer pathology"
    ),
    "hypoxia": (
        "HIF-2 inhibitor OR belzutifan OR hypoxia inducible factor "
        "OR VHL tumor microenvironment OR hypoxic cancer"
    ),
    "default": (
        "cancer drug therapy OR oncology targeted therapy OR "
        "solid tumor treatment"
    ),
}

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ─── HTTP Timeouts ────────────────────────────────────────────────────────────
HTTP_TIMEOUT: int = 15
HTTP_RETRIES: int = 3
HTTP_RETRY_WAIT: float = 1.0
