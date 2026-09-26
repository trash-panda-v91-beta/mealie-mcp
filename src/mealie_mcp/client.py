"""Async Mealie API client with token auth, rate limiting, and retry logic.

Authenticates with a Mealie API token sent as a bearer token and targets the
public REST API under /api. Covered surface: recipes, meal plans, shopping
lists and items, and the organizer/food/unit taxonomies.
"""

import asyncio
import json as json_lib
import logging
import random
import time
from datetime import UTC, datetime
from typing import Any

import httpx2 as httpx

from .config import config

logger = logging.getLogger(__name__)


class TokenBucket:
    """Token bucket rate limiter."""

    def __init__(self, rate: float, capacity: int):
        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last_update = time.time()
        self.lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1):
        async with self.lock:
            while True:
                now = time.time()
                elapsed = now - self.last_update
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_update = now
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return
                await asyncio.sleep((tokens - self.tokens) / self.rate)


def _compact(params: dict[str, Any]) -> dict[str, Any]:
    """Drop null params and comma-join list filters (Mealie's list-filter format)."""
    out: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        out[key] = ",".join(str(v) for v in value) if isinstance(value, (list, tuple)) else value
    return out


class MealieClient:
    """Async client for the Mealie REST API (bearer token auth)."""

    def __init__(
        self,
        base_url: str | None = None,
        api_token: str | None = None,
        rate_limit_per_second: float | None = None,
        rate_limit_burst: int | None = None,
    ):
        self.base_url = (base_url or config.mealie_base_url or "").rstrip("/")
        self.api_token = api_token or config.mealie_api_token or ""
        self.rate_limiter = TokenBucket(
            rate=rate_limit_per_second or config.rate_limit_per_second,
            capacity=rate_limit_burst or config.rate_limit_burst,
        )

        self.client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/json",
            },
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=50, keepalive_expiry=30.0),
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=2.0),
            verify=True,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self) -> None:
        """Close the HTTP client and release the connection pool."""
        if self.client:
            await self.client.aclose()

    async def _request(self, method: str, path: str, max_retries: int = 3, **kwargs: Any) -> Any:
        """Make a rate-limited request with retry. Returns parsed JSON or None for empty bodies."""
        url = f"{self.base_url}{path}"
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                await self.rate_limiter.acquire()
                logger.debug(f"Request {method} {url} (attempt {attempt + 1}/{max_retries})")
                response = await self.client.request(method, url, **kwargs)

                if response.status_code == 429:
                    wait_time = float(response.headers.get("Retry-After", "60"))
                    logger.warning(f"Rate limited, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()

                if not response.content:
                    return None

                try:
                    return response.json()
                except json_lib.JSONDecodeError:
                    # Mealie returns a bare string for some scrape failures; keep it.
                    return response.text

            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                if (
                    isinstance(e, httpx.HTTPStatusError)
                    and 400 <= e.response.status_code < 500
                    and e.response.status_code != 429
                ):
                    logger.error(f"Client error: {e.response.status_code} - {e.response.text}")
                    raise
                if attempt == max_retries - 1:
                    logger.error(f"Request failed after {max_retries} attempts: {e}")
                    raise
                delay = min(base_delay * (2**attempt), 60.0)
                await asyncio.sleep(delay * (1 + random.uniform(-0.25, 0.25)))

        raise RuntimeError(f"Failed after {max_retries} retries")

    # ==================== Recipes ====================

    async def list_recipes(
        self,
        search: str | None = None,
        categories: list[str] | None = None,
        tags: list[str] | None = None,
        tools: list[str] | None = None,
        require_all_tags: bool | None = None,
        require_all_categories: bool | None = None,
        require_all_tools: bool | None = None,
        page: int | None = None,
        per_page: int | None = None,
        order_by: str | None = None,
        order_direction: str | None = None,
    ) -> Any:
        """List/search recipes. Filters by category/tag/tool slugs, not display names."""
        params = _compact(
            {
                "search": search,
                "categories": categories,
                "tags": tags,
                "tools": tools,
                "requireAllTags": require_all_tags,
                "requireAllCategories": require_all_categories,
                "requireAllTools": require_all_tools,
                "page": page,
                "perPage": per_page,
                "orderBy": order_by,
                "orderDirection": order_direction,
            }
        )
        return await self._request("GET", "/api/recipes", params=params)

    async def get_recipe(self, slug: str) -> Any:
        """Get a recipe by slug."""
        return await self._request("GET", f"/api/recipes/{slug}")

    async def create_recipe(self, name: str) -> Any:
        """Create an empty recipe and return its slug."""
        return await self._request("POST", "/api/recipes", json={"name": name})

    async def import_recipe_from_url(self, url: str, include_tags: bool = False) -> Any:
        """Create a recipe by scraping a URL with Mealie's built-in scraper."""
        return await self._request("POST", "/api/recipes/create/url", json={"url": url, "includeTags": include_tags})

    async def update_recipe(self, slug: str, recipe_data: dict[str, Any]) -> Any:
        """Replace a recipe (PUT). recipe_data must be a full recipe payload."""
        return await self._request("PUT", f"/api/recipes/{slug}", json=recipe_data)

    async def patch_recipe(self, slug: str, recipe_data: dict[str, Any]) -> Any:
        """Partially update a recipe (PATCH); only the provided fields change."""
        return await self._request("PATCH", f"/api/recipes/{slug}", json=recipe_data)

    async def delete_recipe(self, slug: str) -> None:
        """Delete a recipe."""
        await self._request("DELETE", f"/api/recipes/{slug}")

    async def duplicate_recipe(self, slug: str, name: str | None = None) -> Any:
        """Duplicate a recipe, optionally under a new name."""
        payload = {"name": name} if name else {}
        return await self._request("POST", f"/api/recipes/{slug}/duplicate", json=payload)

    async def mark_recipe_last_made(self, slug: str, timestamp: str | None = None) -> Any:
        """Set a recipe's last-made timestamp (defaults to now)."""
        timestamp = timestamp or datetime.now(UTC).isoformat()
        return await self._request("PATCH", f"/api/recipes/{slug}/last-made", json={"timestamp": timestamp})

    async def set_recipe_image_from_url(self, slug: str, image_url: str) -> Any:
        """Scrape and set a recipe's image from a URL."""
        return await self._request("POST", f"/api/recipes/{slug}/image", json={"url": image_url})

    # ==================== Meal plans ====================

    async def list_mealplans(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
    ) -> Any:
        """List meal plan entries, optionally bounded by date (YYYY-MM-DD)."""
        params = _compact({"startDate": start_date, "endDate": end_date, "page": page, "perPage": per_page})
        return await self._request("GET", "/api/households/mealplans", params=params)

    async def get_todays_mealplan(self) -> Any:
        """Get today's meal plan entries."""
        return await self._request("GET", "/api/households/mealplans/today")

    async def create_mealplan(
        self,
        date: str,
        entry_type: str = "dinner",
        recipe_id: str | None = None,
        title: str | None = None,
    ) -> Any:
        """Create a meal plan entry for a date (YYYY-MM-DD)."""
        payload: dict[str, Any] = {"date": date, "entryType": entry_type}
        if recipe_id:
            payload["recipeId"] = recipe_id
        if title:
            payload["title"] = title
        return await self._request("POST", "/api/households/mealplans", json=payload)

    async def delete_mealplan(self, item_id: str) -> None:
        """Delete a meal plan entry."""
        await self._request("DELETE", f"/api/households/mealplans/{item_id}")

    # ==================== Shopping lists ====================

    async def list_shopping_lists(
        self, search: str | None = None, page: int | None = None, per_page: int | None = None
    ) -> Any:
        """List shopping lists for the current household."""
        params = _compact({"search": search, "page": page, "perPage": per_page})
        return await self._request("GET", "/api/households/shopping/lists", params=params)

    async def get_shopping_list(self, list_id: str) -> Any:
        """Get a shopping list by ID."""
        return await self._request("GET", f"/api/households/shopping/lists/{list_id}")

    async def create_shopping_list(self, name: str) -> Any:
        """Create a shopping list."""
        return await self._request("POST", "/api/households/shopping/lists", json={"name": name})

    async def delete_shopping_list(self, list_id: str) -> None:
        """Delete a shopping list."""
        await self._request("DELETE", f"/api/households/shopping/lists/{list_id}")

    async def add_recipe_to_shopping_list(
        self, list_id: str, recipe_id: str, increment_quantity: float | None = None
    ) -> Any:
        """Add a recipe's ingredients to a shopping list."""
        payload = {"recipeIncrementQuantity": increment_quantity} if increment_quantity is not None else {}
        return await self._request("POST", f"/api/households/shopping/lists/{list_id}/recipe/{recipe_id}", json=payload)

    async def remove_recipe_from_shopping_list(self, list_id: str, recipe_id: str) -> Any:
        """Remove a recipe's ingredients from a shopping list."""
        return await self._request("POST", f"/api/households/shopping/lists/{list_id}/recipe/{recipe_id}/delete")

    # ==================== Shopping list items ====================

    async def list_shopping_list_items(
        self, search: str | None = None, page: int | None = None, per_page: int | None = None
    ) -> Any:
        """List shopping list items across the household."""
        params = _compact({"search": search, "page": page, "perPage": per_page})
        return await self._request("GET", "/api/households/shopping/items", params=params)

    async def get_shopping_list_item(self, item_id: str) -> Any:
        """Get a shopping list item by ID."""
        return await self._request("GET", f"/api/households/shopping/items/{item_id}")

    async def create_shopping_list_item(
        self,
        shopping_list_id: str,
        note: str | None = None,
        quantity: float | None = None,
        unit_id: str | None = None,
        food_id: str | None = None,
        label_id: str | None = None,
        checked: bool = False,
    ) -> Any:
        """Create a shopping list item."""
        payload: dict[str, Any] = {"shoppingListId": shopping_list_id, "checked": checked}
        if note is not None:
            payload["note"] = note
        if quantity is not None:
            payload["quantity"] = quantity
        if unit_id:
            payload["unitId"] = unit_id
        if food_id:
            payload["foodId"] = food_id
        if label_id:
            payload["labelId"] = label_id
        return await self._request("POST", "/api/households/shopping/items", json=payload)

    async def update_shopping_list_item(self, item_id: str, item_data: dict[str, Any]) -> Any:
        """Update an item via fetch-merge-put, preserving the fields Mealie's PUT requires."""
        current = await self.get_shopping_list_item(item_id)
        merged = {**current, **item_data}
        return await self._request("PUT", f"/api/households/shopping/items/{item_id}", json=merged)

    async def delete_shopping_list_item(self, item_id: str) -> None:
        """Delete a shopping list item."""
        await self._request("DELETE", f"/api/households/shopping/items/{item_id}")

    async def delete_shopping_list_items(self, item_ids: list[str]) -> None:
        """Delete multiple items in one call (repeated `ids` query params)."""
        await self._request("DELETE", "/api/households/shopping/items", params={"ids": item_ids})

    # ==================== Organizers: categories, tags, tools ====================

    async def list_categories(
        self, search: str | None = None, page: int | None = None, per_page: int | None = None
    ) -> Any:
        params = _compact({"search": search, "page": page, "perPage": per_page})
        return await self._request("GET", "/api/organizers/categories", params=params)

    async def create_category(self, name: str) -> Any:
        return await self._request("POST", "/api/organizers/categories", json={"name": name})

    async def delete_category(self, category_id: str) -> None:
        await self._request("DELETE", f"/api/organizers/categories/{category_id}")

    async def list_tags(self, search: str | None = None, page: int | None = None, per_page: int | None = None) -> Any:
        params = _compact({"search": search, "page": page, "perPage": per_page})
        return await self._request("GET", "/api/organizers/tags", params=params)

    async def create_tag(self, name: str) -> Any:
        return await self._request("POST", "/api/organizers/tags", json={"name": name})

    async def delete_tag(self, tag_id: str) -> None:
        await self._request("DELETE", f"/api/organizers/tags/{tag_id}")

    async def list_recipe_tools(
        self, search: str | None = None, page: int | None = None, per_page: int | None = None
    ) -> Any:
        params = _compact({"search": search, "page": page, "perPage": per_page})
        return await self._request("GET", "/api/organizers/tools", params=params)

    async def create_recipe_tool(self, name: str) -> Any:
        return await self._request("POST", "/api/organizers/tools", json={"name": name})

    async def delete_recipe_tool(self, tool_id: str) -> None:
        await self._request("DELETE", f"/api/organizers/tools/{tool_id}")

    # ==================== Foods and units ====================

    async def list_foods(self, search: str | None = None, page: int | None = None, per_page: int | None = None) -> Any:
        params = _compact({"search": search, "page": page, "perPage": per_page})
        return await self._request("GET", "/api/foods", params=params)

    async def create_food(self, name: str, plural_name: str | None = None) -> Any:
        payload: dict[str, Any] = {"name": name}
        if plural_name:
            payload["pluralName"] = plural_name
        return await self._request("POST", "/api/foods", json=payload)

    async def list_units(self, search: str | None = None, page: int | None = None, per_page: int | None = None) -> Any:
        params = _compact({"search": search, "page": page, "perPage": per_page})
        return await self._request("GET", "/api/units", params=params)

    async def create_unit(self, name: str, plural_name: str | None = None, abbreviation: str | None = None) -> Any:
        payload: dict[str, Any] = {"name": name}
        if plural_name:
            payload["pluralName"] = plural_name
        if abbreviation:
            payload["abbreviation"] = abbreviation
        return await self._request("POST", "/api/units", json=payload)

    # ==================== Household and user ====================

    async def get_household(self) -> Any:
        """Get the current household (members, preferences)."""
        return await self._request("GET", "/api/households/self")

    async def get_current_user(self) -> Any:
        """Get the authenticated user."""
        return await self._request("GET", "/api/users/self")
