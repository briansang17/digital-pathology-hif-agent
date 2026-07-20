"""
Digital Pathology HIF Agent — Pydantic v2 Schemas
All data models for H&E feature evidence, HIF hypotheses, and pipeline outputs.
Mirrors the structure of oncomoa_agent/models/schemas.py.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


# ─── Enumerations ─────────────────────────────────────────────────────────────

class ROIType(str, Enum):
    """
    Tissue Region of Interest (ROI) in which a feature is measured on H&E.
    Defines which region a pathologist needs to annotate before quantification.
    """
    STROMA = "stroma"
    """Fibrous connective tissue surrounding tumor nests — for stromal TIL score."""
    TUMOR_NEST = "tumor_nest"
    """Tumor cell nests / parenchyma — for intratumoral TIL density and tumor density."""
    INVASIVE_MARGIN = "invasive_margin"
    """Leading edge where tumor meets stroma (~500 µm band) — for margin TIL density."""
    PERITUMORAL = "peritumoral"
    """Tissue immediately surrounding the tumor bulk (~2 mm zone) — for peritumoral immune infiltrate."""
    TLS = "tls"
    """Tertiary Lymphoid Structures — organized lymphoid follicles within or adjacent to the tumor."""
    INTRAEPITHELIAL = "intraepithelial"
    """Within the epithelial layer — for intraepithelial lymphocyte counts (CRC, gastric)."""
    VASCULAR = "vascular"
    """Perivascular regions — for perivascular lymphocytic cuffing."""
    WHOLE_SECTION = "whole_section"
    """No specific ROI annotation required — whole-slide or composite metrics."""


class FeatureCategory(str, Enum):
    """H&E Human-Interpretable Feature category."""
    CELL_DENSITY = "cell_density"
    TIL_SCORE = "til_score"
    IMMUNE_PHENOTYPE = "immune_phenotype"
    SPATIAL_DISTANCE = "spatial_distance"
    SPATIAL_CLUSTERING = "spatial_clustering"
    COLOCALIZATION = "colocalization"
    NEIGHBORHOOD_COMPOSITION = "neighborhood_composition"
    COMPOSITE = "composite"


class FeatureType(str, Enum):
    """Whether the HIF is predictive, prognostic, or both."""
    PREDICTIVE = "predictive"
    PROGNOSTIC = "prognostic"
    BOTH = "both"
    UNKNOWN = "unknown"


class EvidenceDirection(str, Enum):
    SUPPORTS = "Supports"
    DOES_NOT_SUPPORT = "Does Not Support"
    UNKNOWN = "Unknown"


# ─── Normalized Pathology Feature (unified across all sources) ────────────────
# Mirrors NormalizedEvidence in oncomoa_agent

class NormalizedPathologyFeature(BaseModel):
    """
    Unified H&E feature record from any source (catalog or PubMed).
    Analogous to NormalizedEvidence in oncomoa_agent.
    """
    source: str = Field(..., description="Source: HECatalog or PubMed")
    source_id: str = Field(..., description="Unique record ID within the source")
    feature_name: str = Field(..., description="Human-readable HIF name")
    feature_category: FeatureCategory = Field(FeatureCategory.CELL_DENSITY)
    roi: ROIType = Field(ROIType.WHOLE_SECTION, description="ROI type to annotate for this feature")
    roi_annotation_guide: str = Field(
        "", description="How to annotate the ROI on the H&E slide (e.g., 'Draw polygons around all stromal areas within the tumor boundary')"
    )
    measurement_method: str = Field("", description="How to measure this feature within the annotated ROI")
    measurement_unit: str = Field("", description="Unit (e.g., %, cells/mm², µm)")
    tumor_type: Optional[str] = Field(None, description="Cancer type this evidence applies to")
    drug: Optional[str] = Field(None)
    moa_class: Optional[str] = Field(None, description="MOA class this feature is relevant for")
    evidence_type: FeatureType = Field(FeatureType.UNKNOWN)
    evidence_direction: EvidenceDirection = Field(EvidenceDirection.UNKNOWN)
    evidence_level: Optional[str] = Field(None, description="A/B/C/D — clinical to pre-clinical")
    claim: str = Field("", description="Human-readable evidence claim")
    strength: float = Field(0.0, description="Numeric strength score (from weights)")
    raw_data: dict[str, Any] = Field(default_factory=dict)


# ─── Supporting Evidence Item ─────────────────────────────────────────────────

class SupportingEvidence(BaseModel):
    """A single piece of supporting evidence for a HIF hypothesis."""
    source: str
    id: str
    claim: str


# ─── Ranking Rationale ────────────────────────────────────────────────────────

class HIFRankingRationale(BaseModel):
    """Explains how a HIF's score was computed. Mirrors RankingRationale."""
    in_he_catalog: bool = False
    evidence_level: Optional[str] = None
    pubmed_hits: int = 0
    analogical_hits: int = 0   # PMIDs from MOA-class analogical search
    moa_weight_applied: float = 0.0
    moa_class: str = ""
    raw_score: float = 0.0


