"""
MOA-to-HIF Evidence Prioritization Agent — H&E Feature Knowledge Base
Structured catalog of Human-Interpretable Features (HIFs) measurable on H&E slides.
Each entry describes a feature, its measurement method, evidence level, and the
MOA classes / tumor types for which it has prognostic or predictive evidence.

Returns NormalizedPathologyFeature records that feed into the ranking pipeline.

Example:
    features = get_he_features(tumor_type="NSCLC", moa_class="checkpoint")
    all_features = get_he_features()
"""

from __future__ import annotations

from typing import Optional

from models.schemas import (
    NormalizedPathologyFeature,
    FeatureCategory,
    FeatureType,
    EvidenceDirection,
    ROIType,
)

# ─── H&E HIF Catalog ─────────────────────────────────────────────────────────
# Each entry is a dict defining one H&E HIF.
# Fields:
#   feature_id        Unique identifier
#   feature_name      Human-readable display name
#   feature_category  FeatureCategory value
#   measurement_method  How to compute/score the feature
#   measurement_unit  Unit for reporting the value
#   evidence_type     predictive | prognostic | both
#   evidence_level    A = multiple RCTs, B = retrospective cohorts,
#                     C = exploratory/single cohort, D = pre-clinical
#   moa_classes       MOA buckets where this feature has known relevance
#   tumor_types       Cancer types with published evidence (empty = pan-tumor)
#   claim             One-sentence summary of the evidence
#   references        Key PubMed IDs supporting the claim

