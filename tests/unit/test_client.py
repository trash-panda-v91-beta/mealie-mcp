"""Unit tests for the Mealie client (bearer auth, recipes, shopping lists, organizers)."""

import json

import httpx2 as httpx
import pytest
from pytest_httpx2 import HTTPXMock

from mealie_mcp.client import MealieClient

BASE = "https://mealie.example.com"

SAMPLE_RECIPE = {"id": "abc", "slug": "test-recipe", "name": "Test Recipe", "tags": []}
SAMPLE_COMMENT = {"id": "c1", "recipeId": "abc", "text": "tasty"}


@pytest.fixture
def client():
    """A client using the config defaults (base URL from conftest)."""
    return MealieClient()


class TestAuth:
    @pytest.mark.asyncio
    async def test_sends_bearer_token(self):
        c = MealieClient()
        assert c.client.headers["Authorization"] == "Bearer test-token"
        await c.close()


class TestRecipes:
    @pytest.mark.asyncio
    async def test_list_recipes_comma_joins_filters(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(
            url=f"{BASE}/api/recipes?search=soup&categories=breakfast%2Clunch",
            json={"items": [SAMPLE_RECIPE], "pagination": {"total": 1}},
        )
        result = await client.list_recipes(search="soup", categories=["breakfast", "lunch"])
        assert result["items"][0]["name"] == "Test Recipe"

    @pytest.mark.asyncio
    async def test_get_recipe(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/recipes/test-recipe", json=SAMPLE_RECIPE)
        assert (await client.get_recipe("test-recipe"))["slug"] == "test-recipe"

    @pytest.mark.asyncio
    async def test_create_recipe(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/recipes", json="new-slug", method="POST")
        assert await client.create_recipe("New Recipe") == "new-slug"

    @pytest.mark.asyncio
    async def test_delete_recipe_empty_body(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/recipes/test-recipe", status_code=200, content=b"", method="DELETE")
        assert await client.delete_recipe("test-recipe") is None

    @pytest.mark.asyncio
    async def test_mark_last_made_defaults_to_now(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/recipes/test-recipe/last-made", json=SAMPLE_RECIPE, method="PATCH")
        assert await client.mark_recipe_last_made("test-recipe") is not None
        request = httpx2_mock.get_requests()[0]
        assert "timestamp" in request.content.decode()


class TestShoppingLists:
    @pytest.mark.asyncio
    async def test_create_item_payload(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/households/shopping/items", json={"id": "i1"}, method="POST")
        await client.create_shopping_list_item("l1", note="milk", quantity=2)
        request = httpx2_mock.get_requests()[0]
        body = request.content.decode()
        assert '"shoppingListId":"l1"' in body
        assert '"quantity":2' in body

    @pytest.mark.asyncio
    async def test_update_item_merges_existing(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(
            url=f"{BASE}/api/households/shopping/items/i1", json={"id": "i1", "note": "milk", "checked": False}
        )
        httpx2_mock.add_response(
            url=f"{BASE}/api/households/shopping/items/i1",
            json={"id": "i1", "note": "milk", "checked": True},
            method="PUT",
        )
        await client.update_shopping_list_item("i1", {"checked": True})
        put = httpx2_mock.get_requests(method="PUT")[0]
        assert '"note":"milk"' in put.content.decode()

    @pytest.mark.asyncio
    async def test_bulk_delete_uses_repeated_ids(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(
            url=f"{BASE}/api/households/shopping/items?ids=a&ids=b", status_code=200, content=b"", method="DELETE"
        )
        await client.delete_shopping_list_items(["a", "b"])


class TestRecipeComments:
    @pytest.mark.asyncio
    async def test_list_comments_by_slug(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/recipes/test-recipe/comments", json=[SAMPLE_COMMENT])
        result = await client.list_recipe_comments("test-recipe")
        assert result[0]["text"] == "tasty"

    @pytest.mark.asyncio
    async def test_create_resolves_slug_to_recipe_id(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/recipes/test-recipe", json=SAMPLE_RECIPE)
        httpx2_mock.add_response(url=f"{BASE}/api/comments", json=SAMPLE_COMMENT, method="POST")
        assert (await client.create_recipe_comment("test-recipe", "tasty"))["id"] == "c1"
        assert json.loads(httpx2_mock.get_requests()[-1].content) == {"recipeId": "abc", "text": "tasty"}

    @pytest.mark.asyncio
    async def test_update_sends_id_and_text(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/comments/c1", json=SAMPLE_COMMENT, method="PUT")
        await client.update_recipe_comment("c1", "edited")
        assert json.loads(httpx2_mock.get_requests()[-1].content) == {"id": "c1", "text": "edited"}

    @pytest.mark.asyncio
    async def test_delete_comment_empty_body(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/comments/c1", status_code=200, content=b"", method="DELETE")
        assert await client.delete_recipe_comment("c1") is None


class TestOrganizers:
    @pytest.mark.asyncio
    async def test_list_categories(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(
            url=f"{BASE}/api/organizers/categories?search=dinner",
            json={"items": [{"id": "c1", "name": "Dinner", "slug": "dinner"}]},
        )
        result = await client.list_categories("dinner")
        assert result["items"][0]["slug"] == "dinner"

    @pytest.mark.asyncio
    async def test_create_tag(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/organizers/tags", json={"id": "t1", "name": "Quick"}, method="POST")
        assert (await client.create_tag("Quick"))["name"] == "Quick"

    @pytest.mark.asyncio
    async def test_validation_error_is_not_retried(self, client, httpx2_mock: HTTPXMock):
        httpx2_mock.add_response(url=f"{BASE}/api/foods", json={"detail": "bad"}, status_code=422, method="POST")
        with pytest.raises(httpx.HTTPStatusError):
            await client.create_food("")
        assert len(httpx2_mock.get_requests()) == 1
