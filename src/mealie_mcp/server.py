"""Mealie MCP server built on FastMCP."""

import json
import logging
from functools import wraps
from typing import Any

import httpx2 as httpx
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

from . import __version__
from .client import MealieClient
from .config import config

config.configure_logging()
logger = logging.getLogger(__name__)


@lifespan
async def mealie_lifespan(server):
    """Close the shared Mealie client on shutdown."""
    global client
    yield None
    if client is not None:
        await client.close()
        client = None


mcp = FastMCP("mealie", lifespan=mealie_lifespan)

client: MealieClient | None = None


async def get_client() -> MealieClient:
    """Get the shared Mealie client, creating it on first use."""
    global client
    if client is None:
        client = MealieClient()
    return client


def _error_text(tool_name: str, exc: Exception) -> str:
    """Map an exception to a user-friendly error message."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        try:
            body = exc.response.json()
            detail = body.get("detail") or body.get("message") if isinstance(body, dict) else None
            detail = detail if isinstance(detail, str) else json.dumps(detail)[:300] if detail else None
        except Exception:
            detail = exc.response.text[:300] or None

        if status == 401:
            msg = "Authentication failed. Check MEALIE_API_TOKEN and MEALIE_BASE_URL."
        elif status == 403:
            msg = "Permission denied. The API token's user may not be allowed to do this."
        elif status == 404:
            msg = f"Not found. {detail or 'Check the slug or ID.'}"
        elif status == 422:
            msg = f"Validation error: {detail or 'the API rejected the request payload.'}"
        elif status == 429:
            msg = "Rate limited by Mealie. Retry in a few seconds."
        else:
            msg = f"API error ({status}): {detail or 'request failed.'}"
        return f"Error: {msg}"

    if isinstance(exc, httpx.TimeoutException):
        logger.error(f"Timeout executing tool {tool_name}: {exc}", exc_info=True)
        return "Error: Request to Mealie timed out. Check the instance and try again."

    logger.warning(f"Error executing tool {tool_name}: {exc}")
    return f"Error: {exc}"


def _guard(fn: Any) -> Any:
    """Wrap a tool so thrown errors become friendly text results."""

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return await fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - surface friendly message to model
            logger.error(f"Error executing tool {fn.__name__}: {e}", exc_info=True)
            return _error_text(fn.__name__, e)

    return wrapper


def _dump(data: Any) -> str:
    return json.dumps(data, indent=2)


# ==================== Recipes ====================


@mcp.tool()
@_guard
async def list_recipes(
    search: str | None = None,
    categories: list[str] | None = None,
    tags: list[str] | None = None,
    tools: list[str] | None = None,
    require_all_tags: bool = False,
    require_all_categories: bool = False,
    page: int = 1,
    per_page: int = 50,
) -> str:
    """Search and list recipes.

    Args:
        search: Free-text search across recipe name/description.
        categories: Category slugs to filter by (slugs, not display names).
        tags: Tag slugs to filter by.
        tools: Recipe tool slugs to filter by.
        require_all_tags: True = recipe must have ALL given tags (AND), False = any (OR).
        require_all_categories: True = recipe must have ALL given categories.
        page: Page number (1-based).
        per_page: Results per page.
    """
    c = await get_client()
    result = await c.list_recipes(
        search=search,
        categories=categories,
        tags=tags,
        tools=tools,
        require_all_tags=require_all_tags or None,
        require_all_categories=require_all_categories or None,
        page=page,
        per_page=per_page,
    )
    items = result.get("items", []) if isinstance(result, dict) else result
    if isinstance(items, list) and not items:
        return "No recipes found."
    return _dump(result)


@mcp.tool()
@_guard
async def get_recipe(slug: str, detail_level: str = "full") -> str:
    """Get a recipe by slug.

    Args:
        slug: Recipe slug (from list_recipes).
        detail_level: "full" for the whole recipe, "brief" for a summary.
    """
    c = await get_client()
    recipe = await c.get_recipe(slug)
    if detail_level == "brief" and isinstance(recipe, dict):
        summary = {
            k: recipe.get(k)
            for k in ("id", "slug", "name", "description", "recipeCategory", "tags", "rating", "totalTime")
        }
        return _dump(summary)
    return _dump(recipe)


@mcp.tool()
@_guard
async def create_recipe(name: str) -> str:
    """Create an empty recipe (fill it in later with patch_recipe).

    Args:
        name: Recipe name.
    """
    c = await get_client()
    return _dump(await c.create_recipe(name))


@mcp.tool()
@_guard
async def import_recipe_from_url(url: str, include_tags: bool = False) -> str:
    """Import a recipe by scraping a URL (Mealie's built-in scraper).

    Args:
        url: Source URL of the recipe.
        include_tags: Also import tags Mealie extracts from the page.
    """
    c = await get_client()
    return _dump(await c.import_recipe_from_url(url, include_tags))


@mcp.tool()
@_guard
async def update_recipe(slug: str, recipe: dict[str, Any]) -> str:
    """Replace a recipe in full (PUT). Prefer patch_recipe for partial edits.

    Args:
        slug: Recipe slug.
        recipe: Full recipe object. Fetch it with get_recipe first, change it, pass it back.
    """
    c = await get_client()
    return _dump(await c.update_recipe(slug, recipe))


@mcp.tool()
@_guard
async def patch_recipe(slug: str, recipe: dict[str, Any]) -> str:
    """Update selected recipe fields (PATCH). Only the given keys change.

    Args:
        slug: Recipe slug.
        recipe: Object with just the fields to change, e.g. {"name": "New name"}.
    """
    c = await get_client()
    return _dump(await c.patch_recipe(slug, recipe))


@mcp.tool()
@_guard
async def delete_recipe(slug: str) -> str:
    """Delete a recipe.

    Args:
        slug: Recipe slug.
    """
    c = await get_client()
    await c.delete_recipe(slug)
    return f"Deleted recipe {slug}."


@mcp.tool()
@_guard
async def duplicate_recipe(slug: str, name: str | None = None) -> str:
    """Duplicate a recipe.

    Args:
        slug: Recipe slug to copy.
        name: Optional name for the copy.
    """
    c = await get_client()
    return _dump(await c.duplicate_recipe(slug, name))


@mcp.tool()
@_guard
async def mark_recipe_last_made(slug: str, timestamp: str | None = None) -> str:
    """Record when a recipe was last made.

    Args:
        slug: Recipe slug.
        timestamp: ISO timestamp; defaults to now.
    """
    c = await get_client()
    return _dump(await c.mark_recipe_last_made(slug, timestamp))


@mcp.tool()
@_guard
async def set_recipe_image_from_url(slug: str, image_url: str) -> str:
    """Set a recipe's image by scraping it from a URL.

    Args:
        slug: Recipe slug.
        image_url: Direct URL of the image.
    """
    c = await get_client()
    return _dump(await c.set_recipe_image_from_url(slug, image_url))


# ==================== Meal plans ====================


@mcp.tool()
@_guard
async def list_mealplans(
    start_date: str | None = None,
    end_date: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> str:
    """List meal plan entries, optionally limited to a date range.

    Args:
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        page: Page number (1-based).
        per_page: Results per page.
    """
    c = await get_client()
    return _dump(await c.list_mealplans(start_date, end_date, page, per_page))


@mcp.tool()
@_guard
async def get_todays_mealplan() -> str:
    """Get today's planned meals."""
    c = await get_client()
    return _dump(await c.get_todays_mealplan())


@mcp.tool()
@_guard
async def create_mealplan(
    date: str,
    entry_type: str = "dinner",
    recipe_id: str | None = None,
    title: str | None = None,
) -> str:
    """Add a meal to the plan.

    Args:
        date: Date (YYYY-MM-DD).
        entry_type: One of breakfast, lunch, dinner, side.
        recipe_id: Recipe UUID (use list_recipes to find it).
        title: Free-text title when not referencing a recipe.
    """
    c = await get_client()
    return _dump(await c.create_mealplan(date, entry_type, recipe_id, title))


@mcp.tool()
@_guard
async def delete_mealplan(item_id: str) -> str:
    """Delete a meal plan entry.

    Args:
        item_id: Meal plan entry ID.
    """
    c = await get_client()
    await c.delete_mealplan(item_id)
    return f"Deleted meal plan entry {item_id}."


# ==================== Shopping lists ====================


@mcp.tool()
@_guard
async def list_shopping_lists(search: str | None = None, page: int = 1, per_page: int = 50) -> str:
    """List shopping lists.

    Args:
        search: Filter lists by name.
        page: Page number (1-based).
        per_page: Results per page.
    """
    c = await get_client()
    return _dump(await c.list_shopping_lists(search, page, per_page))


@mcp.tool()
@_guard
async def get_shopping_list(list_id: str) -> str:
    """Get a shopping list with its items.

    Args:
        list_id: Shopping list UUID.
    """
    c = await get_client()
    return _dump(await c.get_shopping_list(list_id))


@mcp.tool()
@_guard
async def create_shopping_list(name: str) -> str:
    """Create a shopping list.

    Args:
        name: List name.
    """
    c = await get_client()
    return _dump(await c.create_shopping_list(name))


@mcp.tool()
@_guard
async def delete_shopping_list(list_id: str) -> str:
    """Delete a shopping list.

    Args:
        list_id: Shopping list UUID.
    """
    c = await get_client()
    await c.delete_shopping_list(list_id)
    return f"Deleted shopping list {list_id}."


@mcp.tool()
@_guard
async def add_recipe_to_shopping_list(list_id: str, recipe_id: str, increment_quantity: float | None = None) -> str:
    """Add a recipe's ingredients to a shopping list.

    Args:
        list_id: Shopping list UUID.
        recipe_id: Recipe UUID.
        increment_quantity: Multiplier for the recipe amounts.
    """
    c = await get_client()
    return _dump(await c.add_recipe_to_shopping_list(list_id, recipe_id, increment_quantity))


@mcp.tool()
@_guard
async def remove_recipe_from_shopping_list(list_id: str, recipe_id: str) -> str:
    """Remove a recipe's ingredients from a shopping list.

    Args:
        list_id: Shopping list UUID.
        recipe_id: Recipe UUID.
    """
    c = await get_client()
    return _dump(await c.remove_recipe_from_shopping_list(list_id, recipe_id))


@mcp.tool()
@_guard
async def list_shopping_list_items(search: str | None = None, page: int = 1, per_page: int = 50) -> str:
    """List shopping list items across the household.

    Args:
        search: Filter items by note.
        page: Page number (1-based).
        per_page: Results per page.
    """
    c = await get_client()
    return _dump(await c.list_shopping_list_items(search, page, per_page))


@mcp.tool()
@_guard
async def create_shopping_list_item(
    shopping_list_id: str,
    note: str | None = None,
    quantity: float | None = None,
    unit_id: str | None = None,
    food_id: str | None = None,
    label_id: str | None = None,
    checked: bool = False,
) -> str:
    """Add an item to a shopping list.

    Args:
        shopping_list_id: Shopping list UUID.
        note: Item text (e.g. "milk").
        quantity: Amount.
        unit_id: Unit UUID (see list_units).
        food_id: Food UUID (see list_foods).
        label_id: Label UUID.
        checked: Whether the item starts checked off.
    """
    c = await get_client()
    return _dump(
        await c.create_shopping_list_item(shopping_list_id, note, quantity, unit_id, food_id, label_id, checked)
    )


@mcp.tool()
@_guard
async def update_shopping_list_item(
    item_id: str,
    checked: bool | None = None,
    note: str | None = None,
    quantity: float | None = None,
) -> str:
    """Update a shopping list item (check it off, rename it, change the amount).

    Args:
        item_id: Shopping list item UUID.
        checked: Set the checked state.
        note: New item text.
        quantity: New amount.
    """
    c = await get_client()
    changes = {k: v for k, v in {"checked": checked, "note": note, "quantity": quantity}.items() if v is not None}
    if not changes:
        return "No changes given."
    return _dump(await c.update_shopping_list_item(item_id, changes))


@mcp.tool()
@_guard
async def delete_shopping_list_item(item_id: str) -> str:
    """Delete a shopping list item.

    Args:
        item_id: Shopping list item UUID.
    """
    c = await get_client()
    await c.delete_shopping_list_item(item_id)
    return f"Deleted item {item_id}."


@mcp.tool()
@_guard
async def clear_checked_items(shopping_list_id: str) -> str:
    """Delete every checked-off item on a shopping list.

    Args:
        shopping_list_id: Shopping list UUID.
    """
    c = await get_client()
    # ponytail: one page of 200; a list with more items would leave some checked items behind.
    # Upgrade to paging through until exhausted if lists ever grow that large.
    result = await c.list_shopping_list_items(per_page=200)
    items = result.get("items", []) if isinstance(result, dict) else []
    ids = [i["id"] for i in items if i.get("shoppingListId") == shopping_list_id and i.get("checked")]
    if not ids:
        return "No checked items to clear."
    await c.delete_shopping_list_items(ids)
    return f"Cleared {len(ids)} checked item(s)."


# ==================== Organizers ====================


@mcp.tool()
@_guard
async def list_categories(search: str | None = None) -> str:
    """List recipe categories (returns slugs used for filtering)."""
    c = await get_client()
    return _dump(await c.list_categories(search))


@mcp.tool()
@_guard
async def create_category(name: str) -> str:
    """Create a recipe category."""
    c = await get_client()
    return _dump(await c.create_category(name))


@mcp.tool()
@_guard
async def delete_category(category_id: str) -> str:
    """Delete a recipe category by ID."""
    c = await get_client()
    await c.delete_category(category_id)
    return f"Deleted category {category_id}."


@mcp.tool()
@_guard
async def list_tags(search: str | None = None) -> str:
    """List recipe tags (returns slugs used for filtering)."""
    c = await get_client()
    return _dump(await c.list_tags(search))


@mcp.tool()
@_guard
async def create_tag(name: str) -> str:
    """Create a recipe tag."""
    c = await get_client()
    return _dump(await c.create_tag(name))


@mcp.tool()
@_guard
async def delete_tag(tag_id: str) -> str:
    """Delete a recipe tag by ID."""
    c = await get_client()
    await c.delete_tag(tag_id)
    return f"Deleted tag {tag_id}."


@mcp.tool()
@_guard
async def list_recipe_tools(search: str | None = None) -> str:
    """List recipe tools (equipment like oven, blender), by slug for filtering."""
    c = await get_client()
    return _dump(await c.list_recipe_tools(search))


@mcp.tool()
@_guard
async def create_recipe_tool(name: str) -> str:
    """Create a recipe tool."""
    c = await get_client()
    return _dump(await c.create_recipe_tool(name))


@mcp.tool()
@_guard
async def delete_recipe_tool(tool_id: str) -> str:
    """Delete a recipe tool by ID."""
    c = await get_client()
    await c.delete_recipe_tool(tool_id)
    return f"Deleted tool {tool_id}."


# ==================== Foods and units ====================


@mcp.tool()
@_guard
async def list_foods(search: str | None = None) -> str:
    """List foods (for structured shopping list items and recipe ingredients)."""
    c = await get_client()
    return _dump(await c.list_foods(search))


@mcp.tool()
@_guard
async def create_food(name: str, plural_name: str | None = None) -> str:
    """Create a food.

    Args:
        name: Singular name.
        plural_name: Plural form, e.g. "tomatoes".
    """
    c = await get_client()
    return _dump(await c.create_food(name, plural_name))


@mcp.tool()
@_guard
async def list_units(search: str | None = None) -> str:
    """List measurement units."""
    c = await get_client()
    return _dump(await c.list_units(search))


@mcp.tool()
@_guard
async def create_unit(name: str, plural_name: str | None = None, abbreviation: str | None = None) -> str:
    """Create a measurement unit.

    Args:
        name: Singular name, e.g. "gram".
        plural_name: Plural form, e.g. "grams".
        abbreviation: Short form, e.g. "g".
    """
    c = await get_client()
    return _dump(await c.create_unit(name, plural_name, abbreviation))


# ==================== Household and user ====================


@mcp.tool()
@_guard
async def get_household() -> str:
    """Get the current household: members, preferences, and settings."""
    c = await get_client()
    return _dump(await c.get_household())


@mcp.tool()
@_guard
async def get_current_user() -> str:
    """Get the authenticated Mealie user (useful to confirm the token works)."""
    c = await get_client()
    return _dump(await c.get_current_user())


def main() -> None:
    """Run the MCP server over stdio."""
    logger.info(f"Starting mealie-mcp {__version__}")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
