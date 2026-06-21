# IntentKit LLM Guide

## Architecture

- `intentkit/` — pip package
  - `core/` — agent system (LangGraph)
    - `manager/` — single agent manager
    - `system_skills/` — built-in system skills
  - `models/` — Pydantic + SQLAlchemy dual models
  - `config/` — system config (DB, LLM keys, skill provider keys)
  - `skills/` — skill system (LangChain BaseTool)
  - `abstracts/` — interfaces for core/ and skills/
  - `utils/` — utilities
  - `clients/` — external service clients
- `app/` — API server, autonomous runner, background scheduler
- `frontend/` — Next.js agent management UI (see `frontend/AGENTS.md`)
- `integrations/` — Go channel adapters (see `integrations/AGENTS.md`)
  - `telegram/` — Telegram bot (see `integrations/telegram/AGENTS.md`)
  - `wechat/` — WeChat bot (see `integrations/wechat/AGENTS.md`)
- `scripts/` — ops & migration scripts
- `tests/` — `tests/core/`, `tests/api/`, `tests/skills/`

## Tech Stack & Gotchas

- Package manager: **uv**. Activate venv: `source .venv/bin/activate`
- Lint: `ruff format & ruff check --fix` after edits
- Type check: **BasedPyright** — ensure no errors in changed files
- **SQLAlchemy 2.0** — do NOT use legacy 1.x API
- **Pydantic V2** — do NOT use V1 API
- Testing: **pytest**

## Rules

- English for code comments and search queries
- Do not git commit unless explicitly asked
- After adding a new feature, add the corresponding tests.
- After modifying an existing feature, check whether any corresponding tests need to be updated, and make sure all tests pass.
- Import dependency order (left cannot import right): `utils → config → models → abstracts → clients → skills → core`
- **No ForeignKey constraints**: All tables intentionally omit `ForeignKey` constraints. Do NOT add FK constraints to any table definition.
- **AgentCore ↔ Template sync**: `AgentCore` (Pydantic) is the shared base for both `Agent` and `Template`. When adding/removing fields in `AgentCore`, you MUST also update `TemplateTable` (SQLAlchemy columns in `intentkit/models/template.py`) to match. The `Template` Pydantic model inherits from `AgentCore` automatically, but the DB schema does not. Agent-specific fields like `slug` belong in `AgentUserInput`, not `AgentCore`.

## Detailed Guides

- Skills: `agent_docs/skill_development.md`
- Git/PR/Release: `agent_docs/ops_guide.md`
- Testing: `agent_docs/test.md`

## Shared Agent Practices
- Keep changes clean, modular, and professional. Prefer small, cohesive modules, clear naming, explicit boundaries, and tests over quick patches.
- When code behavior, public APIs, user workflows, operator workflows, or configuration semantics change, check whether `../xian-docs-web` needs corresponding documentation updates. If this repo is `xian-docs-web`, update the relevant published docs in place. Write durable user/developer documentation, not a changelog entry.
- For any non-trivial code change, update the local graph before final verification when `graphify-out/graph.json` exists. Run `graphify update .` from the repo root, or `graphify update . --force` when deletions or refactors intentionally shrink the graph.
- After updating the graph, check cross-repo impact before finishing: query the local `graphify-out/graph.json`, inspect paths with `graphify path` or `graphify explain`, and note any affected sibling repos.
- If graphify or dependency analysis shows affected sibling repos, update those repos in the same change when the impact is real and the fix is in scope.
- Treat `graphify-out/` as a generated local artifact. Do not commit it.
