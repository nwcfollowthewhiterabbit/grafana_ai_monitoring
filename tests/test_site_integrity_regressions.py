from __future__ import annotations

from email.message import Message
import unittest
from unittest import mock

from test_monitoring_v2 import integrity


class IntegrityRegressionTests(unittest.TestCase):
    def test_fetch_retains_final_redirect_url(self):
        headers = Message()
        headers["Content-Type"] = "text/html"
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers = headers
        response.read.return_value = b"<html>OK</html>"
        response.geturl.return_value = "https://example.com/en/"
        with mock.patch.object(integrity, "is_public_http_url", return_value=True), mock.patch.object(
            integrity.urllib.request, "build_opener"
        ) as opener:
            opener.return_value.open.return_value = response
            result = integrity.fetch_url("https://example.com", 1, 1024, "test")
        self.assertEqual(result.final_url, "https://example.com/en/")

    def test_redirected_page_uses_destination_for_relative_assets(self):
        target = integrity.IntegrityTarget("https://example.com", {})
        page = integrity.FetchResult(
            True, 200, b"<link rel='stylesheet' href='styles.css'>", "text/html",
            False, "", "https://example.com/en/",
        )
        with mock.patch.object(integrity, "fetch_url", return_value=page), mock.patch.object(
            integrity, "check_resources", return_value=(1, 0)
        ) as resources:
            result = integrity.check_target(
                target, timeout=1, page_size_cap=1024, resource_size_cap=1,
                max_resources=40, resource_workers=2, resource_failure_threshold=0.25,
                min_visible_chars=40, user_agent="test",
            )
        self.assertFalse(result.bad)
        self.assertEqual(resources.call_args.args[0], {"https://example.com/en/styles.css": "css"})

    def test_first_document_base_applies_to_relative_assets(self):
        _reasons, resources = integrity.inspect_html(
            "https://example.com/en/",
            b"<base href='/assets/'><base href='/wrong/'><script src='app.js'></script>",
            20, 40,
        )
        self.assertEqual(resources, {"https://example.com/assets/app.js": "javascript"})

    def test_images_do_not_crowd_out_stylesheets_and_scripts(self):
        resources = {f"https://example.com/img-{i}.png": "image" for i in range(100)}
        resources.update({"https://example.com/main.css": "css", "https://example.com/app.js": "javascript"})
        selected = integrity.select_resources(resources, 2)
        self.assertEqual(selected, ["https://example.com/main.css", "https://example.com/app.js"])
        self.assertEqual(selected, integrity.select_resources(dict(reversed(list(resources.items()))), 2))

    def test_http_200_html_fallback_is_a_failed_asset(self):
        page = integrity.FetchResult(True, 200, b"<", "text/html", True, "")
        with mock.patch.object(integrity, "fetch_url", return_value=page):
            for kind in ("css", "javascript", "image"):
                with self.subTest(kind=kind):
                    self.assertFalse(integrity.check_resource("https://example.com/missing", 1, 1, "test", kind))

    def test_unknown_asset_mime_does_not_invent_a_failure(self):
        page = integrity.FetchResult(True, 200, b"x", "application/octet-stream", True, "")
        with mock.patch.object(integrity, "fetch_url", return_value=page):
            self.assertTrue(integrity.check_resource("https://example.com/a.js", 1, 1, "test", "javascript"))

    def test_resource_pool_preserves_kind_for_soft_404_detection(self):
        page = integrity.FetchResult(True, 200, b"<", "text/html", True, "")
        with mock.patch.object(integrity, "fetch_url", return_value=page):
            checked, failures = integrity.check_resources(
                {"https://example.com/a.css": "css", "https://example.com/a.js": "javascript"},
                1, 1, "test", 2,
            )
        self.assertEqual((checked, failures), (2, 2))


if __name__ == "__main__":
    unittest.main()
