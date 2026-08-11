# Motif Forge Development Guidance

Read `docs/PROJECT_GUIDE.md` and the relevant contract document before changing code. Use `.agents/skills/motif-forge-development/SKILL.md` for every Motif Forge implementation or review task.

- Implement one vertical slice at a time; do not prebuild empty future layers.
- Keep `domain` free of FastAPI, LangGraph, database, queue, filesystem, and model SDK imports.
- Keep Agent-visible tools read-only or pure. Persistence, render scheduling, downloads, and revision commits remain Application commands.
- Treat Revision and CandidateSnapshot as immutable. PreviewCandidate is a separate approval lifecycle object, and Branch head is the only authoritative current pointer.
- Use `deepseek-v4-flash` explicitly. Never expose API keys or `reasoning_content` in logs, traces, fixtures, or API responses.
- Add focused tests and a failure/eval case with every Graph, Provider, domain, or persistence change.
- Run `uv run pytest`, `uv run ruff check .`, and `uv run mypy` before handoff.
