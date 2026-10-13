# Local verification report

Date: 2026-10-13. These are observed local checks, not claims of production or live-model certification.

## Executed

- Created a clean Python 3.14 virtual environment and successfully installed `backend/requirements.txt` from the package index.
- `python -m unittest discover -s backend/tests -q`: **43 tests passed**, including a real background worker with a test-only provider, transactional receipts, privacy, hard constraints, historical price precedence, restart recovery and private reference-weight calibration.
- `node backend/tests/test_sse.cjs`: UTF-8 Chinese/emoji and CRLF streaming split-boundary cases passed.
- `node scripts/check-miniprogram.cjs`: **8 page definitions** passed file, JSON, JS syntax and event-handler checks.
- `node --check web/app.js` and Python compile checks passed.
- `python scripts/test_web.py`: headless Microsoft Edge connected to a **real temporary FastAPI server**, not a mocked REST API. Verified local login, group creation, inventory entry, actual-payment ledger, profile save, missing-AI-key failure, zero page exceptions, and desktop/mobile horizontal-overflow checks.
- Desktop (1440 px) and mobile (390 px) screenshots were rendered and visually reviewed. Screenshots contain explicitly labeled synthetic acceptance-test inputs, not real user records or fabricated AI output.

## Not executed / unavailable without configuration

- No live DeepSeek request, photo accuracy benchmark, weekly-plan latency measurement or paid token report.
- No WeChat developer-tool compile, real AppID login, device rendering, canvas export or domain/network validation.
- No Docker image build or remote load test.
- No external WeChat subscription-message push.
- No full live-model demonstration video.
- GitHub Actions execution status must be checked separately after push; local passing results do not assert remote CI success.

A dependency deprecation notice currently states that future Starlette test clients prefer `httpx2`; it does not fail the pinned dependency test run. Provider requests use the explicitly pinned `httpx` client.
