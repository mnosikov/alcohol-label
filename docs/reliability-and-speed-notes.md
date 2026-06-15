# Reliability And Speed Notes

Concise reliability and performance notes for the reviewer-facing submission.

## Product Goal

The verifier should process ordinary cases in 5 seconds or less. When the app cannot gather reliable
machine evidence inside that budget, the correct behavior is to route the case to human review with
field evidence, not to block the queue or make an unsupported decision.

## Reliability Principles

- Preserve evidence even when a case escalates. Human-review cases should still show Field Evidence
  rows so reviewers can see what the machine extracted and why it was uncertain.
- Use deterministic evidence first. OCR and rule comparisons should resolve easy cases and provide a
  no-network path for blocked agency environments.
- Treat provider output as extraction evidence, not truth. The uploaded label image and submitted
  application fields remain the authoritative sources.
- Fail only when the mismatch is supported by strong evidence. Stylized or degraded text that is
  close but not definitive should become `NEEDS_REVIEW`, not a hard machine `FAIL`.
- Keep the statutory government warning strict. Missing words, missing punctuation, or an incorrectly
  cased prefix remain compliance issues unless another deterministic extraction proves the printed
  warning is actually correct.

## Documented Edge Cases

### Human Review With Blank Field Evidence

Issue: low-confidence OCR followed by an unavailable vision provider could route to human review
without persisting field comparison rows.

Resolution: low-confidence OCR now still runs field comparisons and stores those rows before
escalation. Provider-failure review items remain explainable instead of blank.

Regression coverage: `backend/tests/test_pipeline_runner.py` verifies that provider-failure paths
keep OCR field evidence.

### JALDA Color And Contrast Extraction

Issue: two visually similar JALDA labels had the same statutory warning in different colors. One
passed and one failed because the vision extraction misread the lower-contrast warning body and
stylized logo.

Observed extraction artifacts:

- `JALDA` was extracted as near matches such as `JADA`, `JAIDA`, or `JALPA`.
- The warning body was extracted as `Consumption of alcohol beverages` even though local OCR saw
  `Consumption of alcoholic beverages`.

Resolution:

- OCR raw text is preserved as an additional evidence candidate even when the vision provider also
  returns raw text.
- Stray OCR quote artifacts inside warning text are ignored for warning body comparison.
- Near brand reads route to `NEEDS_REVIEW` unless whole-label raw text proves the submitted brand is
  present.

Result after reprocessing:

- The warning matches for both JALDA cases.
- Both route to `NEEDS_REVIEW` for stylized brand uncertainty instead of splitting into pass/fail
  based on color-driven extraction artifacts.

Regression coverage: `backend/tests/test_rules.py` and `backend/tests/test_pipeline_runner.py`
cover near brand reads, OCR warning evidence, and quote-noise tolerance.

## Speed Posture

Current architecture keeps fast local layers before provider calls:

- Rule checks and normalization run in-process.
- Tesseract OCR runs locally.
- Local image-quality analysis runs before vision provider automation.
- OpenAI retries are disabled for verification calls.
- Provider calls use a bounded quality-first timeout and normalized JPEG payloads.

The known speed risk is provider tail latency, not local OCR or image-quality checks. The performance
baseline in `docs/performance-baseline.md` tracks:

- Median, p95, and max end-to-end case processing time.
- Provider latency median, p95, and max.
- Count of cases over 5 seconds.
- Count of provider timeouts routed to human review.
- Confirmation that golden evals and real-label spot checks still pass after speed tuning.

## Repository Hygiene

Sample labels and generated queue-test images are kept outside the repository. The submitted tree
keeps only application code, automated fixtures, deployment scripts, and reviewer-facing
documentation.
