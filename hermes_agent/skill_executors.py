from agent_reach.searcher import AgentReachSearcher


def agent_reach_executor(searcher, query, **kwargs):
    return searcher.search(
        query,
        sources=kwargs.get("sources", ["searxng"]),
        allow_video=kwargs.get("allow_video", False),
        allow_social=kwargs.get("allow_social", False),
    )


def agent_reach_fetch_executor(searcher, url, **kwargs):
    return searcher.fetch_url(url)