_HE_CATALOG: list[dict] = [

    # ── TIL Score ──────────────────────────────────────────────────────────────

    {
        "feature_id": "he_stromal_til",
        "feature_name": "Stromal TIL Score",
        "feature_category": FeatureCategory.TIL_SCORE,
        "measurement_method": (
            "Percent of stromal area occupied by mononuclear inflammatory cells "
            "(lymphocytes + plasma cells) per TIIC Working Group guidelines"
        ),
        "measurement_unit": "%",
        "evidence_type": FeatureType.BOTH,
        "evidence_level": "A",
        "moa_classes": ["checkpoint", "ddr", "kinase", "cell_cycle", "default"],
        "tumor_types": ["TNBC", "NSCLC", "BRCA", "GC", "BLCA", "MELA", "CRC", "HNSCC"],
        "claim": (
            "High stromal TIL score is an independent prognostic marker associated "
            "with improved OS in TNBC and NSCLC, and predicts response to checkpoint "
            "inhibitors and anthracycline-based chemotherapy."
        ),
        "references": ["24691917", "26453326", "31570881", "35764077"],
    },
    {
        "feature_id": "he_intratumoral_til",
        "feature_name": "Intratumoral TIL Density",
        "feature_category": FeatureCategory.TIL_SCORE,
        "measurement_method": (
            "Count of lymphocytes infiltrating tumor cell nests per unit area "
            "(cells/mm²) or as a percent of tumor nests with infiltrating lymphocytes"
        ),
        "measurement_unit": "cells/mm²",
        "evidence_type": FeatureType.BOTH,
        "evidence_level": "B",
        "moa_classes": ["checkpoint", "ddr", "kinase", "default"],
        "tumor_types": ["TNBC", "NSCLC", "CRC", "HNSCC", "MELA", "GC"],
        "claim": (
            "Intratumoral TIL density correlates with pathologic complete response "
            "to neoadjuvant therapy in TNBC and predicts benefit from checkpoint "
            "inhibition in multiple tumor types."
        ),
        "references": ["24691917", "28839416", "30423099"],
    },
    {
        "feature_id": "he_invasive_margin_til",
        "feature_name": "Invasive Margin TIL Density",
        "feature_category": FeatureCategory.TIL_SCORE,
        "measurement_method": (
            "Density of lymphocytes at the tumor-stroma interface "
            "(within 500 µm of the leading edge), reported as cells/mm²"
        ),
        "measurement_unit": "cells/mm²",
        "evidence_type": FeatureType.BOTH,
        "evidence_level": "B",
        "moa_classes": ["checkpoint", "ddr", "default"],
        "tumor_types": ["CRC", "NSCLC", "MELA", "TNBC", "BLCA"],
        "claim": (
            "High TIL density at the invasive margin is a component of the Immunoscore "
            "and associated with improved survival and checkpoint inhibitor benefit in CRC."
        ),
        "references": ["18566460", "26192220", "32649915"],
    },

    # ── Immune Phenotype ───────────────────────────────────────────────────────

    {
        "feature_id": "he_immune_phenotype",
        "feature_name": "Immune Phenotype Classification",
        "feature_category": FeatureCategory.IMMUNE_PHENOTYPE,
        "measurement_method": (
            "Classify the TME into: Inflamed (TILs throughout tumor parenchyma), "
            "Excluded (TILs at margin/stroma only), or Desert (absent TILs). "
            "Based on intratumoral vs stromal TIL distribution."
        ),
        "measurement_unit": "class (inflamed/excluded/desert)",
        "evidence_type": FeatureType.PREDICTIVE,
        "evidence_level": "B",
        "moa_classes": ["checkpoint", "default"],
        "tumor_types": ["NSCLC", "MELA", "BLCA", "HNSCC", "TNBC", "CRC"],
        "claim": (
            "Inflamed phenotype predicts response to PD-1/PD-L1 checkpoint inhibitors; "
            "excluded phenotype identifies patients who may benefit from stromal targeting "
            "combinations; desert phenotype has poor IO response across tumor types."
        ),
        "references": ["29443960", "31406350", "35013590"],
    },
    {
        "feature_id": "he_immunoscore",
        "feature_name": "Immunoscore",
        "feature_category": FeatureCategory.IMMUNE_PHENOTYPE,
        "measurement_method": (
            "Quantify CD3+ and CD8+ cell densities (or lymphocytes as proxy on H&E) "
            "at two tumor regions: tumor core and invasive margin. "
            "Classify as Immunoscore 0–4 based on density percentiles."
        ),
        "measurement_unit": "score 0–4",
        "evidence_type": FeatureType.PROGNOSTIC,
        "evidence_level": "A",
        "moa_classes": ["checkpoint", "ddr", "kinase", "default"],
        "tumor_types": ["CRC", "NSCLC", "HNSCC", "GC", "BLCA", "MELA"],
        "claim": (
            "Immunoscore is a validated pan-cancer prognostic biomarker; "
            "high Immunoscore (3–4) is associated with improved OS independent of "
            "TNM stage and predicts response to adjuvant immunotherapy in Stage III CRC."
        ),
        "references": ["26192220", "29667924", "32649915"],
    },

    # ── Cell Density ───────────────────────────────────────────────────────────

    {
        "feature_id": "he_tumor_cell_density",
        "feature_name": "Tumor Cell Density",
        "feature_category": FeatureCategory.CELL_DENSITY,
        "measurement_method": (
            "Count of tumor cells per unit area (cells/mm²) "
            "within the annotated tumor region"
        ),
        "measurement_unit": "cells/mm²",
        "evidence_type": FeatureType.PROGNOSTIC,
        "evidence_level": "B",
        "moa_classes": ["kinase", "cell_cycle", "ddr", "default"],
        "tumor_types": ["NSCLC", "BRCA", "CRC", "PDAC", "GC"],
        "claim": (
            "High tumor cell density is associated with aggressive tumor biology and "
            "poor prognosis; useful as a denominator for immune infiltrate ratios "
            "and to normalize TIL density measurements."
        ),
        "references": ["31409606", "30886133"],
    },
    {
        "feature_id": "he_stromal_ratio",
        "feature_name": "Stromal Ratio",
        "feature_category": FeatureCategory.CELL_DENSITY,
        "measurement_method": (
            "Fraction of the tumor region occupied by stromal tissue "
            "(stroma + endothelial cells) versus tumor cells, "
            "expressed as a percentage"
        ),
        "measurement_unit": "%",
        "evidence_type": FeatureType.PROGNOSTIC,
        "evidence_level": "B",
        "moa_classes": ["antiangiogenic", "kinase", "default"],
        "tumor_types": ["CRC", "BRCA", "NSCLC", "PDAC", "GC"],
        "claim": (
            "High tumor-associated stroma ratio (>50%) is an independent poor "
            "prognostic factor across multiple solid tumors and associated with "
            "EMT and reduced immune infiltration."
        ),
        "references": ["22438968", "25605569", "27462101"],
    },
    {
        "feature_id": "he_macrophage_density",
        "feature_name": "Tumor-Associated Macrophage Density",
        "feature_category": FeatureCategory.CELL_DENSITY,
        "measurement_method": (
            "Count of macrophage-like cells (large round nuclei with pale cytoplasm) "
            "per mm² in intratumoral and peritumoral compartments separately"
        ),
        "measurement_unit": "cells/mm²",
        "evidence_type": FeatureType.BOTH,
        "evidence_level": "B",
        "moa_classes": ["checkpoint", "antiangiogenic", "default"],
        "tumor_types": ["TNBC", "NSCLC", "CRC", "OV", "GC", "HNSCC"],
        "claim": (
            "High TAM density is associated with poor prognosis in most solid tumors "
            "due to M2 polarization promoting immunosuppression; "
            "intratumoral TAM-to-lymphocyte ratio predicts checkpoint inhibitor resistance."
        ),
        "references": ["22028697", "28841418", "31563810"],
    },
    {
        "feature_id": "he_plasma_cell_density",
        "feature_name": "Plasma Cell Density",
        "feature_category": FeatureCategory.CELL_DENSITY,
        "measurement_method": (
            "Count of plasma cells (clock-face chromatin, eccentric nucleus) "
            "per mm² in stromal and peritumoral regions"
        ),
        "measurement_unit": "cells/mm²",
        "evidence_type": FeatureType.PROGNOSTIC,
        "evidence_level": "C",
        "moa_classes": ["checkpoint", "default"],
        "tumor_types": ["NSCLC", "TNBC", "CRC", "MELA"],
        "claim": (
            "Plasma cell density within the tumor microenvironment is an independent "
            "prognostic factor in NSCLC and TNBC, reflecting tertiary lymphoid "
            "structures associated with improved survival."
        ),
        "references": ["24981606", "28416812", "34285125"],
    },

    # ── Spatial Distance ───────────────────────────────────────────────────────

    {
        "feature_id": "he_lymph_tumor_nnd",
        "feature_name": "Lymphocyte-to-Tumor Nearest Neighbor Distance",
        "feature_category": FeatureCategory.SPATIAL_DISTANCE,
        "measurement_method": (
            "Median distance (µm) from each lymphocyte centroid to the nearest "
            "tumor cell centroid, computed via k-d tree nearest neighbor search"
        ),
        "measurement_unit": "µm",
        "evidence_type": FeatureType.PREDICTIVE,
        "evidence_level": "C",
        "moa_classes": ["checkpoint", "default"],
        "tumor_types": ["TNBC", "NSCLC", "MELA", "CRC"],
        "claim": (
            "Short median lymphocyte-to-tumor distance (high proximity) reflects "
            "physical immune engagement and is associated with pathologic response "
            "to neoadjuvant immunotherapy."
        ),
        "references": ["30423099", "33268085", "36029206"],
    },
    {
        "feature_id": "he_macrophage_distribution",
        "feature_name": "Macrophage Spatial Distribution Ratio",
        "feature_category": FeatureCategory.SPATIAL_DISTANCE,
        "measurement_method": (
            "Ratio of peritumoral to intratumoral macrophage density; "
            "peritumoral region defined as 200 µm band around the tumor boundary"
        ),
        "measurement_unit": "ratio (peri/intra)",
        "evidence_type": FeatureType.PROGNOSTIC,
        "evidence_level": "C",
        "moa_classes": ["checkpoint", "antiangiogenic", "default"],
        "tumor_types": ["NSCLC", "TNBC", "CRC", "GC"],
        "claim": (
            "Peritumoral macrophage predominance (high ratio) indicates an excluded "
            "immune phenotype; intratumoral macrophage predominance is associated with "
            "inflammatory TME and better checkpoint response."
        ),
        "references": ["28841418", "31563810"],
    },

    # ── Spatial Clustering ─────────────────────────────────────────────────────

    {
        "feature_id": "he_lymph_clustering",
        "feature_name": "Lymphocyte Spatial Clustering Index",
        "feature_category": FeatureCategory.SPATIAL_CLUSTERING,
        "measurement_method": (
            "Ripley's L statistic evaluated at r=50 µm for the lymphocyte population; "
            "positive L(r)−r values indicate spatial clustering above random expectation"
        ),
        "measurement_unit": "Ripley L(50µm) − r",
        "evidence_type": FeatureType.PREDICTIVE,
        "evidence_level": "C",
        "moa_classes": ["checkpoint", "default"],
        "tumor_types": ["TNBC", "NSCLC", "MELA", "CRC"],
        "claim": (
            "High lymphocyte clustering (aggregated TILs) at the invasive margin "
            "correlates with tertiary lymphoid structure formation and predicts "
            "improved response to checkpoint inhibitors."
        ),
        "references": ["33268085", "34285125", "36029206"],
    },
    {
        "feature_id": "he_tls_hotspot",
        "feature_name": "TIL Hotspot Density",
        "feature_category": FeatureCategory.SPATIAL_CLUSTERING,
        "measurement_method": (
            "Maximum TIL density in a 500×500 µm sliding window across the tumor, "
            "identifying hotspot regions of immune aggregation"
        ),
        "measurement_unit": "cells/mm² (hotspot)",
        "evidence_type": FeatureType.BOTH,
        "evidence_level": "B",
        "moa_classes": ["checkpoint", "ddr", "default"],
        "tumor_types": ["TNBC", "NSCLC", "MELA", "CRC", "HNSCC", "GC"],
        "claim": (
            "TIL hotspot density (best tumor area) outperforms mean TIL score "
            "for predicting pCR to neoadjuvant chemotherapy in TNBC and "
            "benefit from checkpoint inhibition in NSCLC."
        ),
        "references": ["28839416", "30423099", "31570881"],
    },
    {
        "feature_id": "he_til_heterogeneity",
        "feature_name": "TIL Spatial Heterogeneity",
        "feature_category": FeatureCategory.SPATIAL_CLUSTERING,
        "measurement_method": (
            "Coefficient of variation (CV) of TIL density across 500×500 µm tiles "
            "covering the tumor region; high CV indicates heterogeneous distribution"
        ),
        "measurement_unit": "CV (dimensionless)",
        "evidence_type": FeatureType.PROGNOSTIC,
        "evidence_level": "C",
        "moa_classes": ["checkpoint", "default"],
        "tumor_types": ["TNBC", "NSCLC", "CRC"],
        "claim": (
            "High TIL spatial heterogeneity is associated with sampling bias risk "
            "and resistance mechanisms; homogeneous high TIL density confers better "
            "prognosis than heterogeneous infiltration of equivalent mean density."
        ),
        "references": ["33268085", "36029206"],
    },
    {
        "feature_id": "he_morans_i",
        "feature_name": "Tumor Cell Spatial Autocorrelation (Moran's I)",
        "feature_category": FeatureCategory.SPATIAL_CLUSTERING,
        "measurement_method": (
            "Moran's I statistic computed on tumor cell density across a spatial grid "
            "(50 µm bins); high positive I indicates clustered growth patterns"
        ),
        "measurement_unit": "Moran's I (−1 to +1)",
        "evidence_type": FeatureType.PROGNOSTIC,
        "evidence_level": "D",
        "moa_classes": ["kinase", "cell_cycle", "default"],
        "tumor_types": ["NSCLC", "BRCA", "CRC"],
        "claim": (
            "High spatial autocorrelation of tumor cells (clustered growth) is "
            "associated with expansive tumor growth patterns and better prognosis "
            "versus diffuse/infiltrative patterns."
        ),
        "references": ["29867930", "33268085"],
    },

    # ── Colocalization ─────────────────────────────────────────────────────────

    {
        "feature_id": "he_lymph_tumor_coloc",
        "feature_name": "Lymphocyte-Tumor Cross-K Colocalization",
        "feature_category": FeatureCategory.COLOCALIZATION,
        "measurement_method": (
            "Bivariate Ripley's cross-K function K12(r) between lymphocytes (type 1) "
            "and tumor cells (type 2) at r=50 µm; values above the CSR envelope "
            "indicate attraction between the populations"
        ),
        "measurement_unit": "cross-K(50µm) excess over CSR",
        "evidence_type": FeatureType.PREDICTIVE,
        "evidence_level": "C",
        "moa_classes": ["checkpoint", "default"],
        "tumor_types": ["TNBC", "NSCLC", "MELA"],
        "claim": (
            "Positive lymphocyte-tumor colocalization (attraction) reflects active "
            "immune engagement and predicts pathologic response to neoadjuvant "
            "immunotherapy in TNBC."
        ),
        "references": ["33268085", "36029206"],
    },
    {
        "feature_id": "he_macrophage_lymph_coloc",
        "feature_name": "Macrophage-Lymphocyte Interaction Score",
        "feature_category": FeatureCategory.COLOCALIZATION,
        "measurement_method": (
            "Fraction of lymphocytes within 30 µm of a macrophage; "
            "high scores indicate immunosuppressive macrophage-lymphocyte contacts"
        ),
        "measurement_unit": "fraction (0–1)",
        "evidence_type": FeatureType.PREDICTIVE,
        "evidence_level": "C",
        "moa_classes": ["checkpoint", "antiangiogenic", "default"],
        "tumor_types": ["TNBC", "NSCLC", "GC"],
        "claim": (
            "High macrophage-lymphocyte proximity is associated with "
            "immunosuppressive TME phenotype and predicts reduced response to "
            "anti-PD-1 therapy through TAM-mediated T cell exclusion."
        ),
        "references": ["28841418", "35764077"],
    },

    # ── Neighborhood Composition ───────────────────────────────────────────────

    {
        "feature_id": "he_tumor_neighborhood_diversity",
        "feature_name": "Cell Neighborhood Diversity (Shannon Entropy)",
        "feature_category": FeatureCategory.NEIGHBORHOOD_COMPOSITION,
        "measurement_method": (
            "Shannon entropy of cell class composition within a 50 µm radius "
            "around each tumor cell; higher entropy = more diverse cellular neighborhood"
        ),
        "measurement_unit": "bits",
        "evidence_type": FeatureType.BOTH,
        "evidence_level": "C",
        "moa_classes": ["checkpoint", "kinase", "default"],
        "tumor_types": ["NSCLC", "TNBC", "CRC", "MELA"],
        "claim": (
            "High cellular neighborhood diversity around tumor cells reflects "
            "an immune-rich TME and is associated with better prognosis and "
            "checkpoint inhibitor benefit."
        ),
        "references": ["33268085", "36029206", "34285125"],
    },
    {
        "feature_id": "he_tumor_stromal_interface",
        "feature_name": "Tumor-Stromal Interface Density",
        "feature_category": FeatureCategory.NEIGHBORHOOD_COMPOSITION,
        "measurement_method": (
            "Length of tumor-stroma boundary per unit area (mm/mm²), "
            "estimated from the perimeter of tumor cell clusters versus total tumor area"
        ),
        "measurement_unit": "mm/mm²",
        "evidence_type": FeatureType.PROGNOSTIC,
        "evidence_level": "C",
        "moa_classes": ["antiangiogenic", "kinase", "default"],
        "tumor_types": ["CRC", "NSCLC", "PDAC", "BRCA"],
        "claim": (
            "High tumor-stromal interface density (irregular infiltrative border) "
            "is associated with invasive growth phenotype and poor prognosis, "
            "while pushing border morphology indicates better immune containment."
        ),
        "references": ["22438968", "27462101"],
    },

    # ── Composite Features ─────────────────────────────────────────────────────

    {
        "feature_id": "he_immune_score",
        "feature_name": "Immune Score (TIL/TAM Composite)",
        "feature_category": FeatureCategory.COMPOSITE,
        "measurement_method": (
            "Composite score combining: stromal TIL%, intratumoral TIL density, "
            "and the lymphocyte-to-macrophage ratio; "
            "computed as (sTIL × 0.4) + (iTIL × 0.4) + (lymph/mac ratio × 0.2)"
        ),
        "measurement_unit": "composite score (0–100)",
        "evidence_type": FeatureType.BOTH,
        "evidence_level": "B",
        "moa_classes": ["checkpoint", "ddr", "default"],
        "tumor_types": ["NSCLC", "TNBC", "CRC", "GC", "MELA", "HNSCC"],
        "claim": (
            "Composite immune score integrating TIL density and macrophage balance "
            "outperforms individual TIL scores for predicting OS and IO response "
            "across multiple tumor types."
        ),
        "references": ["29667924", "31570881", "35764077"],
    },
    {
        "feature_id": "he_tumor_purity",
        "feature_name": "Tumor Purity Index",
        "feature_category": FeatureCategory.COMPOSITE,
        "measurement_method": (
            "Fraction of total cells in the tumor region that are tumor cells "
            "(tumor cells / all cells); computed from cell class counts"
        ),
        "measurement_unit": "fraction (0–1)",
        "evidence_type": FeatureType.PROGNOSTIC,
        "evidence_level": "C",
        "moa_classes": ["kinase", "cell_cycle", "ddr", "default"],
        "tumor_types": ["NSCLC", "BRCA", "CRC", "PDAC"],
        "claim": (
            "Tumor purity strongly influences molecular biomarker sensitivity; "
            "low purity (high immune infiltrate) correlates with better prognosis "
            "and serves as a normalizer for density-based features."
        ),
        "references": ["25214461", "31409606"],
    },

    # ── Anti-angiogenic / Vascular features ──────────────────────────────────
    # Critical for bispecific anti-PD-1/VEGF drugs (e.g., ivonescimab) and
    # anti-angiogenic combinations. VEGF inhibition normalizes vessels and
    # reshapes immune exclusion — these features capture that on H&E.

    {
        "feature_id": "he_necrosis_fraction",
        "feature_name": "Tumor Necrosis Fraction",
        "feature_category": FeatureCategory.CELL_DENSITY,
        "roi": "whole_section",
        "roi_annotation_guide": (
            "Annotate all areas of coagulative necrosis within the tumor mass "
            "(pale, eosinophilic regions with ghost cells and no live nuclei); "
            "exclude treatment-related necrosis if known."
        ),
        "measurement_method": (
            "Segment the whole tumor area on H&E. Identify necrotic regions as "
            "areas with loss of nuclear staining and ghost cell outlines. "
            "Report necrosis fraction = necrotic area / total tumor area (0–1)."
        ),
        "measurement_unit": "fraction (0–1)",
        "evidence_type": FeatureType.PROGNOSTIC,
        "evidence_level": "B",
        "moa_classes": ["antiangiogenic", "bispecific", "hypoxia", "default"],
        "tumor_types": ["ccRCC", "NSCLC", "GBM", "HCC", "MELA"],
        "is_macrophage_primary": False,
        "claim": (
            "High tumor necrosis fraction reflects intratumoral hypoxia and "
            "predicts poor prognosis; in anti-VEGF settings it serves as a "
            "baseline hypoxia indicator and is reduced by successful vascular "
            "normalization. Relevant for HIF-2α and VEGF-targeted therapies."
        ),
        "references": ["16818850", "23093548", "30530754"],
    },
    {
        "feature_id": "he_tumor_stroma_ratio",
        "feature_name": "Tumor-Stroma Ratio (TSR)",
        "feature_category": FeatureCategory.COMPOSITE,
        "roi": "whole_section",
        "roi_annotation_guide": (
            "Assess the hotspot area with the highest stromal proportion relative "
            "to tumor cells; select a representative 1–2 mm² field in the invasive "
            "front or core with highest stroma-to-tumor ratio."
        ),
        "measurement_method": (
            "In QuPath or manually on H&E, estimate the proportion of stroma "
            "(fibrous connective tissue + non-immune cells) vs viable tumor cells "
            "in a representative field. TSR = stroma area / (stroma + tumor area). "
            "Classify as stroma-low (<50%) vs stroma-high (≥50%)."
        ),
        "measurement_unit": "ratio (0–1) or categorical",
        "evidence_type": FeatureType.PROGNOSTIC,
        "evidence_level": "A",
        "moa_classes": ["antiangiogenic", "bispecific", "kinase", "default"],
        "tumor_types": ["CRC", "BRCA", "NSCLC", "GC", "PDAC", "OV"],
        "is_macrophage_primary": False,
        "claim": (
            "High tumor-stroma ratio (stroma-rich) is a pan-cancer independent "
            "negative prognostic factor. In anti-angiogenic settings, VEGF "
            "drives desmoplastic stroma; stroma-high tumors are associated with "
            "immune exclusion and poor response to combination IO/anti-VEGF therapies."
        ),
        "references": ["24214916", "28051820", "31649359"],
    },
    {
        "feature_id": "he_perivascular_til_density",
        "feature_name": "Perivascular TIL Density",
        "feature_category": FeatureCategory.SPATIAL_DISTANCE,
        "roi": "vascular",
        "roi_annotation_guide": (
            "Annotate all visible vessels (arterioles, venules, capillaries) "
            "identifiable by their endothelial lining on H&E. Create a 50–100 µm "
            "buffer zone around each vessel wall as the perivascular ROI."
        ),
        "measurement_method": (
            "Segment vessel lumens on H&E. Define a 50–100 µm perivascular annulus "
            "around each vessel. Count lymphocytes within this zone normalized by "
            "total perivascular area (cells/mm²). Compare to non-perivascular TIL "
            "density to derive a perivascular TIL enrichment ratio."
        ),
        "measurement_unit": "cells/mm²; perivascular enrichment ratio",
        "evidence_type": FeatureType.PREDICTIVE,
        "evidence_level": "C",
        "moa_classes": ["antiangiogenic", "bispecific", "checkpoint"],
        "tumor_types": ["ccRCC", "NSCLC", "CRC", "HCC"],
        "is_macrophage_primary": False,
        "claim": (
            "Perivascular TIL density reflects T cell trafficking to the tumor "
            "via normalized vessels. Anti-VEGF therapy normalizes vessel morphology "
            "and enhances T cell extravasation; high perivascular TILs post-VEGF "
            "treatment correlates with response to subsequent IO. Key feature for "
            "bispecific anti-PD-1/VEGF drugs like ivonescimab."
        ),
        "references": ["27777256", "30635538", "34548279"],
    },
    {
        "feature_id": "he_stromal_vessel_density",
        "feature_name": "Stromal Vascular Density",
        "feature_category": FeatureCategory.CELL_DENSITY,
        "roi": "stroma",
        "roi_annotation_guide": (
            "Annotate the tumor-associated stroma (peritumoral connective tissue). "
            "Focus on areas adjacent to viable tumor nests; exclude areas of "
            "necrosis, normal tissue, and large vessels (>100 µm diameter)."
        ),
        "measurement_method": (
            "In the annotated stroma, count vessel profiles (cross-sections showing "
            "open lumens with endothelial lining and/or red blood cells). Normalize "
            "by total stromal area. Optionally score vessel tortuosity (1–3 scale) "
            "from straight/normalized (1) to highly tortuous/glomeruloid (3). "
            "Report as vessels/mm² and mean tortuosity score."
        ),
        "measurement_unit": "vessels/mm²; tortuosity score (1–3)",
        "evidence_type": FeatureType.BOTH,
        "evidence_level": "B",
        "moa_classes": ["antiangiogenic", "bispecific", "hypoxia"],
        "tumor_types": ["ccRCC", "HCC", "CRC", "NSCLC", "OV"],
        "is_macrophage_primary": False,
        "claim": (
            "High stromal vascular density with tortuous vessel morphology indicates "
            "active tumor angiogenesis and predicts response to anti-VEGF therapy. "
            "Vessel normalization (reduced density, reduced tortuosity) after "
            "anti-VEGF treatment correlates with improved T cell infiltration and "
            "is a key intermediate H&E endpoint for bispecific PD-1/VEGF drugs."
        ),
        "references": ["7585549", "18337604", "25417704"],
    },
    {
        "feature_id": "he_tils_excluded_pattern",
        "feature_name": "TIL Exclusion Pattern Score",
        "feature_category": FeatureCategory.SPATIAL_DISTANCE,
        "roi": "invasive_margin",
        "roi_annotation_guide": (
            "Annotate the invasive margin: the zone 500 µm inward and outward "
            "from the tumor-stroma boundary. The excluded pattern is defined by "
            "TILs present in this zone but absent from tumor nests (intratumoral)."
        ),
        "measurement_method": (
            "Calculate the ratio of invasive margin TIL density to intratumoral "
            "TIL density. A ratio >5 defines the 'excluded' phenotype. Also "
            "compute the mean nearest-neighbor distance from margin TILs to the "
            "nearest tumor nest boundary (exclusion gap in µm). Higher gap = "
            "stronger exclusion."
        ),
        "measurement_unit": "margin:intratumoral TIL ratio; exclusion gap (µm)",
        "evidence_type": FeatureType.PREDICTIVE,
        "evidence_level": "B",
        "moa_classes": ["antiangiogenic", "bispecific", "checkpoint"],
        "tumor_types": ["NSCLC", "TNBC", "BLCA", "CRC", "ccRCC"],
        "is_macrophage_primary": False,
        "claim": (
            "The immune-excluded phenotype — where TILs are trapped at the "
            "tumor margin by VEGF-driven stromal barriers — predicts poor response "
            "to checkpoint monotherapy. Anti-VEGF disrupts this exclusion mechanism; "
            "the shift from excluded to inflamed phenotype is the therapeutic "
            "rationale for bispecific anti-PD-1/VEGF drugs and is measurable "
            "as the TIL exclusion gap on H&E."
        ),
        "references": ["29443960", "31270127", "36693305"],
    },

    # ── ADC-specific features ─────────────────────────────────────────────────
    # ADCs deliver cytotoxic payloads directly to tumor cells expressing the target.
    # For TROP2-targeting ADCs (sacituzumab govitecan) and HER2-targeting ADCs
    # (trastuzumab deruxtecan), key H&E features reflect:
    #   1. Proliferative capacity (topoisomerase / tubulin inhibitors hit cycling cells)
    #   2. Tumor cell density and compactness (bystander killing amplified in dense nests)
    #   3. Epithelial differentiation (TROP2 is highest in glandular/epithelial cells)
    #   4. Immunogenic cell death signature (payload-driven ICD → secondary TIL influx)

    {
        "feature_id": "he_mitotic_index",
        "feature_name": "Mitotic Index",
        "feature_category": FeatureCategory.CELL_DENSITY,
        "roi": "tumor_nest",
        "roi_annotation_guide": (
            "Annotate all viable tumor cell nests. Focus scoring on the most "
            "mitotically active 'hotspot' areas — select 10 high-power fields (HPF) "
            "at 400× in regions of highest proliferative activity within tumor nests."
        ),
        "measurement_method": (
            "Count mitotic figures (cells in any phase of mitosis: prophase, "
            "metaphase, anaphase, telophase) in 10 consecutive HPF (0.2 mm² each) "
            "within tumor nests. Exclude necrosis and stroma. Report as mitotic "
            "figures per 10 HPF (MF/10HPF) or per mm². In QuPath, train a classifier "
            "on mitotic figure morphology (condensed/fragmented basophilic chromatin) "
            "and apply to annotated tumor ROI."
        ),
        "measurement_unit": "mitotic figures per 10 HPF or per mm²",
        "evidence_type": FeatureType.PREDICTIVE,
        "evidence_level": "B",
        "moa_classes": ["adc", "cell_cycle", "ddr"],
        "tumor_types": ["TNBC", "BRCA", "NSCLC", "UC", "GC"],
        "is_macrophage_primary": False,
        "claim": (
            "High mitotic index reflects rapid cell proliferation and predicts "
            "sensitivity to topoisomerase and tubulin-targeting ADC payloads. "
            "For TROP2-ADCs (sacituzumab govitecan, SN-38 payload), tumors with "
            "high mitotic rates show greater vulnerability to replication stress. "
            "Mitotic index also correlates with TROP2 expression in TNBC and NSCLC."
        ),
        "references": ["11504456", "26314551", "34099989"],
    },
    {
        "feature_id": "he_tumor_nest_compactness",
        "feature_name": "Tumor Nest Compactness Score",
        "feature_category": FeatureCategory.SPATIAL_CLUSTERING,
        "roi": "tumor_nest",
        "roi_annotation_guide": (
            "Annotate all viable tumor cell nests. Focus on areas where tumor cells "
            "form solid sheets or tightly packed clusters with minimal intervening stroma. "
            "Exclude dispersed single cells and loose glandular patterns."
        ),
        "measurement_method": (
            "Segment individual tumor cell nuclei within annotated nests. Compute the "
            "mean nearest-neighbor distance (NND) between tumor cell centroids — "
            "lower NND = more compact. Also calculate nest area vs perimeter ratio "
            "(circularity) to quantify solid vs glandular architecture. "
            "Compact (solid) nests: NND < 12 µm. Report as mean NND (µm) and "
            "solid nest fraction (% of tumor nests classified as solid vs glandular)."
        ),
        "measurement_unit": "mean NND (µm); solid nest fraction (%)",
        "evidence_type": FeatureType.PREDICTIVE,
        "evidence_level": "C",
        "moa_classes": ["adc"],
        "tumor_types": ["TNBC", "UC", "NSCLC", "CRC"],
        "is_macrophage_primary": False,
        "claim": (
            "Tightly packed solid tumor nests amplify ADC bystander killing: "
            "membrane-permeable payloads (e.g., SN-38 from sacituzumab govitecan, "
            "DXd from trastuzumab deruxtecan) diffuse to neighboring target-negative "
            "cells. Higher nest compactness (lower NND) predicts greater bystander "
            "effect magnitude. Solid growth pattern in TNBC correlates with both "
            "high TROP2 expression and SG response."
        ),
        "references": ["34099989", "35302400", "36198463"],
    },
    {
        "feature_id": "he_glandular_differentiation",
        "feature_name": "Glandular Differentiation Score",
        "feature_category": FeatureCategory.COMPOSITE,
        "roi": "tumor_nest",
        "roi_annotation_guide": (
            "Annotate viable tumor areas. Score architecture in 5 representative "
            "fields at 200× covering different zones of the tumor (center, periphery, "
            "and invasive front)."
        ),
        "measurement_method": (
            "Score tumor architecture on a 3-tier scale: "
            "1 = poorly differentiated (solid, no gland formation, sheets of cells); "
            "2 = moderately differentiated (partial gland formation, >10% glands); "
            "3 = well differentiated (predominant gland formation, tubular structures). "
            "In QuPath, use nuclear morphology and spatial arrangement classifiers "
            "to quantify solid vs glandular areas as a percentage. "
            "Report both categorical grade and solid-area fraction (%)."
        ),
        "measurement_unit": "grade 1–3; solid-area fraction (%)",
        "evidence_type": FeatureType.PREDICTIVE,
        "evidence_level": "B",
        "moa_classes": ["adc"],
        "tumor_types": ["TNBC", "BRCA", "NSCLC", "UC", "GC", "CRC"],
        "is_macrophage_primary": False,
        "claim": (
            "TROP2 is a cell-surface glycoprotein preferentially expressed in "
            "poorly differentiated epithelial tumors. Low glandular differentiation "
            "(solid, grade 1) correlates with TROP2 overexpression and predicts "
            "response to sacituzumab govitecan in TNBC and NSCLC. "
            "Well-differentiated glandular tumors (grade 3) tend to have lower "
            "TROP2 surface expression and reduced ADC uptake."
        ),
        "references": ["24916703", "32445781", "35302400"],
    },
    {
        "feature_id": "he_nuclear_pleomorphism",
        "feature_name": "Nuclear Pleomorphism Score",
        "feature_category": FeatureCategory.CELL_DENSITY,
        "roi": "tumor_nest",
        "roi_annotation_guide": (
            "Score nuclear pleomorphism in the area with the most atypical nuclei "
            "within tumor nests. Select 5 HPF at 400× in the most pleomorphic region."
        ),
        "measurement_method": (
            "Score nuclear pleomorphism on the standard Nottingham/Elston-Ellis scale: "
            "1 = nuclei small, uniform (≤1.5× normal lymphocyte); "
            "2 = moderate variation in size/shape; "
            "3 = marked variation, bizarre nuclei, prominent nucleoli. "
            "In QuPath, compute nuclear area coefficient of variation (CV), "
            "nuclear elongation, and mean nuclear area as objective correlates. "
            "Nuclear area CV >0.35 corresponds to grade 3 pleomorphism."
        ),
        "measurement_unit": "grade 1–3 (Nottingham); nuclear area CV",
        "evidence_type": FeatureType.PREDICTIVE,
        "evidence_level": "B",
        "moa_classes": ["adc", "cell_cycle", "ddr"],
        "tumor_types": ["TNBC", "BRCA", "NSCLC", "UC"],
        "is_macrophage_primary": False,
        "claim": (
            "High nuclear pleomorphism (grade 3) reflects genomic instability, "
            "elevated replication stress, and high proliferative index — all of which "
            "increase vulnerability to DNA-damaging ADC payloads. In TNBC, "
            "high-grade nuclear pleomorphism correlates with TROP2 expression "
            "and pathologic complete response to SN-38-based ADCs. "
            "Also relevant for DXd-based ADCs (topoisomerase I payload)."
        ),
        "references": ["11504456", "26314551", "33822570"],
    },
    {
        "feature_id": "he_icd_til_infiltrate",
        "feature_name": "Post-ADC ICD TIL Infiltration Pattern",
        "feature_category": FeatureCategory.TIL_SCORE,
        "roi": "tumor_nest",
        "roi_annotation_guide": (
            "Annotate areas within tumor nests showing lymphocyte infiltration "
            "adjacent to or within necrotic/apoptotic tumor cell clusters. "
            "Focus on intraepithelial compartments — TILs within tumor nests, "
            "not just peritumoral stroma."
        ),
        "measurement_method": (
            "Quantify intratumoral TILs (within tumor cell nests, not stroma) "
            "using TIIC Working Group guidelines adapted for intraepithelial "
            "localization. Compute intraepithelial TIL% = lymphocytes within "
            "tumor nests / total cells within nests × 100. "
            "Also calculate apoptotic index (cells with condensed/fragmented "
            "nuclei and cytoplasmic shrinkage) as a proxy for payload-driven "
            "immunogenic cell death."
        ),
        "measurement_unit": "intraepithelial TIL% ; apoptotic index",
        "evidence_type": FeatureType.PREDICTIVE,
        "evidence_level": "B",
        "moa_classes": ["adc", "ddr", "checkpoint"],
        "tumor_types": ["TNBC", "BRCA", "NSCLC", "UC"],
        "is_macrophage_primary": False,
        "claim": (
            "ADC payloads (especially topoisomerase I inhibitors like SN-38 and DXd) "
            "cause immunogenic cell death (ICD), releasing DAMPs that drive de novo "
            "T cell infiltration into tumor nests. Baseline intraepithelial TIL "
            "infiltration is a predictive biomarker for ADC response — high "
            "baseline intraepithelial TILs predict pCR to sacituzumab govitecan "
            "in TNBC independent of TROP2 IHC score."
        ),
        "references": ["34099989", "35302400", "36198463"],
    },
]


