from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from bot import config
from bot.media import download_image, fetch_og_metadata

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _set_config() -> None:
    config.HTTP_TIMEOUT = 5
    config.MAX_IMAGE_BYTES = 1024


class TestDownloadImage:
    @patch("bot.media.requests.get")
    def test_downloads_bytes(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"image-data"]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = download_image("https://example.com/photo.jpg")

        assert result == b"image-data"
        mock_get.assert_called_once_with(
            "https://example.com/photo.jpg", timeout=5, stream=True
        )

    @patch("bot.media.requests.get")
    def test_raises_on_oversized_image(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        # Return chunks that exceed MAX_IMAGE_BYTES (1024 in test fixture)
        mock_resp.iter_content.return_value = [b"x" * 600, b"x" * 600]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with pytest.raises(ValueError, match="exceeds"):
            download_image("https://example.com/huge.jpg")

    @patch("bot.media.requests.get")
    def test_raises_on_http_error(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")
        mock_get.return_value = mock_resp

        with pytest.raises(requests.HTTPError):
            download_image("https://example.com/missing.jpg")


class TestFetchOgMetadata:
    @patch("bot.media.requests.get")
    def test_extracts_og_tags(self, mock_get: MagicMock) -> None:
        html = """
        <html><head>
            <meta property="og:title" content="Test Title" />
            <meta property="og:description" content="Test Desc" />
            <meta property="og:image" content="https://example.com/og.png" />
        </head><body></body></html>
        """
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        meta = fetch_og_metadata("https://example.com")

        assert meta["title"] == "Test Title"
        assert meta["description"] == "Test Desc"
        assert meta["image"] == "https://example.com/og.png"

    @patch("bot.media.requests.get")
    def test_falls_back_to_title_tag(self, mock_get: MagicMock) -> None:
        html = "<html><head><title>Fallback Title</title></head><body></body></html>"
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        meta = fetch_og_metadata("https://example.com")

        assert meta["title"] == "Fallback Title"

    @patch("bot.media.requests.get")
    def test_falls_back_to_meta_description(self, mock_get: MagicMock) -> None:
        html = '<html><head><meta name="description" content="Meta desc" /></head><body></body></html>'
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        meta = fetch_og_metadata("https://example.com")

        assert meta["description"] == "Meta desc"

    @patch("bot.media.requests.get")
    def test_returns_empty_on_http_error(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = requests.ConnectionError("unreachable")

        meta = fetch_og_metadata("https://example.com")

        assert meta == {"title": "", "description": "", "image": ""}

    @patch("bot.media.requests.get")
    def test_returns_empty_on_no_tags(self, mock_get: MagicMock) -> None:
        html = "<html><head></head><body>Hello</body></html>"
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        meta = fetch_og_metadata("https://example.com")

        assert meta["title"] == ""
        assert meta["description"] == ""
        assert meta["image"] == ""
