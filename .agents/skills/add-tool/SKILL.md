---
name: add-tool
description: Add a new MCP tool or Mealie API method to this server. Use when implementing a new tool, extending the Mealie API surface, or "add a tool" / "add an endpoint". Covers the 3-place pipeline (client method, tool, tests).
---

# Add a Tool/Endpoint

A new capability touches these spots, in order. Do them all, then run the checks.

## 1. Client method - `src/mealie_mcp/client.py`

Add a method to `MealieClient` and call it from the tool via `get_client()`. Use an `httpx` request
against the Mealie REST API. Remember:

- list filters (`categories`, `tags`, `tools`) take **slugs** and are comma-joined via `_compact`
- `PUT /api/recipes/{slug}` is a full replace; partial edits use `PATCH`
- shopping item `PUT` needs a full object - fetch, merge, then put (see `update_shopping_list_item`)
- bulk shopping item delete sends repeated `ids` query params, so pass the list to `params` directly
  (do not run it through `_compact`, which would comma-join it)
- list endpoints return `{"items": [...], "pagination": {...}}`

## 2. Tool - `src/mealie_mcp/server.py`

Define an async function with `@mcp.tool()` + `@_guard`, returning `json.dumps(...)` (or a short
plain sentence for actions). FastMCP builds the schema from the typed signature + docstring. Read
the nearest existing `@mcp.tool` in the file and copy its shape - this is the source of truth, not
this guide.

## 3. Tests - `tests/unit/`

- `tests/unit/test_client.py` - mock the httpx transport; assert the method hits the right
  URL/method, sends the right query params/payload, and parses the response
- `tests/unit/test_mcp_tools.py` - mock the transport through the tool and assert the tool output

## Verify

```bash
mise run check   # ruff + yamls + actionlint
mise run test    # pytest
```

Commit style: `feat: <what the tool does>` (e.g. `feat: add upload_recipe_image tool`). Since
release-please drives versioning and the changelog from Conventional Commits on `main`, a `feat`
commit bumps the minor version on release.
