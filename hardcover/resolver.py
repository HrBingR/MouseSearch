import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .client import HardcoverAPIError, HardcoverClient
from .normalization import (
    clean_title,
    detect_author_name,
    detect_series_names,
    extract_isbns,
    mam_original_metadata,
)
from .validator import pick_valid_candidate


@dataclass
class HardcoverEnrichmentConfig:
    match_threshold: float = 78.0
    concurrency: int = 6
    per_page: int = 5


def _listify(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [str(v) for v in value.values() if v]
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v]
    return [str(value)]


def _extract_image_url(image: Any) -> str:
    if not image:
        return ""
    if isinstance(image, str):
        return image
    if isinstance(image, dict):
        for key in ("url", "image_url", "large", "medium", "small", "original"):
            value = image.get(key)
            if isinstance(value, str) and value:
                return value
        for value in image.values():
            if isinstance(value, str) and value.startswith("http"):
                return value
    if isinstance(image, list):
        for item in image:
            value = _extract_image_url(item)
            if value:
                return value
    return ""


def _release_year(candidate: dict[str, Any]) -> int | None:
    raw = candidate.get("release_year") or candidate.get("release_date_i") or candidate.get("release_date")
    if raw is None:
        return None
    text = str(raw)
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def metadata_from_search_candidate(candidate: dict[str, Any], query_type: str) -> dict[str, Any]:
    is_book = query_type.lower() == "book"
    is_series = query_type.lower() == "series"
    is_author = query_type.lower() == "author"
    title = candidate.get("title") if is_book else candidate.get("name")
    authors = _listify(candidate.get("author_names"))
    if not authors and candidate.get("author_name"):
        authors = [str(candidate.get("author_name"))]
    url_path = "books"
    if is_series:
        url_path = "series"
    elif is_author:
        url_path = "authors"

    return {
        "title": title or "",
        "authors": authors,
        "cover_image": _extract_image_url(candidate.get("image")),
        "rating": candidate.get("rating"),
        "release_year": _release_year(candidate),
        "slug": candidate.get("slug") or "",
        "book_id": candidate.get("id") if is_book else None,
        "series_names": _listify(candidate.get("series_names")) if is_book else ([title] if is_series and title else []),
        "featured_series": candidate.get("featured_series") or candidate.get("featured_book_series"),
        "compilation": bool(candidate.get("compilation")) if is_book else False,
        "object_type": candidate.get("object_type") or query_type,
        "url_path": url_path,
    }


def metadata_from_edition(edition: dict[str, Any], original: dict[str, Any] | None = None) -> dict[str, Any]:
    book = edition.get("book") or {}
    original = original or {}
    authors = _listify(book.get("author_names"))
    if not authors and original.get("author_info"):
        authors = [name.strip() for name in str(original.get("author_info")).split(",") if name.strip()]
    series_names = _listify(book.get("series_names"))
    if not series_names and original.get("series_info"):
        series_names = [name.strip() for name in str(original.get("series_info")).split(",") if name.strip()]
    return {
        "title": book.get("title") or edition.get("title") or "",
        "authors": authors,
        "cover_image": _extract_image_url(book.get("image")),
        "rating": book.get("rating"),
        "release_year": _release_year(book) or _release_year(edition),
        "slug": book.get("slug") or "",
        "book_id": book.get("id"),
        "series_names": series_names,
        "featured_series": book.get("featured_series") or book.get("featured_book_series"),
        "compilation": bool(book.get("compilation")),
        "object_type": "Book",
        "url_path": "books",
    }


