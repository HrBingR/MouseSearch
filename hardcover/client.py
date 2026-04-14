import asyncio
import copy
import time
from typing import Any

import httpx


class HardcoverAPIError(Exception):
    pass


class AsyncTokenBucket:
    def __init__(self, limit: int, period_seconds: float):
        self.limit = max(1, int(limit))
        self.period_seconds = float(period_seconds)
        self.tokens = float(self.limit)
        self.updated_at = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self.lock:
                now = time.monotonic()
                elapsed = now - self.updated_at
                self.updated_at = now
                refill_rate = self.limit / self.period_seconds
                self.tokens = min(float(self.limit), self.tokens + elapsed * refill_rate)
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait_for = (1.0 - self.tokens) / refill_rate
            await asyncio.sleep(wait_for)


def normalize_search_results(results: Any) -> list[dict[str, Any]]:
    if isinstance(results, dict):
        for key in ("hits", "results", "documents"):
            nested = results.get(key)
            if isinstance(nested, list):
                results = nested
                break
        else:
            results = [results]

    if not isinstance(results, list):
        return []

    normalized = []
    for item in results:
        candidate = item
        if isinstance(item, dict):
            if isinstance(item.get("document"), dict):
                candidate = item["document"]
            elif isinstance(item.get("book"), dict):
                candidate = item["book"]
            elif isinstance(item.get("series"), dict):
                candidate = item["series"]
            elif isinstance(item.get("author"), dict):
                candidate = item["author"]

        if isinstance(candidate, dict):
            normalized.append(candidate)
    return normalized


class HardcoverClient:
    SEARCH_QUERY = """
    query HardcoverSearch($query: String!, $query_type: String!, $per_page: Int!, $page: Int!) {
      search(query: $query, query_type: $query_type, per_page: $per_page, page: $page) {
        ids
        results
        query
        query_type
        page
        per_page
      }
    }
    """

    EDITION_BY_ISBN_13_QUERY = """
    query EditionByISBN13($isbn: String!) {
      editions(where: {isbn_13: {_eq: $isbn}}, limit: 1) {
        id
        title
        isbn_10
        isbn_13
        release_date
        book {
          id
          title
          subtitle
          description
          slug
          author_names
          series_names
          rating
          ratings_count
          reviews_count
          users_read_count
          users_count
          release_date
          release_year
          pages
          compilation
          has_audiobook
          has_ebook
          genres
          moods
          image {
            url
          }
          featured_series {
            position
            series {
              name
              slug
            }
          }
        }
      }
    }
    """

    EDITION_BY_ISBN_10_QUERY = """
    query EditionByISBN10($isbn: String!) {
      editions(where: {isbn_10: {_eq: $isbn}}, limit: 1) {
        id
        title
        isbn_10
        isbn_13
        release_date
        book {
          id
          title
          subtitle
          description
          slug
          author_names
          series_names
          rating
          ratings_count
          reviews_count
          users_read_count
          users_count
          release_date
          release_year
          pages
          compilation
          has_audiobook
          has_ebook
          genres
          moods
          image {
            url
          }
          featured_series {
            position
            series {
              name
              slug
            }
          }
        }
      }
    }
    """

    def __init__(
        self,
        token: str,
        *,
        endpoint: str = "https://api.hardcover.app/v1/graphql",
        user_agent: str = "MouseSearch Hardcover Enrichment",
        timeout_seconds: float = 30.0,
        rate_limit: int = 60,
    ):
        self.token = token
        self.endpoint = endpoint
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.limiter = AsyncTokenBucket(rate_limit, 60.0)
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[str, Any] = {}

    def authorization_header(self) -> str:
        token = str(self.token or "").strip()
        if token.lower().startswith("bearer "):
            return token
        return f"Bearer {token}"

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    async def open(self) -> None:
        if self._client is not None:
            return
        headers = {
            "Authorization": self.authorization_header(),
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        self._client = httpx.AsyncClient(headers=headers, timeout=self.timeout_seconds)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def graphql(
        self,
        query: str,
        variables: dict[str, Any],
        *,
        cache_key: str | None = None,
        retry_5xx: int = 2,
    ) -> dict[str, Any]:
        if cache_key and cache_key in self._cache:
            return copy.deepcopy(self._cache[cache_key])

        await self.open()
        assert self._client is not None

        retry_429 = 3
        attempt = 0
        while True:
            await self.limiter.acquire()
            try:
                response = await self._client.post(
                    self.endpoint,
                    json={"query": query, "variables": variables},
                )
            except httpx.TimeoutException as exc:
                raise HardcoverAPIError(f"timeout: {exc}") from exc
            except httpx.RequestError as exc:
                raise HardcoverAPIError(f"request_error: {exc}") from exc

            if response.status_code == 429 and attempt < retry_429:
                await asyncio.sleep(min(8.0, 0.75 * (2 ** attempt)))
                attempt += 1
                continue

            if 500 <= response.status_code <= 599 and attempt < retry_5xx:
                await asyncio.sleep(min(4.0, 0.5 * (2 ** attempt)))
                attempt += 1
                continue

            if response.status_code >= 400:
                raise HardcoverAPIError(f"http_{response.status_code}")

            payload = response.json()
            if payload.get("errors"):
                first = payload["errors"][0]
                message = first.get("message") if isinstance(first, dict) else str(first)
                raise HardcoverAPIError(f"graphql_error: {message}")

            data = payload.get("data") or {}
            if cache_key:
                self._cache[cache_key] = copy.deepcopy(data)
            return data

    async def search(self, query: str, query_type: str = "Book", per_page: int = 5) -> list[dict[str, Any]]:
        normalized_type = str(query_type or "Book").strip().title()
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return []

        data = await self.graphql(
            self.SEARCH_QUERY,
            {
                "query": normalized_query,
                "query_type": normalized_type,
                "per_page": int(per_page),
                "page": 1,
            },
            cache_key=f"search:{normalized_type.lower()}:{normalized_query.lower()}:{int(per_page)}",
        )
        search_data = data.get("search") or {}
        return normalize_search_results(search_data.get("results") or [])

    async def edition_by_isbn(self, isbn: str) -> dict[str, Any] | None:
        isbn = str(isbn or "").strip().upper()
        if not isbn:
            return None
        query = self.EDITION_BY_ISBN_13_QUERY if len(isbn) == 13 else self.EDITION_BY_ISBN_10_QUERY
        data = await self.graphql(
            query,
            {"isbn": isbn},
            cache_key=f"edition:isbn:{isbn}",
        )
        editions = data.get("editions") or []
        if isinstance(editions, list) and editions:
            return editions[0]
        return None
