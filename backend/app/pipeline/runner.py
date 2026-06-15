from dataclasses import dataclass, field, replace
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.db.models import FieldResultRow, ProviderUsage, TierEvent
from backend.app.observability.langsmith import traceable
from backend.app.pipeline.evidence import LABEL_APPLICATION_SOURCES, confidence_evidence
from backend.app.pipeline.image_quality import (
    LocalImageQualityAssessment,
    assess_local_image_quality,
    describe_quality_flags,
    summarize_quality_flags,
)
from backend.app.pipeline.ocr import OcrProvider, parse_ocr_text
from backend.app.pipeline.rules import compare_application_to_extraction
from backend.app.pipeline.types import (
    ApplicationFields,
    ExtractedFields,
    FieldVerdict,
    LayerName,
    LayerOutcome,
    MachineDecision,
)
from backend.app.pipeline.vision import VisionExtraction, VisionProvider

LOCAL_QUALITY_PASS_VETO_FLAGS = {"local_low_contrast", "local_blur"}


@dataclass(frozen=True)
class PipelineResult:
    recommendation: MachineDecision
    events: list[LayerOutcome]
    provider_usage: list[VisionExtraction] = field(default_factory=list)


class VerificationPipeline:
    def __init__(self, ocr: OcrProvider, vision: VisionProvider) -> None:
        self.ocr = ocr
        self.vision = vision

    @traceable(
        name="verification_pipeline",
        run_type="chain",
        process_inputs=lambda inputs: {
            "image_filename": Path(inputs["image_path"]).name,
            "application_fields_present": {
                field_name: bool(getattr(inputs["application"], field_name))
                for field_name in (
                    "brand_name",
                    "class_type",
                    "alcohol_content",
                    "net_contents",
                    "fanciful_name",
                    "formula",
                    "grape_varietals",
                    "wine_appellation",
                    "serial_number",
                    "source_of_product",
                    "applicant_name_address",
                    "producer",
                    "country_of_origin",
                )
            },
        },
        process_outputs=lambda output: {
            "recommendation": output.recommendation.value,
            "events": [
                {
                    "layer": event.layer.value,
                    "decision": event.decision.value,
                    "confidence": event.confidence,
                    "error": bool(event.error),
                }
                for event in output.events
            ],
            "provider_usage": [
                {
                    "provider": usage.provider,
                    "model": usage.model,
                    "latency_ms": usage.latency_ms,
                    "tokens_input": usage.tokens_input,
                    "tokens_output": usage.tokens_output,
                    "error": bool(usage.error),
                }
                for usage in output.provider_usage
            ],
        },
    )
    def verify(self, image_path: Path, application: ApplicationFields) -> PipelineResult:
        events: list[LayerOutcome] = [
            LayerOutcome(
                LayerName.RULES,
                MachineDecision.NEEDS_REVIEW,
                0.4,
                "Extraction evidence required",
                evidence={
                    **confidence_evidence(
                        raw_score=0.4,
                        calibration_context="rules_require_extraction_v1",
                        out_of_distribution_flags=["no_extraction_evidence"],
                    ),
                    "source_references": LABEL_APPLICATION_SOURCES,
                },
            )
        ]

        text, ocr_confidence = self.ocr.extract_text(image_path)
        ocr_extracted = parse_ocr_text(text, ocr_confidence, application=application)
        if text and ocr_confidence >= 0.85:
            ocr_outcome = compare_application_to_extraction(
                application, ocr_extracted, LayerName.OCR
            )
        else:
            low_confidence_ocr_comparison = compare_application_to_extraction(
                application, ocr_extracted, LayerName.OCR
            )
            ocr_outcome = LayerOutcome(
                LayerName.OCR,
                MachineDecision.NEEDS_REVIEW,
                ocr_confidence,
                "OCR confidence below threshold",
                ocr_extracted,
                field_results=low_confidence_ocr_comparison.field_results,
                evidence={
                    **confidence_evidence(
                        raw_score=ocr_confidence,
                        calibration_context="ocr_text_confidence_v1",
                        out_of_distribution_flags=["low_ocr_confidence"],
                    ),
                    "source_references": LABEL_APPLICATION_SOURCES,
                },
            )
        events.append(ocr_outcome)
        local_quality = assess_local_image_quality(image_path)
        if local_quality.requires_review:
            events.append(
                LayerOutcome(
                    LayerName.IMAGE_QUALITY,
                    MachineDecision.NEEDS_REVIEW,
                    0.5,
                    local_quality.rationale,
                    evidence={
                        **confidence_evidence(
                            raw_score=0.5,
                            calibration_context="local_image_quality_gate_v1",
                            out_of_distribution_flags=local_quality.flags,
                        ),
                        "quality_metrics": local_quality.metrics,
                        "source_references": LABEL_APPLICATION_SOURCES,
                    },
                )
            )

        if _is_terminal_ocr_outcome(ocr_outcome):
            if _local_quality_should_veto_pass(local_quality) and (
                ocr_outcome.decision == MachineDecision.PASS
            ):
                events.append(_human_review_after_local_quality(local_quality))
                return PipelineResult(MachineDecision.NEEDS_REVIEW, events)
            return PipelineResult(ocr_outcome.decision, events)

        vision = self.vision.extract(image_path)
        provider_usage = [vision]
        if vision.error:
            events.append(
                LayerOutcome(
                    LayerName.VISION,
                    MachineDecision.NEEDS_REVIEW,
                    0.0,
                    "Vision provider unavailable",
                    evidence={
                        **confidence_evidence(
                            raw_score=0.0,
                            calibration_context="vision_provider_availability_v1",
                            out_of_distribution_flags=["vision_provider_unavailable"],
                        ),
                        "source_references": LABEL_APPLICATION_SOURCES,
                    },
                    error=vision.error,
                    latency_ms=vision.latency_ms,
                )
            )
            events.append(
                LayerOutcome(
                    LayerName.HUMAN_REVIEW,
                    MachineDecision.NEEDS_REVIEW,
                    None,
                    "Human review required after provider failure",
                    evidence={
                        "decision_authority": "human_decider",
                        "reason": "provider_failure",
                        "source_references": LABEL_APPLICATION_SOURCES,
                    },
                )
            )
            return PipelineResult(MachineDecision.NEEDS_REVIEW, events, provider_usage)

        vision_extracted = ExtractedFields(**vision.extracted)
        vision_extracted = _merge_ocr_raw_text_evidence(vision_extracted, ocr_extracted)
        vision_extracted = _apply_ocr_warning_prefix_evidence(
            vision_extracted,
            ocr_extracted,
        )
        vision_outcome = compare_application_to_extraction(
            application, vision_extracted, LayerName.VISION
        )
        events.append(vision_outcome)
        if _local_quality_should_veto_pass(local_quality) and (
            vision_outcome.decision == MachineDecision.PASS
        ):
            events.append(_human_review_after_local_quality(local_quality))
            return PipelineResult(MachineDecision.NEEDS_REVIEW, events, provider_usage)
        if vision_outcome.decision == MachineDecision.NEEDS_REVIEW:
            events.append(
                LayerOutcome(
                    LayerName.HUMAN_REVIEW,
                    MachineDecision.NEEDS_REVIEW,
                    None,
                    "Human review required after uncertainty",
                    evidence={
                        "decision_authority": "human_decider",
                        "reason": "uncertain_or_incomplete_evidence",
                        "source_references": LABEL_APPLICATION_SOURCES,
                    },
                )
            )
        return PipelineResult(vision_outcome.decision, events, provider_usage)


