import json
import re

import httpx

from .base import BaseConnector, Document


class PolymarketConnector(BaseConnector):
    """Official Polymarket Gamma API market-data connector."""

    PATTERN = re.compile(
        r"^https?://(?:www\.)?polymarket\.com/"
        r"event/([a-z0-9-]+)$",
        re.IGNORECASE,
    )

    EVENTS_API_URL = "https://gamma-api.polymarket.com/events"

    def detect(self, url: str) -> bool:
        return bool(self.PATTERN.search(url))

    def _extract_target(self, url: str):
        match = self.PATTERN.search(url)
        if not match:
            return None, None
        return "event", match.group(1)

    def fetch(self, url: str) -> Document:
        cached = self._cache_get(url)
        if cached:
            return cached

        target_type, slug = self._extract_target(url)

        if not slug:
            return Document(
                title="Error",
                source_url=url,
                platform="polymarket",
                metadata={"error": "slug_not_found"},
            )

        try:
            endpoint = self.EVENTS_API_URL

            response = httpx.get(
                endpoint,
                params={"slug": slug},
                timeout=15,
            )
            response.raise_for_status()

            payload = response.json()

            if not isinstance(payload, list) or not payload:
                return Document(
                    title="Error",
                    source_url=url,
                    platform="polymarket",
                    metadata={
                        "error": "market_not_found",
                        "target_type": target_type,
                        "slug": slug,
                    },
                )

            data = payload[0]

            markets = data.get("markets") or []
            title = data.get("title") or slug
            description = data.get("description") or ""
            resolution_source = data.get("resolutionSource") or ""
            volume = data.get("volume", "")
            liquidity = data.get("liquidity", "")
            active = data.get("active")
            closed = data.get("closed")

            metadata = {
                "target_type": target_type,
                "slug": slug,
                "title": title,
                "description": description,
                "resolution_source": resolution_source,
                "volume": volume,
                "liquidity": liquidity,
                "active": active,
                "closed": closed,
                "market_count": len(markets),
                "markets": [],
                "api_url": endpoint,
            }

            for market in markets:
                outcomes = market.get("outcomes", [])
                outcome_prices = market.get("outcomePrices", [])

                if isinstance(outcomes, str):
                    try:
                        outcomes = json.loads(outcomes)
                    except Exception:
                        outcomes = [outcomes]

                if isinstance(outcome_prices, str):
                    try:
                        outcome_prices = json.loads(outcome_prices)
                    except Exception:
                        outcome_prices = [outcome_prices]

                metadata["markets"].append(
                    {
                        "slug": market.get("slug", ""),
                        "question": market.get("question", ""),
                        "outcomes": outcomes,
                        "outcome_prices": outcome_prices,
                        "description": market.get("description", ""),
                        "resolution_source": market.get(
                            "resolutionSource",
                            resolution_source,
                        ),
                        "best_bid": market.get("bestBid", ""),
                        "best_ask": market.get("bestAsk", ""),
                        "spread": market.get("spread", ""),
                        "last_trade_price": market.get(
                            "lastTradePrice",
                            "",
                        ),
                        "volume": market.get("volume", ""),
                        "liquidity": market.get("liquidity", ""),
                        "clob_token_ids": market.get("clobTokenIds", ""),
                    }
                )

            doc = Document(
                title=f"Polymarket: {title}",
                source_url=url,
                platform="polymarket",
                metadata=metadata,
            )

            self._cache_set(url, doc)
            return doc

        except httpx.HTTPStatusError as exc:
            return Document(
                title="Error",
                source_url=url,
                platform="polymarket",
                metadata={
                    "error": str(exc),
                    "slug": slug,
                    "target_type": target_type,
                },
            )
        except Exception as exc:
            return Document(
                title="Error",
                source_url=url,
                platform="polymarket",
                metadata={
                    "error": str(exc),
                    "slug": slug,
                    "target_type": target_type,
                },
            )
