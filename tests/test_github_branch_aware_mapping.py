import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aran_search.searcher import AgentReachSearcher


class GithubBranchAwareMappingTests(unittest.TestCase):
    def test_simple_branch_and_readme_path(self):
        url = "https://github.com/owner/repo/blob/main/README.md"
        self.assertEqual(
            AgentReachSearcher._github_contents_api_url(url),
            "https://api.github.com/repos/owner/repo/contents/README.md?ref=main",
        )

    def test_openwrt_branch_and_readme_path(self):
        url = "https://github.com/dl12345/mwan3/blob/openwrt-25.12/README.md"
        self.assertEqual(
            AgentReachSearcher._github_contents_api_url(url),
            "https://api.github.com/repos/dl12345/mwan3/contents/README.md?ref=openwrt-25.12",
        )

    def test_encoded_slash_in_ref_is_preserved(self):
        url = "https://github.com/owner/repo/blob/feature%2Fwan/README.md"
        self.assertEqual(
            AgentReachSearcher._github_contents_api_url(url),
            "https://api.github.com/repos/owner/repo/contents/README.md?ref=feature%2Fwan",
        )

    def test_repository_url_keeps_metadata_behavior(self):
        url = "https://github.com/owner/repo"
        self.assertIsNone(AgentReachSearcher._github_contents_api_url(url))

    @patch("aran_search.searcher.subprocess.run")
    def test_repository_url_uses_metadata_api_fallback(self, run):
        run.return_value = SimpleNamespace(
            stdout='{"full_name":"owner/repo"}\n__FETCH_HTTP_STATUS__:200\n'
        )
        AgentReachSearcher().fetch_url("https://github.com/owner/repo")
        command = run.call_args.args[0]
        self.assertEqual(command[-1], "https://api.github.com/repos/owner/repo")