def _local_quality_should_veto_pass(local_quality: LocalImageQualityAssessment) -> bool:
    return any(flag in LOCAL_QUALITY_PASS_VETO_FLAGS for flag in local_quality.flags)


def _human_review_after_local_quality(local_quality: LocalImageQualityAssessment) -> LayerOutcome:
    findings = summarize_quality_flags(local_quality.flags)
    return LayerOutcome(
        LayerName.HUMAN_REVIEW,
        MachineDecision.NEEDS_REVIEW,
        None,
        (
            "Human review required because local image quality flagged "
            f"{findings}. Verify label legibility before approval."
        ),
        evidence={
            "decision_authority": "human_decider",
            "reason": "local_image_quality",
            "quality_flags": local_quality.flags,
            "quality_findings": describe_quality_flags(local_quality.flags),
            "quality_metrics": local_quality.metrics,
            "source_references": LABEL_APPLICATION_SOURCES,
        },
    )


def _merge_ocr_raw_text_evidence(
    vision_extracted: ExtractedFields,
    ocr_extracted: ExtractedFields,
) -> ExtractedFields:
    if not ocr_extracted.raw_text:
        return vision_extracted
    if not vision_extracted.raw_text:
        return replace(vision_extracted, raw_text=ocr_extracted.raw_text)

    ocr_raw_text = " ".join(ocr_extracted.raw_text.split())
    vision_raw_text = " ".join(vision_extracted.raw_text.split())
    if not ocr_raw_text or ocr_raw_text in vision_raw_text:
        return vision_extracted
    if vision_raw_text in ocr_raw_text:
        return replace(vision_extracted, raw_text=ocr_extracted.raw_text)

    combined_raw_text = f"{ocr_extracted.raw_text}\n{vision_extracted.raw_text}"
    return replace(vision_extracted, raw_text=combined_raw_text)


