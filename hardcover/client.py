import asyncio
import copy
import hashlib
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


class HardcoverRateController:
    def __init__(self, limit: int, period_seconds: float):
        self.limit = max(1, int(limit))
        self.period_seconds = float(period_seconds)
        self.bucket = AsyncTokenBucket(self.limit, self.period_seconds)
        self.cooldown_until = 0.0
        self.cooldown_lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self.cooldown_lock:
                wait_for = self.cooldown_until - time.monotonic()
            if wait_for > 0:
                await asyncio.sleep(wait_for)
                continue

            await self.bucket.acquire()

            async with self.cooldown_lock:
                wait_for = self.cooldown_until - time.monotonic()
            if wait_for <= 0:
                return

    async def note_rate_limited(self, attempt: int, retry_after: str | None = None) -> None:
        delay_seconds = self._retry_delay_seconds(attempt, retry_after)
        async with self.cooldown_lock:
            self.cooldown_until = max(self.cooldown_until, time.monotonic() + delay_seconds)

    def _retry_delay_seconds(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None:
            try:
                parsed = float(str(retry_after).strip())
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None and parsed > 0:
                return parsed
        return min(15.0, 1.0 * (2 ** max(0, int(attempt))))


_HARDCOVER_RATE_CONTROLLERS: dict[str, HardcoverRateController] = {}


def get_hardcover_rate_controller(endpoint: str, authorization_header: str, limit: int) -> HardcoverRateController:
    scope = f"{str(endpoint or '').strip().lower()}:{hashlib.sha256(str(authorization_header or '').encode('utf-8')).hexdigest()}"
    controller = _HARDCOVER_RATE_CONTROLLERS.get(scope)
    if controller is None or controller.limit != max(1, int(limit)):
        controller = HardcoverRateController(limit, 60.0)
        _HARDCOVER_RATE_CONTROLLERS[scope] = controller
    return controller


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
              id
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
              id
              name
              slug
            }
          }
        }
      }
    }
    """

    SERIES_DETAILS_QUERY = """
    query SeriesDetails($id: Int!) {
      series(where: {id: {_eq: $id}}, limit: 1) {
        id
        name
        slug
        books_count
        author {
          name
        }
        book_series(
          distinct_on: position
          order_by: [{position: asc}, {book: {users_count: desc}}]
          where: {
            book: {canonical_id: {_is_null: true}}
            compilation: {_eq: false}
          }
        ) {
          position
          book {
            id
            slug
            title
            release_year
            image {
              url
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
        self.rate_limit_per_minute = max(1, int(rate_limit))
        self.rate_controller = get_hardcover_rate_controller(
            self.endpoint,
            self.authorization_header(),
            self.rate_limit_per_minute,
        )
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
            await self.rate_controller.acquire()
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
                await self.rate_controller.note_rate_limited(attempt, response.headers.get("Retry-After"))
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

    async def series_details(self, series_id: int) -> dict[str, Any] | None:
        try:
            normalized_id = int(series_id)
        except (TypeError, ValueError):
            return None
        if normalized_id <= 0:
            return None

        data = await self.graphql(
            self.SERIES_DETAILS_QUERY,
            {"id": normalized_id},
            cache_key=f"series:{normalized_id}",
        )
        series = data.get("series") or []
        if isinstance(series, list) and series:
            return series[0]
        return None
