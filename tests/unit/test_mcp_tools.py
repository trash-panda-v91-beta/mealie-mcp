"""Tests for the MCP server tools (FastMCP surface, bearer auth)."""

import json

import pytest
from pytest_httpx2 import HTTPXMock

import mealie_mcp.server as server

BASE = "https://mealie.example.com"

SAMPLE_RECIPE = {"id": "abc", "slug": "test-recipe", "name": "Test Recipe", "tags": []}
SAMPLE_LIST_ITEM = {
    "id": "i1",
    "shoppingListId": "l1",
    "note": "milk",
    "checked": True,
}


async def call_tool(name, arguments=None):
    result = await server.mcp.call_tool(name, arguments)
    return result.content


class TestToolList:
    @pytest.mark.asyncio
    async def test_tool_count(self):
        tools = await server.mcp.list_tools()
        names = {t.name for t in tools}
        assert len(tools) == 40
        assert {
            "list_recipes",
            "get_recipe",
            "import_recipe_from_url",
            "patch_recipe",
            "list_mealplans",
            "get_todays_mealplan",
            "create_mealplan",
            "create_shopping_list_item",
            "clear_checked_items",
            "list_categories",
            "list_tags",
            "list_foods",
            "list_units",
            "get_current_user",
        } <= names


class TestRecipeTools:
    @pytest.mark.asyncio
    async def test_list_recipes(self, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(
            url=f"{BASE}/api/recipes?page=1&perPage=50",
            json={"items": [SAMPLE_RECIPE], "pagination": {"total": 1}},
        )
        result = await call_tool("list_recipes", {})
        assert json.loads(result[0].text)["items"][0]["name"] == "Test Recipe"

    @pytest.mark.asyncio
    async def test_list_recipes_empty(self, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/recipes?page=1&perPage=50", json={"items": []})
        result = await call_tool("list_recipes", {})
        assert "No recipes found" in result[0].text

    @pytest.mark.asyncio
    async def test_get_recipe_brief(self, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/recipes/test-recipe", json=SAMPLE_RECIPE)
        result = await call_tool("get_recipe", {"slug": "test-recipe", "detail_level": "brief"})
        data = json.loads(result[0].text)
        assert data["name"] == "Test Recipe"
        assert "slug" in data

    @pytest.mark.asyncio
    async def test_delete_recipe(self, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/recipes/test-recipe", status_code=200, content=b"", method="DELETE")
        result = await call_tool("delete_recipe", {"slug": "test-recipe"})
        assert "Deleted recipe" in result[0].text

    @pytest.mark.asyncio
    async def test_unauthorized_maps_to_friendly_error(self, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/recipes/test-recipe", status_code=401, json={"detail": "nope"})
        result = await call_tool("get_recipe", {"slug": "test-recipe"})
        assert "Authentication failed" in result[0].text


class TestShoppingTools:
    @pytest.mark.asyncio
    async def test_clear_checked_items(self, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(
            url=f"{BASE}/api/households/shopping/items?perPage=200",
            json={"items": [SAMPLE_LIST_ITEM, {**SAMPLE_LIST_ITEM, "id": "i2", "checked": False}]},
        )
        httpx2_mock.add_response(
            url=f"{BASE}/api/households/shopping/items?ids=i1", status_code=200, content=b"", method="DELETE"
        )
        result = await call_tool("clear_checked_items", {"shopping_list_id": "l1"})
        assert "Cleared 1 checked item" in result[0].text

    @pytest.mark.asyncio
    async def test_clear_checked_items_none(self, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/households/shopping/items?perPage=200", json={"items": []})
        result = await call_tool("clear_checked_items", {"shopping_list_id": "l1"})
        assert "No checked items" in result[0].text

    @pytest.mark.asyncio
    async def test_update_item_rejects_noop(self):
        result = await call_tool("update_shopping_list_item", {"item_id": "i1"})
        assert "No changes" in result[0].text
