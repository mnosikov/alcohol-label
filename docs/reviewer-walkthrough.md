# Reviewer Walkthrough

Live app: https://label.af5.org

This walkthrough is the fastest way to evaluate the prototype without reading every implementation
note first. The demo queue may be empty immediately after a presentation reset; upload a mixed batch
from the Upload tab to populate PASS, FAIL, and NEEDS_REVIEW cases.

## Five-Minute Demo Path

1. Open the Queue tab.
   - Check the status counts for `Needs Review`, `Machine Passed`, and `Machine Failed`.
   - Use the search box for a brand, class/type, status, or partial case ID.

2. Open a `Needs Review` case.
   - Inspect the label image and application fields.
   - Look at the Layer Trail. Poor, blurry, skewed, or cropped labels should show local image-quality
     review evidence before any provider-backed automation.
   - Use the decision note and action buttons to see the human-in-the-loop workflow.

3. Open a `Machine Failed` case.
   - Inspect Field Evidence. Failed cases should show expected versus extracted values, verdicts,
     and confidence.
   - Confirm the top badge shows `FAIL` while the case status records the operational state.

4. Open a `Machine Passed` case.
   - Confirm Field Evidence shows matched application fields and the label recommendation is `PASS`.
   - This demonstrates that the app can automate clean cases while preserving evidence.

5. Open the Upload tab.
   - Upload a CSV manifest plus selected images, or a ZIP containing `manifest.csv`.
   - Watch the batch progress card for accepted, ignored, rejected, and processed counts.

6. Open the Audit tab.
   - Confirm operational actions are persisted as audit events.

7. Try a single upload.
   - Upload one front label, optionally add a rear label, and fill the application fields.
   - Required batch manifest columns are `filename`, `brand_name`, `class_type`, `alcohol_content`,
     `net_contents`, `applicant_name_address`, and `source_of_product`.
   - The responsible party address must include at least a U.S. state. Imported products also
     require `country_of_origin`.

## What To Look For

- The app is the review console itself, not a landing page.
- The routing path is deliberately layered: deterministic rules, local OCR, local image quality,
  optional vision provider, then human review.
- The network-blocked environment is handled directly: provider access is optional, and provider
  failures become reviewable cases instead of broken UI states.
- Government warning checks use the canonical warning text and all-caps prefix.
- Degraded scans route conservatively to human review rather than producing adverse automated
  decisions from weak evidence.
- Human decisions are stored separately from machine recommendations.

## Evaluation Evidence

The deterministic golden eval suite runs offline with fixture OCR and vision payloads:

```bash
python -m backend.app.evals.golden
```

The balanced generated batch produced:

| Route | Expected | Actual |
| --- | ---: | ---: |
| PASS | 13 | 13 |
| FAIL | 6 | 6 |
| NEEDS_REVIEW | 6 | 6 |

The 20-label mixed presentation batch adds real-world labels with front/back pairs, decorative
layouts, missing required fields, warning punctuation failures, and low-confidence review cases:

| Route | Expected | Actual |
| --- | ---: | ---: |
| PASS | 12 | 12 |
| FAIL | 5 | 5 |
| NEEDS_REVIEW | 3 | 3 |

## Demo And Security Notes

- The public demo sets `PUBLIC_REVIEW_ENABLED=true`, so evaluators can test the full PRD workflow
  without credentials. A production deployment can set `PUBLIC_REVIEW_ENABLED=false` plus
  `REVIEW_TOKEN`; the UI then shows a reviewer-token field and sends it as `X-Review-Token`.
- OpenAI vision extraction is optional and server-side. `VISION_PROVIDER=noop` keeps the app usable
  without outbound ML calls.
- The app does not integrate with COLA, federal identity, or real adjudication systems.
- Test assets used for manual production queues are intentionally kept outside the repository; the
  app does not depend on them at runtime.
