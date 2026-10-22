"""Fuzzy search and ranking for desktop applications.

The ranker rewards prefix and word-boundary matches, understands acronyms and
multi-word queries, and ignores diacritics. It is pure Python so the search
logic stays independent from the interface.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from orbit.core.desktop_entry import DesktopEntry

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class SearchResult:
    """An application plus the information the UI needs to present it."""

    entry: DesktopEntry
    score: float
    name_positions: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class _Field:
    text: str
    weight: float
    is_name: bool = False
    index_map: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class _Match:
    score: float
    positions: tuple[int, ...]


def normalize(text: str) -> str:
    """Case-fold and remove combining marks for accent-insensitive matching."""

    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(
        char for char in decomposed if not unicodedata.combining(char)
    ).casefold()


def _normalize_with_map(text: str) -> tuple[str, tuple[int, ...]]:
    """Normalize *text* while remembering where every output character came from."""

    pieces: list[str] = []
    index_map: list[int] = []

    for index, char in enumerate(text):
        decomposed = unicodedata.normalize("NFKD", char)
        folded = "".join(
            item for item in decomposed if not unicodedata.combining(item)
        ).casefold()
        for item in folded:
            pieces.append(item)
            index_map.append(index)

    return "".join(pieces), tuple(index_map)


def _is_boundary(text: str, index: int) -> bool:
    return index == 0 or not text[index - 1].isalnum()


def _match_token(token: str, text: str, *, allow_fuzzy: bool = True) -> _Match | None:
    """Score one token against one normalized field."""

    if not token or not text:
        return None

    token_length = len(token)

    if text == token:
        return _Match(1000.0, tuple(range(token_length)))

    if text.startswith(token):
        length_penalty = max(0, len(text) - token_length) * 0.5
        return _Match(max(600.0, 820.0 - length_penalty), tuple(range(token_length)))

    first_occurrence = text.find(token)
    if first_occurrence >= 0:
        first_boundary: int | None = None
        index = first_occurrence
        while index >= 0:
            if _is_boundary(text, index):
                first_boundary = index
                break
            index = text.find(token, index + 1)

        position = first_boundary if first_boundary is not None else first_occurrence
        base = 600.0 if first_boundary is not None else 430.0
        score = base - min(position, 60) * 1.1
        score -= max(0, len(text) - token_length) * 0.1
        return _Match(
            max(score, 180.0), tuple(range(position, position + token_length))
        )

    positions = _subsequence_positions(token, text)
    if positions is None or not allow_fuzzy:
        return None

    span = positions[-1] - positions[0] + 1
    gaps = max(0, span - token_length)
    boundary_bonus = sum(55.0 for position in positions if _is_boundary(text, position))
    consecutive_bonus = sum(
        18.0 for left, right in pairwise(positions) if right == left + 1
    )

    score = 120.0 + boundary_bonus + consecutive_bonus + token_length * 6.0
    score -= gaps * 4.0
    score -= positions[0] * 1.0
    return _Match(max(40.0, min(score, 380.0)), positions)


def _subsequence_positions(token: str, text: str) -> tuple[int, ...] | None:
    positions: list[int] = []
    cursor = 0

    for char in token:
        found = text.find(char, cursor)
        if found < 0:
            return None
        positions.append(found)
        cursor = found + 1

    return tuple(positions)


def _fields_for(entry: DesktopEntry) -> tuple[_Field, ...]:
    name, name_map = _normalize_with_map(entry.name)
    fields = [_Field(name, 1.0, True, name_map)]
    fields.extend(
        _Field(normalize(keyword), 0.6) for keyword in entry.keywords if keyword.strip()
    )
    fields.extend(
        (
            _Field(normalize(entry.generic_name), 0.5),
            _Field(normalize(entry.comment), 0.35),
        )
    )
    fields.extend(
        _Field(normalize(category), 0.25)
        for category in entry.categories
        if category.strip()
    )
    fields.append(_Field(normalize(Path(entry.desktop_id).stem), 0.15))
    return tuple(field for field in fields if field.text)


def _result_for(entry: DesktopEntry, query: str) -> SearchResult | None:
    tokens = [token for token in _WHITESPACE.split(query) if token]
    if not tokens:
        return SearchResult(entry, 0.0)

    fields = _fields_for(entry)
    total = 0.0
    name_positions: set[int] = set()

    for token in tokens:
        best_score = 0.0
        best_field: _Field | None = None
        best_match: _Match | None = None
        name_match = _match_token(token, fields[0].text, allow_fuzzy=True)

        for field in fields:
            # Two-letter queries should feel precise. Comments, categories and
            # other secondary metadata create noise at that length, so only
            # names and keywords participate.
            if len(token) <= 2 and field.weight < 0.6:
                continue

            match = _match_token(
                token,
                field.text,
                allow_fuzzy=field.is_name or field.weight >= 0.5,
            )
            if match is None:
                continue

            weighted = match.score * field.weight
            if weighted > best_score:
                best_score = weighted
                best_field = field
                best_match = match

        if best_field is None or best_match is None:
            return None

        total += best_score

        if name_match is not None:
            name_field = fields[0]
            name_positions.update(
                name_field.index_map[position]
                for position in name_match.positions
                if position < len(name_field.index_map)
            )
            # A name hit should stay ahead of an equally good keyword hit.
            total += max(120.0, name_match.score * 0.25)

    # Prefer shorter names when scores are close.
    total += max(0.0, 30.0 - len(entry.name)) * 0.4

    return SearchResult(
        entry=entry,
        score=total,
        name_positions=tuple(sorted(name_positions)),
    )


def search(
    entries: list[DesktopEntry] | tuple[DesktopEntry, ...],
    query: str,
    *,
    limit: int | None = None,
) -> list[SearchResult]:
    """Return entries matching *query*, best match first."""

    normalized_query = normalize(query).strip()

    if not normalized_query:
        results = [
            SearchResult(entry, 0.0)
            for entry in sorted(entries, key=lambda item: item.name.casefold())
        ]
        return results[:limit] if limit is not None else results

    results = []
    for entry in entries:
        result = _result_for(entry, normalized_query)
        if result is not None:
            results.append(result)

    results.sort(key=lambda result: (-result.score, result.entry.name.casefold()))

    # Drop only the faintest fuzzy matches; they add noise to short queries
    # without contributing useful alternatives at the top of the list.
    if results:
        floor = results[0].score * 0.1
        results = [result for result in results if result.score >= floor]

    return results[:limit] if limit is not None else results
