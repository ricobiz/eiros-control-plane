from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from runtime.rental_agent.browser import BrowserWorker, discover_adapter_with_browser
from runtime.rental_agent.config import DEFAULT_SEARCH_PROFILE
from runtime.rental_agent.db import RentalDatabase
from runtime.rental_agent.models import LeadInput
from runtime.rental_agent.normalize import normalize_listing
from runtime.rental_agent.ranking import rank_listing
from runtime.rental_agent.scout.base import AdapterResult
from runtime.rental_agent.scout.batdongsan import BatdongsanAdapter
from runtime.rental_agent.scout.common import fetch_listing, make_client
from runtime.rental_agent.scout.nhatot import NhaTotAdapter
from runtime.rental_agent.scout.search_index import PublicWebSearchAdapter


class ScoutService:
    def __init__(
        self,
        database: RentalDatabase,
        *,
        adapters: Iterable[Any] | None = None,
        browser_worker: BrowserWorker | None = None,
    ) -> None:
        self.database = database
        self.adapters = tuple(adapters) if adapters is not None else (BatdongsanAdapter(), NhaTotAdapter(), PublicWebSearchAdapter())
        self.browser_worker = browser_worker

    def run(self, *, sources: tuple[str, ...] | None = None, limit_per_source: int = 10) -> dict[str, Any]:
        bounded = max(1, min(int(limit_per_source), 30))
        selected = [adapter for adapter in self.adapters if not sources or adapter.name in set(sources)]
        run_id = self.database.begin_search_run({
            "profile": DEFAULT_SEARCH_PROFILE,
            "sources": [adapter.name for adapter in selected],
            "limit_per_source": bounded,
        })
        source_summaries: list[dict[str, Any]] = []
        property_ids: set[str] = set()
        discovered_count = 0
        merged_count = 0
        error_count = 0
        needs_browser_sources: list[str] = []
        needs_user_action_sources: list[str] = []

        for adapter in selected:
            try:
                result: AdapterResult = adapter.discover(limit=bounded)
            except Exception as exc:
                result = AdapterResult(
                    source=adapter.name,
                    status="source_error",
                    listings=(),
                    errors=(f"{type(exc).__name__}: {exc}",),
                )
            if result.status == "needs_browser" and self.browser_worker is not None:
                browser_result = discover_adapter_with_browser(adapter, self.browser_worker, limit=bounded)
                if browser_result.status == "ok" or browser_result.listings:
                    result = browser_result
                elif browser_result.status == "needs_user_action":
                    result = browser_result
            if result.status == "needs_browser":
                needs_browser_sources.append(result.source)
            if result.status == "needs_user_action":
                needs_user_action_sources.append(result.source)
            if result.status != "ok":
                error_count += max(1, len(result.errors))
            source_summaries.append({
                "source": result.source,
                "status": result.status,
                "count": len(result.listings),
                "errors": list(result.errors),
            })
            discovered_count += len(result.listings)
            for listing in result.listings:
                item = normalize_listing(listing.text, title=listing.title)
                fit = rank_listing(item, DEFAULT_SEARCH_PROFILE)
                upsert = self.database.upsert_normalized_source(
                    LeadInput(
                        source_kind=f"scout:{listing.source}",
                        source_value=listing.url,
                        source_url=listing.url,
                        context={"search_run_id": run_id, "source": listing.source},
                    ),
                    item,
                    fit,
                )
                property_ids.add(upsert.property.property_id)
                if upsert.merged:
                    merged_count += 1

        canonical = [record for record in self.database.list_properties(limit=500) if record.property_id in property_ids]
        qualified_count = sum(record.status == "qualified" for record in canonical)
        rejected_count = sum(record.status == "rejected" for record in canonical)
        non_ok = [item for item in source_summaries if item["status"] != "ok"]
        if property_ids and non_ok:
            status = "partial"
        elif property_ids or (source_summaries and not non_ok):
            status = "ok"
        elif non_ok:
            status = str(non_ok[0]["status"])
        else:
            status = "source_error"
            error_count += 1

        self.database.finish_search_run(
            run_id,
            status=status,
            result_count=len(property_ids),
            error_count=error_count,
        )
        return {
            "run_id": run_id,
            "status": status,
            "discovered_count": discovered_count,
            "canonical_count": len(property_ids),
            "merged_count": merged_count,
            "qualified_count": qualified_count,
            "rejected_count": rejected_count,
            "needs_browser_sources": needs_browser_sources,
            "needs_user_action_sources": needs_user_action_sources,
            "sources": source_summaries,
            "property_ids": sorted(property_ids),
        }

    def refresh_property(self, property_id: str) -> dict[str, Any]:
        record = self.database.get_property(property_id)
        if record is None:
            return {"found": False, "property_id": property_id, "status": "not_found"}
        sources = self.database.list_sources(property_id)
        refreshable = [row for row in sources if str(row.get("source_url") or "").startswith(("http://", "https://"))]
        if not refreshable:
            return {"found": True, "property_id": property_id, "status": "no_refreshable_sources", "refreshed_count": 0}
        client = make_client()
        refreshed = 0
        errors: list[str] = []
        try:
            for row in refreshable[:10]:
                url = str(row["source_url"])
                status, listing, error = fetch_listing(client, str(row["source_kind"]), url)
                if listing is None:
                    if error:
                        errors.append(error)
                    continue
                item = normalize_listing(listing.text, title=listing.title)
                fit = rank_listing(item, DEFAULT_SEARCH_PROFILE)
                self.database.upsert_normalized_source(
                    LeadInput(
                        source_kind=str(row["source_kind"]),
                        source_value=str(row["source_value"]),
                        source_url=url,
                        context={"refresh": True, "fetch_status": status},
                    ),
                    item,
                    fit,
                )
                refreshed += 1
        finally:
            client.close()
        updated = self.database.get_property(property_id)
        return {
            "found": True,
            "property_id": property_id,
            "status": "ok" if refreshed else "source_error",
            "refreshed_count": refreshed,
            "errors": errors,
            "property": asdict(updated) if updated else None,
        }