class HardcoverResolver:
    def __init__(self, client: HardcoverClient, config: HardcoverEnrichmentConfig):
        self.client = client
        self.config = config

    def unresolved(self, result: dict[str, Any], cleaned_query: str, reason: str, path: str = "unresolved") -> dict[str, Any]:
        return {
            "original_mam": mam_original_metadata(result),
            "hardcover": None,
            "match_score": 0.0,
            "query_path": path,
            "failure_reason": reason,
            "cleaned_query": cleaned_query,
        }

    async def enrich_result(self, result: dict[str, Any]) -> dict[str, Any]:
        cleaned_query = clean_title(result.get("title"))
        original = mam_original_metadata(result)
        author_name = detect_author_name(result)
        series_names = detect_series_names(result)

        try:
            for isbn in extract_isbns(result):
                edition = await self.client.edition_by_isbn(isbn)
                if edition:
                    return {
                        "original_mam": original,
                        "hardcover": metadata_from_edition(edition, original),
                        "match_score": 100.0,
                        "query_path": "ISBN",
                        "failure_reason": "",
                        "cleaned_query": cleaned_query,
                    }

            if not cleaned_query:
                return self.unresolved(result, cleaned_query, "missing_clean_title")

            book_candidates = await self.client.search(cleaned_query, "Book", self.config.per_page)
            candidate, score, _ = pick_valid_candidate(
                cleaned_query,
                book_candidates,
                self.config.match_threshold,
                author_name=author_name,
                series_names=series_names,
            )
            if candidate:
                return {
                    "original_mam": original,
                    "hardcover": metadata_from_search_candidate(candidate, "Book"),
                    "match_score": score,
                    "query_path": "book",
                    "failure_reason": "",
                    "cleaned_query": cleaned_query,
                }

            best_score = score
            series_queries = [cleaned_query] + [
                name for name in series_names
                if name.lower() != cleaned_query.lower()
            ]
            for series_query in series_queries:
                series_candidates = await self.client.search(series_query, "Series", self.config.per_page)
                candidate, score, _ = pick_valid_candidate(
                    series_query,
                    series_candidates,
                    self.config.match_threshold,
                    author_name=author_name,
                    series_names=series_names,
                )
                if candidate:
                    return {
                        "original_mam": original,
                        "hardcover": metadata_from_search_candidate(candidate, "Series"),
                        "match_score": score,
                        "query_path": "series",
                        "failure_reason": "",
                        "cleaned_query": cleaned_query,
                    }
                best_score = max(best_score, score)

            if author_name:
                author_candidates = await self.client.search(author_name, "Author", self.config.per_page)
                candidate, score, _ = pick_valid_candidate(
                    author_name,
                    author_candidates,
                    self.config.match_threshold,
                    author_name=author_name,
                    series_names=series_names,
                )
                if candidate:
                    metadata = metadata_from_search_candidate(candidate, "Author")
                    metadata["authors"] = [metadata.get("title") or author_name]
                    return {
                        "original_mam": original,
                        "hardcover": metadata,
                        "match_score": score,
                        "query_path": "author",
                        "failure_reason": "",
                        "cleaned_query": cleaned_query,
                    }
                best_score = max(best_score, score)

            failure = "low_confidence" if best_score else "no_match"
            unresolved = self.unresolved(result, cleaned_query, failure)
            unresolved["match_score"] = best_score
            return unresolved
        except HardcoverAPIError as exc:
            return self.unresolved(result, cleaned_query, str(exc), "failed")
        except Exception as exc:
            return self.unresolved(result, cleaned_query, f"unexpected_error: {exc}", "failed")


class HardcoverBatchRunner:
    def __init__(self, resolver: HardcoverResolver, concurrency: int):
        self.resolver = resolver
        self.concurrency = max(1, int(concurrency))

    async def run(
        self,
        results: list[dict[str, Any]],
        on_result: Callable[[int, dict[str, Any], dict[str, Any]], Awaitable[None]],
    ) -> None:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def worker(index: int, result: dict[str, Any]) -> None:
            async with semaphore:
                enrichment = await self.resolver.enrich_result(result)
                await on_result(index, result, enrichment)

        tasks = [asyncio.create_task(worker(index, result)) for index, result in enumerate(results)]
        await asyncio.gather(*tasks)