def _is_terminal_ocr_outcome(outcome: LayerOutcome) -> bool:
    if outcome.layer != LayerName.OCR or outcome.confidence is None or outcome.confidence < 0.9:
        return False
    if outcome.decision == MachineDecision.PASS:
        return True
    if outcome.decision != MachineDecision.FAIL:
        return False
    return any(
        result.field_name in {"alcohol_content", "net_contents"}
        and result.verdict == FieldVerdict.MISMATCH
        for result in outcome.field_results
    )


def _apply_ocr_warning_prefix_evidence(
    vision_extracted: ExtractedFields,
    ocr_extracted: ExtractedFields,
) -> ExtractedFields:
    ocr_warning = " ".join((ocr_extracted.government_warning or "").split())
    vision_warning = " ".join((vision_extracted.government_warning or "").split())
    prefix = "GOVERNMENT WARNING:"
    if not ocr_warning.startswith(prefix):
        return vision_extracted
    if not vision_warning.casefold().startswith(prefix.casefold()):
        return vision_extracted
    if vision_warning.startswith(prefix):
        return vision_extracted

    corrected_warning = f"{prefix}{vision_warning[len(prefix):]}"
    return replace(vision_extracted, government_warning=corrected_warning)


def persist_pipeline_result(session: Session, case, result: PipelineResult) -> None:
    for event in result.events:
        session.add(
            TierEvent(
                case_id=case.id,
                layer=event.layer.value,
                decision=event.decision.value,
                confidence=event.confidence,
                rationale=event.rationale,
                evidence=event.evidence,
                latency_ms=event.latency_ms,
                error=event.error,
            )
        )
        for result_field in event.field_results:
            session.add(
                FieldResultRow(
                    case_id=case.id,
                    field_name=result_field.field_name,
                    expected_value=result_field.expected_value,
                    extracted_value=result_field.extracted_value,
                    verdict=result_field.verdict.value,
                    confidence=result_field.confidence,
                    rationale=result_field.rationale,
                    source_layer=result_field.source_layer.value,
                )
            )

    for usage in result.provider_usage:
        session.add(
            ProviderUsage(
                case_id=case.id,
                provider=usage.provider,
                model=usage.model,
                latency_ms=usage.latency_ms,
                tokens_input=usage.tokens_input,
                tokens_output=usage.tokens_output,
                estimated_cost_usd=usage.estimated_cost_usd,
                error=usage.error,
            )
        )
