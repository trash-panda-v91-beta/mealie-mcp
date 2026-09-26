# mealie-mcp

Model Context Protocol (MCP) server for [Mealie](https://github.com/mealie-recipes/mealie).
Exposes Mealie as MCP tools (recipes, meal plans, shopping lists and items, categories, tags,
foods, units) with API-token auth, token-bucket rate limiting, and connection pooling. Stack and
versions live in `pyproject.toml` and `server.py` - read those for the current shape, don't trust
this file.

## Common Tasks

```bash
mise run check    # hk: ruff, actionlint, rumdl, tombi, ty, yamllint, yamlfmt, pkl
mise run fix      # hk fix: auto-fix the same
mise run test     # uv run pytest
```

`mise run` is the command surface - use it for everything; no direct tool invocation. New tool /
client method flow lives in the `add-tool` skill. Run `mise install` once to get the toolchain
(uv, ruff, hk, ...).

## Release

Merging to `main` triggers `.github/workflows/release.yml` (release-please-action v5): it opens a
`release: vX.Y.Z` PR from Conventional Commits. Merge that PR to cut a release - release-please
bumps the version in `pyproject.toml` + README, tags it, and updates `CHANGELOG.md`. Config lives in
`.release-please-config.json` / `.release-please-manifest.json`.

- Conventional commits drive the version bump and changelog; `chore` is hidden, breaking changes
  bump major.
- Multi-change PRs: use footer syntax (one conventional-commit stanza per change) so each lands as
  its own changelog entry - see the `release-please-pr` skill.

## Layout

- `src/mealie_mcp/server.py` - all MCP tools (async funcs with `@mcp.tool` + `_guard`)
- `src/mealie_mcp/client.py` - async httpx API client (rate limiting, retry, bearer auth)
- `src/mealie_mcp/config.py` - env-driven config
- `tests/` - pytest suite (mocked httpx transport)
- `.agents/skills/add-tool/` - repo-local skill for adding a tool

## Conventions

- Mealie responses are passed through as-is (no response models); the client returns parsed JSON or
  `None` for empty bodies
- List filters (`categories`, `tags`, `tools`) take **slugs**, not display names, and are sent as
  comma-separated values
- Recipe update is `PUT` (full replace), partial edits use `PATCH`; fetch with `get_recipe` first
- Shopping item update merges the current item before `PUT`, because Mealie's PUT expects a full
  object
- Ad-hoc analysis scripts go in `tmp/` (gitignored); formal tests go in `tests/`
- Don't create `docs/adr/` or `CONTEXT.md`; repo metadata stays out-of-tree
- Commit messages use Conventional Commits: `feat`, `fix`, `chore`, `refactor`, `docs`, `ci`, ...
  Scope optional (e.g. `fix(update_shopping_list_item): ...`). release-please drives versioning +
  changelog from these.

## Domain

- Recipe - slug-addressed; ingredients/tags/categories are denormalized onto the recipe object
- Meal plan entry - a dated breakfast/lunch/dinner/side, referencing a recipe or a free title
- Shopping list - household-scoped; items may be free-text notes or structured food+unit+quantity
- Organizer - the shared taxonomy: categories, tags, recipe tools (equipment)
- Food / unit - ingredient vocabulary used for structured shopping items and recipe ingredients

## Links

- Repo: git@github.com:trash-panda-v91-beta/mealie-mcp.git
- Mealie API: https://demo.mealie.io/docs (OpenAPI at `/docs`)
