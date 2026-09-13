import json
import logging
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from .base import BaseConnector, Document

logger = logging.getLogger(__name__)

WMO_WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class WeatherConnector(BaseConnector):
    """
    Official Open-Meteo Weather API Connector.

    Provides geocoding, current weather observations, and daily forecasts.
    Read-only, public endpoints, zero API key required.
    Inherits 24-hour disk caching and Document contract from BaseConnector.
    """

    GEOCODING_API_URL = "https://geocoding-api.open-meteo.com/v1/search"
    FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"

    PATTERNS = [
        re.compile(r"^https?://(?:www\.)?open-meteo\.com/(?:[a-z]{2}/)?weather", re.IGNORECASE),
        re.compile(r"^weather://", re.IGNORECASE),
        re.compile(r"^https?://(?:www\.)?wttr\.in/", re.IGNORECASE),
        re.compile(r"^https?://(?:www\.)?weather\.com/", re.IGNORECASE),
        re.compile(r"^https?://(?:www\.)?accuweather\.com/", re.IGNORECASE),
    ]

    def detect(self, url: str) -> bool:
        if not url or not isinstance(url, str):
            return False
        return any(p.search(url) for p in self.PATTERNS)

    def _extract_location_and_target(self, url: str) -> tuple[Optional[str], Optional[str]]:
        """
        Extract location string and optional target date/metric from URL.
        """
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)

        # 1. Query parameters
        loc = None
        for key in ("location", "q", "city", "name", "loc"):
            if key in qs and qs[key]:
                loc = qs[key][0].strip()
                break

        target_date = None
        for key in ("date", "target_date", "dt", "day"):
            if key in qs and qs[key]:
                target_date = qs[key][0].strip()
                break

        if loc:
            return loc, target_date

        # 2. weather:// scheme
        if parsed.scheme.lower() == "weather":
            loc_candidate = parsed.netloc or parsed.path.strip("/")
            if loc_candidate:
                return loc_candidate.replace("-", " ").replace("_", " ").strip(), target_date

        # 3. Path segments
        path = parsed.path
        if "open-meteo.com" in parsed.netloc.lower():
            parts = [p for p in path.split("/") if p and p.lower() not in ("en", "weather")]
            if parts:
                return parts[0].replace("-", " ").replace("_", " ").strip(), target_date

        if "wttr.in" in parsed.netloc.lower():
            parts = [p for p in path.split("/") if p]
            if parts:
                return parts[0].replace("-", " ").replace("_", " ").strip(), target_date

        if "weather.com" in parsed.netloc.lower():
            m = re.search(r"/l/([^/?#+]+)", path)
            if m:
                return m.group(1).replace("-", " ").replace("_", " ").strip(), target_date

        if "accuweather.com" in parsed.netloc.lower():
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 3:
                return parts[2].replace("-", " ").replace("_", " ").strip(), target_date

        return None, None

    def _http_get_json(self, url: str, params: dict) -> dict:
        query_str = urllib.parse.urlencode(params)
        full_url = f"{url}?{query_str}"
        req = urllib.request.Request(
            full_url,
            headers={
                "User-Agent": "HermesResearchAssistant/1.0 (open-meteo-connector)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            data = response.read().decode("utf-8")
            return json.loads(data)

    def _geocode(self, location_name: str) -> Optional[dict]:
        clean_name = location_name.replace("-", " ").strip()
        data = self._http_get_json(
            self.GEOCODING_API_URL,
            {
                "name": clean_name,
                "count": 1,
                "language": "en",
                "format": "json",
            },
        )
        results = data.get("results", [])
        if results and isinstance(results, list):
            return results[0]
        return None

    def _fetch_forecast(self, latitude: float, longitude: float) -> dict:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,rain,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,rain_sum",
            "timezone": "auto",
        }
        return self._http_get_json(self.FORECAST_API_URL, params)

    def fetch(self, url: str) -> Document:
        cached = self._cache_get(url)
        if cached:
            logger.info("[weather-connector] cache hit url=%s", url)
            return cached

        loc_name, target_date = self._extract_location_and_target(url)
        if not loc_name:
            return Document(
                title="Error",
                source_url=url,
                platform="weather",
                metadata={
                    "error": "location_not_specified",
                    "source_url": url,
                },
            )

        try:
            geo = self._geocode(loc_name)
            if not geo:
                return Document(
                    title="Error",
                    source_url=url,
                    platform="weather",
                    metadata={
                        "error": "location_not_found",
                        "location": loc_name,
                        "source_url": url,
                    },
                )

            lat = geo.get("latitude")
            lon = geo.get("longitude")
            resolved_name = geo.get("name", loc_name)
            country = geo.get("country", "")
            admin1 = geo.get("admin1", "")
            tz_str = geo.get("timezone", "UTC")

            forecast_data = self._fetch_forecast(lat, lon)

            current = forecast_data.get("current", {})
            current_units = forecast_data.get("current_units", {})
            daily = forecast_data.get("daily", {})
            daily_units = forecast_data.get("daily_units", {})

            weather_code = current.get("weather_code")
            weather_desc = WMO_WEATHER_CODES.get(weather_code, "Unknown")

            daily_times = daily.get("time", [])
            daily_max = daily.get("temperature_2m_max", [])
            daily_min = daily.get("temperature_2m_min", [])
            daily_precip = daily.get("precipitation_sum", [])
            daily_rain = daily.get("rain_sum", [])

            forecast_list = []
            target_date_forecast = None

            temp_unit = daily_units.get("temperature_2m_max", "C")
            precip_unit = daily_units.get("precipitation_sum", "mm")

            for i, dt_str in enumerate(daily_times):
                t_max = daily_max[i] if i < len(daily_max) else None
                t_min = daily_min[i] if i < len(daily_min) else None
                p_sum = daily_precip[i] if i < len(daily_precip) else 0.0
                r_sum = daily_rain[i] if i < len(daily_rain) else 0.0

                day_entry = {
                    "date": dt_str,
                    "temperature_2m_max": t_max,
                    "temperature_2m_min": t_min,
                    "temperature_unit": temp_unit,
                    "precipitation_sum": p_sum,
                    "rain_sum": r_sum,
                    "precipitation_unit": precip_unit,
                }
                forecast_list.append(day_entry)

                if target_date:
                    norm_target = target_date.replace("-", "").lower()
                    norm_dt = dt_str.replace("-", "").lower()
                    if norm_target in norm_dt or norm_dt in norm_target:
                        target_date_forecast = day_entry

            doc = Document(
                title=f"Open-Meteo Weather: {resolved_name}, {country}",
                source_url=url,
                platform="weather",
                created_at=datetime.now(timezone.utc).isoformat(),
                metadata={
                    "location": resolved_name,
                    "country": country,
                    "admin1": admin1,
                    "latitude": lat,
                    "longitude": lon,
                    "timezone": tz_str,
                    "current_timestamp": current.get("time"),
                    "current_temperature": current.get("temperature_2m"),
                    "temperature_unit": current_units.get("temperature_2m", "C"),
                    "current_humidity": current.get("relative_humidity_2m"),
                    "humidity_unit": current_units.get("relative_humidity_2m", "%"),
                    "current_precipitation": current.get("precipitation"),
                    "precipitation_unit": current_units.get("precipitation", "mm"),
                    "current_rain": current.get("rain"),
                    "current_weather_code": weather_code,
                    "current_weather_desc": weather_desc,
                    "current_wind_speed": current.get("wind_speed_10m"),
                    "wind_speed_unit": current_units.get("wind_speed_10m", "km/h"),
                    "target_date": target_date,
                    "target_date_forecast": target_date_forecast,
                    "forecast_daily": forecast_list,
                    "api_url": self.FORECAST_API_URL,
                    "source_url": url,
                },
            )

            self._cache_set(url, doc)
            return doc

        except urllib.error.HTTPError as e:
            logger.warning("[weather-connector] HTTPError url=%s code=%d", url, e.code)
            return Document(
                title="Error",
                source_url=url,
                platform="weather",
                metadata={
                    "error": f"http_error_{e.code}",
                    "location": loc_name,
                    "details": str(e),
                    "source_url": url,
                },
            )
        except Exception as e:
            logger.exception("[weather-connector] fetch failed url=%s", url)
            return Document(
                title="Error",
                source_url=url,
                platform="weather",
                metadata={
                    "error": str(e),
                    "location": loc_name,
                    "source_url": url,
                },
            )
