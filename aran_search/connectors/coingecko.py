import re
from datetime import datetime, timezone

import httpx

from .base import BaseConnector, Document


class CoinGeckoConnector(BaseConnector):
    """Official CoinGecko API connector."""

    PATTERN = re.compile(
        r"^https?://(?:www\.)?coingecko\.com/(?:en/coins/)?([^/?#]+)",
        re.IGNORECASE,
    )
    API_URL = "https://api.coingecko.com/api/v3/simple/price"

    def detect(self, url: str) -> bool:
        return bool(self.PATTERN.search(url))

    def _extract_coin_id(self, url: str) -> str | None:
        match = self.PATTERN.search(url)
        return match.group(1) if match else None

    def fetch(self, url: str) -> Document:
        cached = self._cache_get(url)
        if cached:
            return cached

        coin_id = self._extract_coin_id(url)
        if not coin_id:
            return Document(
                title="Error",
                source_url=url,
                platform="coingecko",
                metadata={"error": "coin_id_not_found"},
            )

        try:
            resp = httpx.get(
                self.API_URL,
                params={
                    "ids": coin_id,
                    "vs_currencies": "usd",
                    "include_last_updated_at": "true",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            coin = data.get(coin_id)
            if not isinstance(coin, dict) or "usd" not in coin:
                return Document(
                    title="Error",
                    source_url=url,
                    platform="coingecko",
                    metadata={
                        "error": "coin_not_found",
                        "coin_id": coin_id,
                    },
                )

            price_usd = coin["usd"]
            updated_at = coin.get("last_updated_at", "")
            updated_utc = ""

            if updated_at:
                updated_utc = datetime.fromtimestamp(
                    int(updated_at),
                    tz=timezone.utc,
                ).isoformat()

            doc = Document(
                title=f"CoinGecko: {coin_id}",
                source_url=url,
                platform="coingecko",
                metadata={
                    "coin_id": coin_id,
                    "price_usd": price_usd,
                    "last_updated_at": updated_at,
                    "last_updated_utc": updated_utc,
                    "api_url": self.API_URL,
                },
            )

            self._cache_set(url, doc)
            return doc

        except Exception as e:
            return Document(
                title="Error",
                source_url=url,
                platform="coingecko",
                metadata={
                    "error": str(e),
                    "coin_id": coin_id,
                },
            )
