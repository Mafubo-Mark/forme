"""Summarize the video ruler calibration without treating it as a fit check."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def build(project: Path, submission_id: str) -> dict:
    analysis = project / "analysis"
    primary = json.loads((analysis / "scale-calibration.json").read_text())
    independent = json.loads((analysis / "scale-calibration-original-check.json").read_text())
    sections = json.loads((analysis / "sections-draft.json").read_text())
    preflight_path = project / "forme-backend" / "data" / "cover_tasks" / submission_id / "template_physical_preflight.json"
    preflight = json.loads(preflight_path.read_text())
    bar_length = float(primary["measured_ab_mm"])
    if bar_length != float(independent["measured_ab_mm"]):
        raise ValueError("Calibration sources disagree on bar length")
    scales = [float(primary["mm_per_colmap_unit"]), float(independent["mm_per_colmap_unit"])]
    relative_spread_pct = abs(scales[0] - scales[1]) / ((scales[0] + scales[1]) / 2) * 100
    reported_span = float(sections["measured_span_mm"])
    section_rows = []
    for station in sections["stations"]:
        section_rows.append({
            "referenceAxialCoordinateMm": station["height_mm"],
            "candidateInnerWidthMm": station["inner_width_mm"],
            "candidateInnerDepthMm": station["inner_depth_mm"],
            "observedAngularBinsOf24": station["observed_angular_bins_of_24"],
            "pointsInBand": station["points_in_band"],
        })
    return {
        "status": "RULER_SCALED_EXPLORATORY_GEOMETRY",
        "submissionId": submission_id,
        "source": "same-video 200 mm printed target; no current physical prosthesis measurements",
        "calibration": {
            "knownTargetLengthMm": bar_length,
            "primaryMmPerColmapUnit": scales[0],
            "independentReconstructionMmPerColmapUnit": scales[1],
            "reconstructionScaleSpreadPercent": round(relative_spread_pct, 4),
            "primaryCommonImages": primary["quality"]["common_images"],
            "independentCommonImages": independent["quality"]["common_images"],
            "interpretation": "The spread compares two reductions of the same ruler, not an accuracy interval or independent physical validation.",
        },
        "candidateGeometry": {
            "visibleAxialSpanMm": reported_span,
            "visibleAxialSpanAtIndependentScaleMm": round(reported_span * scales[1] / scales[0], 3),
            "sectionSource": str(analysis / "sections-draft.json"),
            "sections": section_rows,
            "interpretation": "These are envelope candidates from a noisy/incomplete segmented COLMAP cloud, including its chosen margin and clearance; they are not measured outer dimensions.",
        },
        "templateComparison": {
            "templateId": preflight["templateId"],
            "oldConditionalUpperWidthDeficitMm": preflight.get("conditionalWidthScreen", {}).get("remainingDeficitMm"),
            "oldConditionalResultValid": False,
            "reason": "The assumed 120 mm physical outer width is unavailable and its section was not registered to the template opening. The template opening is below the prosthesis top rim.",
            "nextStep": "Register template and reference at matched height/orientation before comparing inner cavity and clearance; use multiple candidate scales and collision envelopes.",
        },
        "uncertainty": {
            "scale": "Two same-video reconstructions differ by about 0.071%; target printing and endpoint placement are not included.",
            "surface": "Point-cloud gaps, segmentation, occlusion, and Hunyuan shape disagreement dominate local fit uncertainty; no calibrated confidence interval is available.",
            "boltAndFastener": "Side, protrusion and mating geometry remain inferred from images only.",
        },
        "allowedUse": "visual prototype and registered fit-study candidates only",
        "printForWearApproved": False,
        "fitVerified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--submission-id", required=True)
    args = parser.parse_args()
    result = build(args.project, args.submission_id)
    output = args.project / "forme-backend" / "data" / "cover_tasks" / args.submission_id / "ruler_only_assessment.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(output), "status": result["status"], "scaleSpreadPercent": result["calibration"]["reconstructionScaleSpreadPercent"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
