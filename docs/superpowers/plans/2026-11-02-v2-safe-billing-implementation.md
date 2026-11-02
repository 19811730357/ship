# V2 Safe Billing Implementation Plan

> **For agentic workers:** Execute the approved plan task by task with independent agents and review. Use test-driven-development; keep all generated files on D:.

**Goal:** Make V2 extract individual charges and safely preview, review and commit scoped changes with evidence and atomic audit.

**Architecture:** Keep the existing Python modules. Both database and in-memory modes use one planner/validator/commit pipeline. Introduce additive scoped tables and preserve legacy records as historical summaries.

**Tech Stack:** Python, Pydantic 2, Streamlit, SQLite/MySQL, LangChain, pytest.

## Global Constraints

- Workspace: D:/桌面/湃乐多笔试题/shipping-billing-agent-v2.
- No C: writes, live database mutations, model calls or service uploads in tests.
- Default preview; transactions recheck scope and version. No silent parse loss or successful placeholders.

## Task 1: Reproduce unsafe persistence and planning

Files: tests/test_safe_billing.py, src/billing_agent/database.py, smart_crud.py, validator.py.

- [x] Add failing assertions for different-entity same-number lookup, 65/35 ambiguity, unauthorized difference, missing-field inheritance, version race, rollback and scoped source retry.
- [x] Run `python -B -m pytest -p no:cacheprovider tests/test_safe_billing.py -q` with project D: temporary storage; record expected failures.
- [x] Implement `plan(decision, source_documents, allow_updates)` without writes and `commit_plans(plans, source_events, session_id)` with transactional version checking.
- [x] Rerun new and existing tests.

## Task 2: Extraction contract

Files: models.py, agent.py, tests/test_extraction.py.

- [x] Test zero preservation, error retention, no manufactured evidence/high confidence, independent same-name rows and restricted second-stage candidates before implementation.
- [x] Add typed references, amount roles and field evidence with backwards-compatible fields.
- [x] Replace total-only prompt; implement `propose_changes(batch, candidates)` and validate its output independently.

## Task 3: Parsers and storage

Files: runtime.py, parsers.py, integrations.py, logger_config.py, tests/test_parsing_pipeline.py.

- [x] Test actual fake-adapter image OCR, EML recursive attachment content, source blocks, failures and D: paths.
- [x] Implement local upload/OCR, source archive, error propagation and safe own-object cleanup.
- [x] Preserve mixed PDF pages and source locations; do not mark unavailable OCR as success.

## Task 4: Unified workflow and review

Files: workflow.py, workflow_db.py, ledger.py, tests/test_safe_workflow.py.

- [x] Test default preview causes no ledger writes, commit version checking, review selection, complete snapshots and duplicate/retry statuses.
- [x] Implement `process_real_files(..., preview_only=True, allow_updates=False)` and `commit_preview(preview_id, review_actions=None)`.
- [x] Route demo and memory persistence through the same planner; preserve metadata and audit.

## Task 5: UI and delivery

Files: app.py, README.md, requirements.txt, pytest.ini, tests/test_app_contract.py.

- [x] Test workflow signature and review state contract; default to preview and persist preview context across reruns.
- [x] Display source evidence, candidate selection, field differences, errors and truthful commit status.
- [x] Restrict offline test discovery; document migration, current limitations and separate live verification.
- [x] Run the offline suite, AST checks and focused independent code review. Record exact results without claiming live service acceptance.
