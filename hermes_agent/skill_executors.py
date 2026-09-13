def agent_reach_executor(searcher, query, **kwargs):
    return searcher.search(
        query,
        sources=kwargs.get("sources"),
        allow_video=kwargs.get("allow_video", False),
        allow_social=kwargs.get("allow_social", False),
    )


def agent_reach_fetch_executor(searcher, url, **kwargs):
    return searcher.fetch_url(url)


def weather_executor(searcher, query, **kwargs):
    """Execute weather capability through the existing Searcher/WeatherConnector."""
    return searcher.fetch_url(query)
