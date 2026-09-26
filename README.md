# mealie-mcp

Model Context Protocol (MCP) server for [Mealie](https://github.com/mealie-recipes/mealie).
Exposes a Mealie instance as MCP tools: recipes, meal plans, shopping lists and items, plus the
organizer/food/unit taxonomies. Bearer-token auth, token-bucket rate limiting, and connection
pooling. Built on FastMCP v4 and an async httpx client.

## Quick start

```bash
uv run mealie-mcp
```

Configure with environment variables:

| Variable | Default | Notes |
| --- | --- | --- |
| `MEALIE_BASE_URL` | - | required, e.g. `https://mealie.example.com` |
| `MEALIE_API_TOKEN` | - | required, Mealie user settings > API Tokens |
| `LOG_LEVEL` | `INFO` | log verbosity |
| `RATE_LIMIT_PER_SECOND` | `10` | outbound request rate |
| `RATE_LIMIT_BURST` | `10` | burst capacity |
| `ALLOW_INSECURE_HTTP` | `false` | allow `http://` base URLs (cluster-internal) |

Values can come from a `.env` file in the working directory.

## Container

```bash
docker run -i --rm \
  -e MEALIE_BASE_URL=https://mealie.example.com \
  -e MEALIE_API_TOKEN=*** \
  ghcr.io/trash-panda-v91-beta/mealie-mcp:latest
```

## Tools

- Recipes: `list_recipes`, `get_recipe`, `create_recipe`, `import_recipe_from_url`,
  `update_recipe`, `patch_recipe`, `delete_recipe`, `duplicate_recipe`,
  `mark_recipe_last_made`, `set_recipe_image_from_url`
- Meal plans: `list_mealplans`, `get_todays_mealplan`, `create_mealplan`, `delete_mealplan`
- Shopping lists: `list_shopping_lists`, `get_shopping_list`, `create_shopping_list`,
  `delete_shopping_list`, `add_recipe_to_shopping_list`, `remove_recipe_from_shopping_list`
- Shopping items: `list_shopping_list_items`, `create_shopping_list_item`,
  `update_shopping_list_item`, `delete_shopping_list_item`, `clear_checked_items`
- Organizers: `list_categories`, `create_category`, `delete_category`, `list_tags`, `create_tag`,
  `delete_tag`, `list_recipe_tools`, `create_recipe_tool`, `delete_recipe_tool`
- Foods and units: `list_foods`, `create_food`, `list_units`, `create_unit`
- Household: `get_household`, `get_current_user`

## Development

```bash
mise install     # toolchain: uv, ruff, hk, ...
mise run check   # hk: ruff, actionlint, yamllint, yamlfmt, pkl
mise run fix     # auto-fix the same
mise run test    # uv run pytest
```

Adding a tool: see `.agents/skills/add-tool/SKILL.md`. Releases are driven by release-please from
Conventional Commits on `main`.