def get_he_features(
    moa_class: Optional[str] = None,
    evidence_level_filter: Optional[list[str]] = None,
) -> list[NormalizedPathologyFeature]:
    """
    Retrieve all H&E HIF catalog entries as NormalizedPathologyFeature records.

    This is tumor-type agnostic by design — the catalog covers pan-cancer evidence.
    Tumor type is noted in each entry's raw_data for informational context only;
    it is never used to exclude features. Any indication can be assessed.

    Args:
        moa_class: MOA class bucket from config.get_moa_class(). None = return all.
        evidence_level_filter: Optional list of acceptable levels (e.g., ["A", "B"]).

    Returns:
        List of NormalizedPathologyFeature objects — always the full relevant set.

    Example:
        features = get_he_features(moa_class="checkpoint")
        all_features = get_he_features()
    """
    results: list[NormalizedPathologyFeature] = []

    for entry in _HE_CATALOG:
        # MOA class soft filter: include all features but skip those with no MOA overlap
        # when a specific moa_class is given and the feature has a restricted list.
        if moa_class and entry["moa_classes"] and "default" not in entry["moa_classes"]:
            if moa_class not in entry["moa_classes"]:
                # Still include it — just mark that MOA alignment is weak.
                # The RankingAgent will apply a lower moa_weight for it.
                pass  # intentional: include all features, scoring handles relevance

        if evidence_level_filter:
            if entry["evidence_level"] not in evidence_level_filter:
                continue

        # Resolve ROI string to enum, default to whole_section
        roi_raw = entry.get("roi", "whole_section")
        try:
            roi = ROIType(roi_raw)
        except ValueError:
            roi = ROIType.WHOLE_SECTION

        feat = NormalizedPathologyFeature(
            source="HECatalog",
            source_id=entry["feature_id"],
            feature_name=entry["feature_name"],
            feature_category=entry["feature_category"],
            measurement_method=entry["measurement_method"],
            measurement_unit=entry["measurement_unit"],
            roi=roi,
            roi_annotation_guide=entry.get("roi_annotation_guide", ""),
            tumor_type=None,   # Tumor-type agnostic
            moa_class=moa_class,
            evidence_type=entry["evidence_type"],
            evidence_direction=EvidenceDirection.SUPPORTS,
            evidence_level=entry["evidence_level"],
            claim=entry["claim"],
            strength=0.0,  # Computed by RankingAgent
            raw_data={
                "feature_id": entry["feature_id"],
                "example_tumor_types": entry["tumor_types"],   # informational only
                "moa_classes": entry["moa_classes"],
                "references": entry["references"],
                "is_macrophage_primary": entry.get("is_macrophage_primary", False),
            },
        )
        results.append(feat)

    return results
