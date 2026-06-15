# Final Submission Readiness

| Requirement | Proof |
| --- | --- |
| Simple agent UI | Review Queue and Case Detail are the default workflow. |
| 5 second processing posture | Deterministic and OCR layers run before provider calls; OpenAI vision uses a bounded quality-first timeout, normalized image payloads, and recorded provider latency. |
| Batch uploads | CSV-plus-images or ZIP plus `manifest.csv` creates cases and queued jobs. |
| Government warning exactness | Canonical warning text and prefix checks are deterministic. |
| Network-blocked environment | Vision provider is swappable; blocked or disabled provider cases route to human review. |
| Poor scan handling | Local image-quality gate catches blur, glare, crop/damage, skew, and low contrast before model automation. |
| Human-in-the-loop | Human decisions are persisted and audit events are recorded. |
| Auditability | Tier events, field results, provider usage, human decisions, and audit events are stored. |
| Reviewer UI polish | Searchable queue, contained label viewer, field evidence cards, layer trail, batch monitor, and audit log. |
| Human-in-the-loop demo | Public demo review actions are credential-free for evaluator usability via `PUBLIC_REVIEW_ENABLED=true`; production can disable that flag and set `REVIEW_TOKEN` to require `X-Review-Token`. |
| Deployed app | `https://label.af5.org` after manual GitHub Actions deploy. |
| Production-shaped deploy | Docker Compose, Traefik labels, health checks, and VPS smoke scripts are included. |
| Build workflow evidence | Beads issue slicing is documented in `docs/agents/beads.md`. |
| Production eval evidence | Upload-ready mixed and synthetic batches cover PASS, FAIL, and NEEDS_REVIEW outcomes. The balanced generated batch matched current production routing at 13 PASS, 6 FAIL, and 6 NEEDS_REVIEW; the balanced mixed batch matched at 12 PASS, 5 FAIL, and 3 NEEDS_REVIEW. |
| Reliability and speed tuning | Current edge-case notes and the 5-second target are documented in `docs/reliability-and-speed-notes.md`. |

## Latest Verification

Completed June 14, 2026:

| Check | Result |
| --- | --- |
| Backend tests and Ruff in the final main pipeline | Passed |
| Frontend production build in the final main pipeline | Passed |
| Docker build in the final main pipeline | Passed |
| VPS deploy for the latest app commit | Passed |
| Production smoke script | Passed |
| Production queue reset workflow | Passed via manual GitHub Actions `purge_cases=true`. |
| Production batch upload smoke | Passed with mixed and synthetic upload-ready batches. |
| Live desktop browser QA | Passed: no console messages, no evidence-panel horizontal overflow, queue pane scrolls inside viewport, image viewer no longer clips tall labels. |
| Live narrow/mobile browser QA | Passed: no horizontal page overflow; queue and detail stack cleanly. |

Verification commands:

```bash
pytest backend/tests -q
ruff check backend
npm --prefix frontend run build
docker compose build
BASE_URL=https://label.af5.org bash scripts/smoke-production.sh
```

## Known Boundaries

- This prototype does not integrate with COLA or federal identity systems.
- OCR confidence and visual bold detection are conservative. Uncertain cases route to human review.
- Blurry labels with likely missing warnings route to human review rather than machine failure because
  degraded evidence should not create an adverse automated decision.
- OpenAI vision extraction is optional for the public demo and should be replaced with an approved endpoint for an agency network.
