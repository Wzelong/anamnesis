## Summary

<!-- What does this change do, and why? -->

## Related issue

<!-- Closes #NNN -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor / cleanup
- [ ] Documentation
- [ ] Pipeline / prompt change (may affect accuracy — note benchmark impact)

## Checklist

- [ ] Tests pass locally (`uv run pytest` in `backend/`)
- [ ] Lint and format clean (`uv run ruff check .` and `ruff format --check .`)
- [ ] Review app type-checks (`npm run typecheck` in `mcp-app/`)
- [ ] Built UI assets committed if `mcp-app/` changed (`npm run build`)
- [ ] Provenance invariant preserved (proposals carry source refs; writes carry `Provenance`)
- [ ] No PHI persisted; no secrets committed
- [ ] Docs updated if behavior or architecture changed

## Notes for reviewers

<!-- Anything that needs extra attention, tradeoffs, follow-ups. -->
