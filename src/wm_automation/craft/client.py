"""Thin wrapper around the Craft multi-document connection API. Generic
transport only - no knowledge of which collection/properties the job
tracker uses (see tracker.py for that, still pending schema confirmation).

Docs: https://developer.craft.do. Rate limits: 50 req/10s per IP, 100
req/60s per space, 20k blocks/60s per space - a poll every few minutes is
nowhere near these, so no backoff logic is needed yet.
"""

from __future__ import annotations

from typing import Any

import httpx


class CraftClient:
    def __init__(self, base_url: str, token: str):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

    async def __aenter__(self) -> "CraftClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self._client.aclose()

    async def list_documents(self, *, fetch_metadata: bool = False) -> list[dict]:
        resp = await self._client.get("/documents", params={"fetchMetadata": fetch_metadata})
        resp.raise_for_status()
        return resp.json()["items"]

    async def list_collections(self, document_ids: list[str] | None = None) -> list[dict]:
        params = {"documentIds": document_ids} if document_ids else {}
        resp = await self._client.get("/collections", params=params)
        resp.raise_for_status()
        return resp.json()["items"]

    async def get_collection_schema(self, collection_id: str) -> dict:
        resp = await self._client.get(f"/collections/{collection_id}/schema", params={"format": "schema"})
        resp.raise_for_status()
        return resp.json()

    async def get_collection_items(self, collection_id: str, *, max_depth: int = 0) -> list[dict]:
        resp = await self._client.get(
            f"/collections/{collection_id}/items", params={"maxDepth": max_depth}
        )
        resp.raise_for_status()
        return resp.json()["items"]

    async def update_collection_items(self, collection_id: str, items_to_update: list[dict]) -> list[dict]:
        resp = await self._client.put(
            f"/collections/{collection_id}/items",
            json={"itemsToUpdate": items_to_update},
        )
        resp.raise_for_status()
        return resp.json()["items"]

    async def get_blocks(self, block_id: str, *, max_depth: int = -1, fetch_metadata: bool = False) -> dict:
        resp = await self._client.get(
            "/blocks",
            params={"id": block_id, "maxDepth": max_depth, "fetchMetadata": fetch_metadata},
        )
        resp.raise_for_status()
        return resp.json()

    async def search_blocks(
        self,
        document_id: str,
        pattern: str,
        *,
        before_block_count: int = 0,
        after_block_count: int = 0,
        fetch_blocks: bool = False,
    ) -> list[dict]:
        resp = await self._client.get(
            "/blocks/search",
            params={
                "documentId": document_id,
                "pattern": pattern,
                "beforeBlockCount": before_block_count,
                "afterBlockCount": after_block_count,
                "fetchBlocks": fetch_blocks,
            },
        )
        resp.raise_for_status()
        return resp.json()["items"]

    async def update_blocks(self, blocks: list[dict]) -> list[dict]:
        resp = await self._client.put("/blocks", json={"blocks": blocks})
        resp.raise_for_status()
        return resp.json()["items"]
