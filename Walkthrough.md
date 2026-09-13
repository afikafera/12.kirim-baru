Walkthrough — Weather API Capability Integration (Open-Meteo)
1. Overview & Architectural Boundaries
Sesuai dengan arahan audit dan 3 guardrail yang ditetapkan:

Orchestrator Scope Preserved: Recovery controller tetap menjadi pemanggil capability yang terfokus; WeatherConnector menangani panggilan API publik Open-Meteo, geocoding koordinat, kalkulasi forecast, dan normalisasi.
Target Date Explicitly Highlighted: Formatter dan connector secara eksplisit membedakan lokasi, tanggal target (target_date), temperatur maksimum (temperature_2m_max), temperatur minimum (temperature_2m_min), estimasi presipitasi/hujan, unit (°C/mm), dan timezone (misal Asia/Shanghai).
No False 100% Accuracy Claim: Data dideklarasikan secara objektif sebagai hasil observasi dan prakiraan model numerik meteorologi Open-Meteo API tanpa klaim determinisme palsu.
Port 8080 & Git Integrity: Open WebUI tidak disentuh, tidak ada perintah destructive git reset/clean/stash.
2. Changes Made
A. New Weather Connector
aran_search/connectors/weather.py
Mengimplementasikan WeatherConnector(BaseConnector) dengan disk cache 24 jam.
Endpoint resmi: geocoding-api.open-meteo.com/v1/search & api.open-meteo.com/v1/forecast.
Mengambil parameter observasi terkini (temperature_2m, precipitation, rain, weather_code, relative_humidity_2m, wind_speed_10m) dan prakiraan harian (temperature_2m_max, temperature_2m_min, precipitation_sum, rain_sum).
Pemetaan otomatis kode cuaca WMO (WMO Weather interpretation codes).
Ekstraksi dan pencocokan tanggal target (target_date_forecast).
Graceful fallback saat lokasi tidak ditemukan (location_not_found).
B. Connector Registration & Dispatch
aran_search/connectors/__init__.py
Mengekspos WeatherConnector.
aran_search/searcher.py
Menambahkan dispatch WeatherConnector pada method fetch_url.
Menambahkan method _format_weather yang menghasilkan struktur evidence standar:
Header [WEATHER OFFICIAL API - OPEN-METEO]
Metadata Location, Region/Admin, Coordinates, Timezone, Current Timestamp
Section Current Weather
Section [TARGET DATE FORECAST] dengan temperature_2m_max dan unit
Section [DAILY FORECAST SUMMARY]
API Provider dan Source URL canonical
C. Skill Routing & Execution
hermes_agent/skill_router.py
Menambahkan leksikon cuaca ke internet_terms: "weather", "cuaca", "forecast", "prakiraan", "suhu", "temperature", "rain", "hujan".
Menambahkan rute kategori cuaca ke _agent_reach_route: ("weather", "references/weather.md", ...).
hermes_agent/skill_executors.py
Mengimplementasikan weather_executor(searcher, query_or_url, **kwargs).
~/.agents/skills/weather/SKILL.md
Semantic descriptor terisolasi tanpa kode eksekusi/API call, dapat ditemukan otomatis oleh SkillRouter._discover().
D. Recovery Controller & Node Processing
hermes_agent/orchestrator.py
Mendaftarkan capability "weather" ke SkillBridge.
Menambahkan helper _extract_weather_target(text) untuk mengekstraksi nama kota dan tanggal target (YYYY-MM-DD) dari pertanyaan pasar Polymarket.
Memperbarui _resolve_recovery_requirement: menghasilkan recovery requirement dengan capability="weather" dan target URL langsung ke https://open-meteo.com/en/weather?location={loc}&date={date}.
Memperbarui process_node: mendukung requirement-level target sebagai Hard Target dengan prioritas langsung di atas pencarian web generik.
3. Verification & Test Results
Test Suite	File	Scope	Status
1. Standalone Connector	scratch/test_weather_connector_standalone.py	Geocoding, Daily Forecast, Target Date 2026-09-13, Disk Cache Hit (7.73ms), Graceful Error Handling	PASS (100%)
2. Searcher Fetch & Format	scratch/test_searcher_weather_fetch.py	fetch_url() dispatch, string output structure, header [WEATHER OFFICIAL API], temperature_2m_max, timezone	PASS (100%)
3. SkillRouter Discovery & Matching	scratch/test_skill_router_weather.py	~/.agents/skills/weather/SKILL.md discovered, query intent matched, _agent_reach_route category assigned	PASS (100%)
4. Connector & Architecture Regression	scratch/test_weather_regression_and_e2e.py	Legacy connector detection (Polymarket, Binance, CoinGecko) zero collision; SkillBridge execution; multi-city detection (Shanghai, Dallas, Wellington, Munich, New Orleans)	PASS (4/4)
5. Full E2E Recovery Simulation	scratch/test_full_e2e_weather_flow.py	Polymarket fact in context -> Evaluator MISSING -> Controller recovery generation -> Live Open-Meteo fetch -> FactChecker extraction -> KG learning -> Node status FOUND	PASS (100%)
6. Python Syntax Compilation	python -m py_compile	aran_search/connectors/weather.py, aran_search/searcher.py, hermes_agent/skill_router.py, hermes_agent/skill_executors.py, hermes_agent/orchestrator.py	PASS (0 errors)
