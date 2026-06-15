# Verification Performance Baseline

Measured June 12, 2026 against the production API at `https://label.af5.org`
before the provider timeout and image normalization change.

## PRD Target

Verification should keep the automatic processing path within roughly 5 seconds.
If provider evidence cannot return inside that budget, the safer behavior is to
route the case to human review instead of holding the queue open.

## Production Baseline

Sample: latest 100 public cases loaded through `/api/cases` and `/api/cases/{id}`.

| Metric | Result |
| --- | ---: |
| Cases with OpenAI provider usage | 99 |
| Production model | `gpt-5.4-mini` |
| Provider latency median | 2,413 ms |
| Provider latency mean | 2,775 ms |
| Provider latency max | 12,735 ms |
| Provider calls over 5 seconds | 3 / 99 |

Conclusion: median latency is acceptable, but the tail is not acceptable for a
hard 5-second processing rule.

## Local Layer Timing

Sample: 10 representative lifelike labels from the local upload-ready test assets kept outside
the repository.

| Layer | Median | Mean | Max |
| --- | ---: | ---: | ---: |
| Tesseract OCR | 331 ms | 311 ms | 472 ms |
| Local image quality gate | 67 ms | 68 ms | 92 ms |

Conclusion: local layers are fast. The compliance risk is provider tail latency,
not OCR or image-quality analysis.

## Mitigation

- OpenAI client retries are disabled for verification calls.
- OpenAI vision requests use `OPENAI_TIMEOUT_SECONDS`, default `10.0`.
- Provider timeout/errors return a `VisionExtraction` error and route to human
  review through the existing provider-failure path.
- Images are normalized to JPEG before provider submission with tunable defaults:
  `OPENAI_IMAGE_MAX_SIDE=1600` and `OPENAI_IMAGE_JPEG_QUALITY=82`.

On the 50 lifelike labels, image normalization reduced median provider payload
bytes from 337,118 to 163,672, a 59.9% median reduction.

## June 13-14 Payload Tuning

Production briefly used the smaller speed-first payload:

```text
OPENAI_IMAGE_MAX_SIDE=800
OPENAI_IMAGE_JPEG_QUALITY=75
```

That kept several demo cases under the 5-second target, but a front/back label
submission later regressed because the combined verification image was reduced
too aggressively and the provider timed out just past 6 seconds. Production was
returned to the quality-first payload:

```text
OPENAI_TIMEOUT_SECONDS=10.0
OPENAI_IMAGE_MAX_SIDE=1600
OPENAI_IMAGE_JPEG_QUALITY=82
```

Direct reprocessing checks from the speed-first experiment:

| Case | Result | End-to-end | Provider latency |
| --- | --- | ---: | ---: |
| Bärenjäger net-contents mismatch | `FAIL` | 4.16 s | 2,121 ms |
| Thornfield gin clean pass | `PASS` | 4.16 s | 2,429 ms |
| Cala del Sol rum clean pass | `PASS` | 4.11 s | 1,980 ms |

The Bärenjäger case previously took about 5.1 seconds on the 1600/82 payload.
The smaller payload kept that case under the 5-second target during the initial
sample, but real front/back testing showed extraction quality and provider
success are more important than forcing a hard timeout.

## Current Posture

The application prioritizes reliable evidence over a hard timeout. Ordinary clean cases generally
complete within the 5-second target, while provider timeouts and low-confidence extraction paths
route to `needs_review` with stored field evidence. Regression coverage in the golden and
real-label eval suites protects the quality-first behavior.

Reliability edge cases discovered during real-label testing are tracked in
`docs/reliability-and-speed-notes.md`.
