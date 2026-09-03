"""V3 C-2 — production observation capabilities for the dialog agent's tools.

The agent's tools declare four observation capabilities (search_place /
get_route / check_opening_hours / retrieve_guide_knowledge); this module
builds their callables from the same provider stack the rest of the service
uses, selected by ``PROVIDER_MODE``.

Discipline:

- every adapter returns JSON-able dicts (they become ToolObservation.data);
- adapters fail closed — a missing configuration keeps the capability
  unwired (``None``) instead of inventing data;
- knowledge retrieval is city-scoped by the confirmed destination slot;
  without a destination the observation is unknown rather than guessed.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from trip_agent.providers.settings import resolve_provider_mode


@dataclass(frozen=True, slots=True)
class ObservationCapabilities:
    """The four observation callables (None = capability not configured)."""

    place_search: Callable[..., Any] | None = None
    route: Callable[..., Any] | None = None
    opening_hours: Callable[..., Any] | None = None
    knowledge: Callable[..., Any] | None = None


_CLIENT: Any = None


def _shared_client() -> Any:
    """One lazily-created HTTP client for the worker process lifetime."""
    global _CLIENT
    if _CLIENT is None:
        import httpx

        _CLIENT = httpx.AsyncClient(timeout=15.0)
    return _CLIENT


def _mode() -> str:
    """Current provider mode as a string (tools compare against DEMO_ONLY).

    Single-source resolution lives in ``providers.settings``; this shim
    keeps the existing ``str`` contract for the two call sites.
    """
    return resolve_provider_mode().value


def _map_provider() -> Any:
    if _mode() == "DEMO_ONLY":
        from trip_agent.providers.map import DemoMapProvider

        return DemoMapProvider()
    from trip_agent.providers.map import AmapMapProvider

    return AmapMapProvider(
        api_key=(os.getenv("AMAP_WEB_SERVICE_KEY") or "").strip(),
        http_client=_shared_client(),
        cache=None,
    )


def _route_provider() -> Any:
    if _mode() == "DEMO_ONLY":
        from trip_agent.providers._demo_route import DemoRouteProvider

        return DemoRouteProvider()
    from trip_agent.providers.route import AmapRouteProvider

    return AmapRouteProvider(
        api_key=(os.getenv("AMAP_WEB_SERVICE_KEY") or "").strip(),
        http_client=_shared_client(),
        cache=None,
    )


def _place_search_adapter(provider: Any) -> Callable[..., Any]:
    from trip_agent.planning.poi_quality import place_search_selectable
    from trip_agent.providers.map import PoiSearchRequest, ProviderFailure

    async def search(*, keyword: str, city: str | None = None) -> dict[str, Any]:
        result = await provider.search_pois(
            PoiSearchRequest(city=city or "全国", keyword=keyword, limit=5)
        )
        if isinstance(result, ProviderFailure):
            return {
                "error": result.error_code,
                "message": getattr(result, "safe_message", "") or result.error_code,
            }
        places = result.data
        if result.provider == "AMAP":
            # Same selection rule as the places search endpoint: never offer
            # station gates/metro/parking or geo hot-spots as "places".
            places = tuple(poi for poi in places if place_search_selectable(poi))
        return {
            "places": [
                {
                    "name": poi.name,
                    "address": poi.address,
                    "type": poi.type_name,
                    "district": poi.district,
                    "longitude": float(poi.coordinates.longitude),
                    "latitude": float(poi.coordinates.latitude),
                }
                for poi in places
            ]
        }

    return search


def _route_adapter(map_provider: Any, route_provider: Any) -> Callable[..., Any]:
    from trip_agent.providers.map import PoiSearchRequest, ProviderFailure
    from trip_agent.providers.route import RouteRequest

    async def geocode(name: str, city: str | None) -> Any:
        result = await map_provider.search_pois(
            PoiSearchRequest(city=city or "全国", keyword=name, limit=1)
        )
        if isinstance(result, ProviderFailure) or not result.data:
            return None
        return result.data[0].coordinates

    async def route(
        *,
        origin: str,
        destination: str,
        mode: str = "TRANSIT",
        city: str | None = None,
    ) -> dict[str, Any]:
        origin_poi = await geocode(origin, city)
        destination_poi = await geocode(destination, city)
        if origin_poi is None or destination_poi is None:
            return {
                "error": "GEOCODE_FAILED",
                "origin": origin,
                "destination": destination,
            }
        plan = await route_provider.get_route(
            RouteRequest(
                origin=origin_poi,
                destination=destination_poi,
                departure_at=datetime.now(UTC),
                mode=mode,
                city=city,
            )
        )
        if isinstance(plan, ProviderFailure):
            return {"error": plan.error_code}
        data = plan.data
        return {
            "mode": data.mode,
            "distance_meters": data.distance_meters,
            "duration_seconds": data.duration_seconds,
            "estimated_cost": (
                float(data.estimated_cost) if data.estimated_cost is not None else None
            ),
        }

    return route


def _knowledge_stack() -> tuple[Callable[[str], Any], Any] | None:
    """(embed_query, repository) for the knowledge base, or None when the
    knowledge database/embedding is not configured."""
    try:
        from trip_agent.acquisition.cli import AcquisitionSettings

        database_url = AcquisitionSettings().database_url()
    except Exception:  # noqa: BLE001 - configuration probing must not raise
        return None
    if not database_url:
        return None
    try:
        # Deferred: keeps this probe import-free until the database is known.
        from trip_agent.retrieval.repository import PsycopgKnowledgeRepository
        from trip_agent.worker.runtime import (
            WorkerSettings,
            _configured_embedding_provider,
        )

        embedding = _configured_embedding_provider(WorkerSettings())
        repository = PsycopgKnowledgeRepository(database_url)
    except Exception:  # noqa: BLE001 - missing keys/schema degrade to unwired
        return None

    async def embed_query(text: str) -> Any:
        vectors = await embedding.embed_texts((text,))
        return vectors[0]

    return embed_query, repository


def _knowledge_adapter(
    embed_query: Callable[[str], Any], repository: Any
) -> Callable[..., Any]:
    from trip_agent.retrieval.repository import KnowledgeSearchRequest

    async def knowledge(
        *, query: str, city: str | None = None, limit: int = 5
    ) -> dict[str, Any]:
        if not city:
            return {
                "citations": [],
                "note": "destination unknown — knowledge is city-scoped",
            }
        vector = await embed_query(query)
        citations = await repository.search(
            KnowledgeSearchRequest(city=city, embedding=vector, limit=int(limit))
        )
        return {
            "citations": [
                {
                    "title": citation.title,
                    "content": citation.content,
                    "source_name": citation.source_name,
                    "source_url": citation.source_url,
                    "similarity": citation.similarity,
                }
                for citation in citations
            ]
        }

    return knowledge


def _opening_hours_adapter(knowledge: Callable[..., Any]) -> Callable[..., Any]:
    async def opening_hours(
        *, place: str, city: str | None = None, date: str | None = None
    ) -> dict[str, Any] | None:
        del date  # the knowledge base is not date-parameterised today
        result = await knowledge(
            query=f"{place} 营业时间 开放时间", city=city, limit=3
        )
        citations = result.get("citations") or []
        if not citations:
            return None
        return {"place": place, "sources": citations}

    return opening_hours


def build_observation_capabilities() -> ObservationCapabilities:
    """Build the four observation callables from environment configuration.

    Degrades per capability: a missing knowledge database leaves knowledge
    and opening_hours unwired while place_search/route stay available.
    """
    map_provider = _map_provider()
    route_provider = _route_provider()
    place_search = _place_search_adapter(map_provider)
    route = _route_adapter(map_provider, route_provider)

    knowledge: Callable[..., Any] | None = None
    stack = _knowledge_stack()
    if stack is not None:
        embed_query, repository = stack
        knowledge = _knowledge_adapter(embed_query, repository)
    opening_hours = _opening_hours_adapter(knowledge) if knowledge is not None else None

    return ObservationCapabilities(
        place_search=place_search,
        route=route,
        opening_hours=opening_hours,
        knowledge=knowledge,
    )