# ─── HIF Hypothesis (primary output object) ───────────────────────────────────
# Mirrors BiomarkerHypothesis in oncomoa_agent

class HIFHypothesis(BaseModel):
    """
    A ranked H&E Human-Interpretable Feature hypothesis with evidence.
    Analogous to BiomarkerHypothesis in oncomoa_agent.
    """
    rank: int
    feature_name: str
    feature_category: FeatureCategory = FeatureCategory.CELL_DENSITY
    feature_type: FeatureType = FeatureType.UNKNOWN
    roi: ROIType = Field(ROIType.WHOLE_SECTION, description="ROI to annotate on the H&E slide")
    roi_annotation_guide: str = Field("", description="Step-by-step instruction for ROI annotation")
    measurement_method: str = ""
    measurement_unit: str = ""
    confidence_score: float = Field(0.0, ge=0.0, le=100.0)
    predictive_score: float = Field(0.0, ge=0.0, le=100.0)
    prognostic_score: float = Field(0.0, ge=0.0, le=100.0)
    evidence_level: Optional[str] = None
    evidence_basis: str = Field(
        "direct",
        description="'direct' = drug-specific evidence, 'analogical' = MOA-class only, 'mixed' = both",
    )
    drug_relevance: str = ""
    supporting_sources: list[str] = Field(default_factory=list)
    supporting_evidence: list[SupportingEvidence] = Field(default_factory=list)
    ranking_rationale: HIFRankingRationale = Field(default_factory=HIFRankingRationale)
    hypothesis: str = Field("", description="LLM-generated narrative interpretation")

    @field_validator("confidence_score", "predictive_score", "prognostic_score", mode="before")
    @classmethod
    def clamp_score(cls, v: Any) -> float:
        """Clamp scores to [0, 100]."""
        return max(0.0, min(100.0, float(v)))


# ─── Internal Scoring Container ───────────────────────────────────────────────
# Mirrors CandidateBiomarker in oncomoa_agent

class CandidateHIF(BaseModel):
    """
    Internal scoring accumulator for an H&E HIF before final ranking.
    Analogous to CandidateBiomarker in oncomoa_agent.
    """
    feature_id: str
    feature_name: str
    feature_category: FeatureCategory
    roi: ROIType = ROIType.WHOLE_SECTION
    roi_annotation_guide: str = ""
    measurement_method: str = ""
    measurement_unit: str = ""

    # Raw score accumulators
    catalog_score: float = 0.0      # From HE catalog evidence level
    pubmed_score: float = 0.0       # From PubMed hits
    moa_score: float = 0.0          # From MOA category weight match

    # Independent predictive vs prognostic scores
    predictive_raw: float = 0.0
    prognostic_raw: float = 0.0

    # Evidence references
    evidence_items: list[NormalizedPathologyFeature] = Field(default_factory=list)
    pubmed_ids: list[str] = Field(default_factory=list)
    catalog_ids: list[str] = Field(default_factory=list)

    # Rationale flags
    in_he_catalog: bool = False
    best_evidence_level: Optional[str] = None
    moa_class: str = ""

    @property
    def total_raw_score(self) -> float:
        return self.catalog_score + self.pubmed_score + self.moa_score

    @property
    def has_minimum_evidence(self) -> bool:
        """Must have at least 1 catalog source."""
        return self.in_he_catalog or len(self.pubmed_ids) >= 1


# ─── Top-Level Agent Output ───────────────────────────────────────────────────
# Mirrors AgentOutput in oncomoa_agent

class PathologyOutput(BaseModel):
    """Top-level output for the digital pathology HIF pipeline."""
    drug_name: str
    moa_description: str
    tumor_type: str
    moa_class: str = ""
    llm_backend_used: str = ""
    hypotheses: list[HIFHypothesis] = Field(default_factory=list)
    failed_sources: list[str] = Field(default_factory=list)
    successful_sources: list[str] = Field(default_factory=list)
    total_features_evaluated: int = 0
    run_metadata: dict[str, Any] = Field(default_factory=dict)
