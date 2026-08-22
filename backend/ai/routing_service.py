"""
Lightweight semantic routing layer to decide whether a query should hit RAG.

- Loads route definitions from ai/routes.yaml
- Pre-computes utterance embeddings via ML service
- Routes each query using cosine similarity against route embeddings
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any

import yaml

from services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


@dataclass
class RouteVector:
    name: str
    handler: str
    threshold: float
    description: str
    utterance_vectors: List[List[float]] = field(default_factory=list)


class RoutingService:
    """In-memory semantic router."""

    def __init__(self, routes_path: Optional[Path] = None):
        self.routes_path = routes_path or Path(__file__).with_name("routes.yaml")
        self.routes: List[RouteVector] = []
        self._load_routes()

    def _load_routes(self) -> None:
        """Load routes from YAML and embed utterances."""
        if not self.routes_path.exists():
            logger.warning(
                "Routes file not found at %s; routing disabled", self.routes_path
            )
            return

        with open(self.routes_path, "r") as f:
            data = yaml.safe_load(f) or {}

        routes_cfg = data.get("routes") or []
        if not routes_cfg:
            logger.warning("No routes configured in %s", self.routes_path)
            return

        for route_cfg in routes_cfg:
            utterances = route_cfg.get("utterances") or []
            if not utterances:
                continue

            vectors = self._embed_texts(utterances)
            route = RouteVector(
                name=route_cfg.get("name", "unknown"),
                handler=route_cfg.get("handler", "doc_rag"),
                threshold=float(route_cfg.get("threshold", 0.3)),
                description=route_cfg.get("description", ""),
                utterance_vectors=vectors,
            )
            self.routes.append(route)

        logger.info("Routing service initialized with %d routes", len(self.routes))

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts using the shared embedding service."""
        try:
            vectors = embedding_service.generate_embedding_sync(texts, mode="query")
            return vectors if isinstance(vectors, list) else []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to embed route utterances: %s", exc)
            return []

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not a or not b:
            return 0.0
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def route(
        self, query: str, query_embedding: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        Route a query to the best-matching route.

        Returns:
            {"name": str | None, "handler": str | None, "score": float}
        """
        if not self.routes:
            return {"name": None, "handler": None, "score": 0.0}

        if query_embedding is None:
            try:
                emb = embedding_service.generate_embedding_sync(query, mode="query")
                query_embedding = emb if isinstance(emb, list) else None
            except Exception as exc:  # noqa: BLE001
                logger.warning("Routing embedding failed: %s", exc)
                return {"name": None, "handler": None, "score": 0.0}

        if not query_embedding:
            return {"name": None, "handler": None, "score": 0.0}

        best_route = None
        best_score = 0.0

        for route in self.routes:
            if not route.utterance_vectors:
                continue
            route_score = max(
                self._cosine(query_embedding, vec) for vec in route.utterance_vectors
            )
            if route_score > best_score and route_score >= route.threshold:
                best_score = route_score
                best_route = route

        if not best_route:
            return {"name": None, "handler": None, "score": 0.0}

        return {
            "name": best_route.name,
            "handler": best_route.handler,
            "score": best_score,
        }


_routing_service: Optional[RoutingService] = None


def get_routing_service() -> RoutingService:
    """Singleton accessor."""
    global _routing_service  # noqa: PLW0603
    if _routing_service is None:
        _routing_service = RoutingService()
    return _routing_service
