import asyncio
import json

try:
    from agent_reach.discovery_exa import ExaDiscoveryTool
except ImportError as e:
    print(f"[IMPORT FAILED] agent_reach.discovery_exa: {e}")
    print("This confirms Exa is not reachable via this import path in "
          "production. The 5 RAW results in the handoff must have come "
          "from a different code path -- clarify before trusting the "
          "fixture.")
    raise SystemExit(1)

QUERY = (
    "What is the current Bitcoin price according to CoinGecko, "
    "and when was the price last updated?"
)


async def main():
    discovery = ExaDiscoveryTool()
    exa_raw = await discovery.search(QUERY, num_results=5)

    normalized = [
        {
            "title": item.title,
            "url": item.url,
            "content": item.highlights,
            "engine": "exa",
            "score": 0.0,
            "category": "general",
        }
        for item in exa_raw
    ]

    print(json.dumps(normalized, indent=2, ensure_ascii=False))


asyncio.run(main())
