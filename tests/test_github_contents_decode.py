import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aran_search.searcher import AgentReachSearcher


class GithubContentsDecodeTests(unittest.TestCase):
    blob_url = "https://github.com/owner/repo/blob/main/README.md"

    def fetch_with(self, payload, status=200, raw=False):
        body = payload if raw else json.dumps(payload)
        stdout = f"{body}\n__FETCH_HTTP_STATUS__:{status}\n"
        with patch(
            "aran_search.searcher.subprocess.run",
            return_value=SimpleNamespace(stdout=stdout),
        ):
            return AgentReachSearcher().fetch_url(self.blob_url)

    def test_valid_contents_file_returns_decoded_markdown(self):
        markdown = "# mwan3\n\nUsage documentation."
        payload = {
            "type": "file",
            "encoding": "base64",
            "content": base64.b64encode(markdown.encode()).decode(),
        }
        self.assertEqual(self.fetch_with(payload), markdown)

    def test_base64_whitespace_is_ignored(self):
        markdown = "# mwan3\n\nUsage documentation."
        encoded = base64.b64encode(markdown.encode()).decode()
        payload = {
            "type": "file",
            "encoding": "base64",
            "content": encoded[:8] + "\n" + encoded[8:] + "\n",
        }
        self.assertEqual(self.fetch_with(payload), markdown)

    def test_non_file_payload_is_rejected(self):
        self.assertEqual(
            self.fetch_with({"type": "dir", "encoding": "base64", "content": "eA=="}),
            "Error GitHub: NOT_FILE",
        )

    def test_non_base64_encoding_is_rejected(self):
        self.assertEqual(
            self.fetch_with({"type": "file", "encoding": "utf-8", "content": "text"}),
            "Error GitHub: UNSUPPORTED_ENCODING",
        )

    def test_empty_content_is_rejected(self):
        self.assertEqual(
            self.fetch_with({"type": "file", "encoding": "base64", "content": ""}),
            "Error GitHub: EMPTY_CONTENT",
        )

    def test_invalid_base64_content_is_rejected(self):
        self.assertEqual(
            self.fetch_with({"type": "file", "encoding": "base64", "content": "not-base64"}),
            "Error GitHub: INVALID_BASE64_CONTENT",
        )

    def test_malformed_json_preserves_explicit_error(self):
        self.assertEqual(
            self.fetch_with("{malformed", raw=True),
            "Error GitHub: INVALID_JSON",
        )

    def test_repository_url_keeps_metadata_behavior(self):
        url = "https://github.com/owner/repo"
        payload = {"full_name": "owner/repo", "type": "repo"}
        body = json.dumps(payload)
        stdout = f"{body}\n__FETCH_HTTP_STATUS__:200\n"
        with patch(
            "aran_search.searcher.subprocess.run",
            return_value=SimpleNamespace(stdout=stdout),
        ):
            self.assertEqual(AgentReachSearcher().fetch_url(url), body)


if __name__ == "__main__":
    unittest.main()
