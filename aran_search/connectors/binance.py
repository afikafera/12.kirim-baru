import re
from datetime import datetime, timezone

import httpx

from .base import BaseConnector, Document


class BinanceConnector(BaseConnector):
    """Official Binance Spot market-data connector."""

    PATTERN = re.compile(
        r"^https?://(?:www\.)?binance\.com/(?:[a-z]{2}/)?trade/"
        r"([A-Z0-9]+)_([A-Z0-9]+)",
        re.IGNORECASE,
    )
    API_URL = "https://api.binance.com/api/v3/ticker/24hr"

    def detect(self, url: str) -> bool:
        return bool(self.PATTERN.search(url))

    def _extract_symbol(self, url: str) -> str | None:
        match = self.PATTERN.search(url)
        if not match:
            return None
        return f"{match.group(1)}{match.group(2)}".upper()

    def fetch(self, url: str) -> Document:
        cached = self._cache_get(url)
        if cached:
            return cached

        symbol = self._extract_symbol(url)
        if not symbol:
            return Document(
                title="Error",
                source_url=url,
                platform="binance",
                metadata={"error": "symbol_not_found"},
            )

        try:
            resp = httpx.get(
                self.API_URL,
                params={"symbol": symbol},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if not isinstance(data, dict) or data.get("symbol") != symbol:
                return Document(
                    title="Error",
                    source_url=url,
                    platform="binance",
                    metadata={
                        "error": "symbol_not_found",
                        "symbol": symbol,
                    },
                )

            close_time = data.get("closeTime", "")
            close_utc = ""

            if close_time:
                close_utc = datetime.fromtimestamp(
                    int(close_time) / 1000,
                    tz=timezone.utc,
                ).isoformat()

            doc = Document(
                title=f"Binance: {symbol}",
                source_url=url,
                platform="binance",
                metadata={
                    "symbol": symbol,
                    "last_price": data.get("lastPrice", ""),
                    "price_change": data.get("priceChange", ""),
                    "price_change_percent": data.get(
                        "priceChangePercent", ""
                    ),
                    "high_price": data.get("highPrice", ""),
                    "low_price": data.get("lowPrice", ""),
                    "volume": data.get("volume", ""),
                    "quote_volume": data.get("quoteVolume", ""),
                    "close_time": close_time,
                    "close_time_utc": close_utc,
                    "api_url": self.API_URL,
                },
            )

            self._cache_set(url, doc)
            return doc

        except httpx.HTTPStatusError as e:
            try:
                error_data = e.response.json()
            except Exception:
                error_data = {}

            error_code = error_data.get("code")
            error_message = error_data.get("msg", str(e))

            if error_code == -1121:
                return Document(
                    title="Error",
                    source_url=url,
                    platform="binance",
                    metadata={
                        "error": "invalid_symbol",
                        "symbol": symbol,
                        "binance_code": error_code,
                        "binance_message": error_message,
                    },
                )

            return Document(
                title="Error",
                source_url=url,
                platform="binance",
                metadata={
                    "error": error_message,
                    "symbol": symbol,
                    "binance_code": error_code,
                },
            )

        except Exception as e:
            return Document(
                title="Error",
                source_url=url,
                platform="binance",
                metadata={
                    "error": str(e),
                    "symbol": symbol,
                },
            )
