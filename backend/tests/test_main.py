import asyncio
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.app.main import (
    JobCancelled,
    AnalyzeRequest,
    analyze,
    analyze_url,
    extractor_error_message,
    format_info,
    jobs,
    progress_hook,
    public_hostname,
    safe_filename,
    validate_extracted_urls,
)


class ValidationTests(unittest.TestCase):
    @patch("backend.app.main.socket.getaddrinfo", return_value=[("", "", "", "", ("127.0.0.1", 80))])
    def test_private_destination_is_rejected(self, _resolve):
        with self.assertRaises(HTTPException):
            public_hostname("http://internal.example/video.mp4")

    def test_unsupported_scheme_is_rejected(self):
        with self.assertRaises(HTTPException):
            public_hostname("file:///C:/secret.mp4")

    @patch("backend.app.main.socket.getaddrinfo", return_value=[("", "", "", "", ("10.0.0.8", 443))])
    def test_extractor_resolved_private_url_is_rejected(self, _resolve):
        with self.assertRaises(HTTPException):
            validate_extracted_urls({"formats": [{"url": "https://cdn.example/video.mp4"}]})


class FormatTests(unittest.TestCase):
    def test_exact_filesize_is_preferred(self):
        result = format_info({"format_id": "18", "ext": "mp4", "filesize": 2_000_000, "filesize_approx": 3_000_000, "vcodec": "avc1", "acodec": "mp4a"})
        self.assertEqual(result["filesize_bytes"], 2_000_000)
        self.assertFalse(result["filesize_is_approximate"])
        self.assertEqual(result["filesize_source"], "exact")

    def test_approximate_filesize_is_labeled(self):
        result = format_info({"format_id": "22", "ext": "mp4", "filesize_approx": 3_000_000, "vcodec": "avc1", "acodec": "mp4a"})
        self.assertEqual(result["filesize_bytes"], 3_000_000)
        self.assertTrue(result["filesize_is_approximate"])
        self.assertEqual(result["filesize_source"], "approximate")

    def test_hls_size_is_estimated_from_duration_and_bitrate(self):
        result = format_info({"format_id": "hls-2649", "ext": "mp4", "tbr": 2649, "vcodec": "avc1", "acodec": "mp4a"}, 120)
        self.assertEqual(result["filesize_bytes"], 39_735_000)
        self.assertTrue(result["filesize_is_approximate"])
        self.assertEqual(result["filesize_source"], "estimated")

    def test_size_is_unavailable_without_valid_metadata(self):
        result = format_info({"format_id": "hls-unknown", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a"}, 0)
        self.assertIsNone(result["filesize_bytes"])
        self.assertTrue(result["filesize_is_approximate"])
        self.assertIsNone(result["filesize_source"])

    def test_video_only_format_requires_merge(self):
        result = format_info({"format_id": "137", "ext": "mp4", "width": 1920, "height": 1080, "vcodec": "avc1", "acodec": "none"})
        self.assertEqual(result["kind"], "video")
        self.assertTrue(result["needs_merge"])

    def test_audio_only_format_is_identified(self):
        result = format_info({"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a"})
        self.assertEqual(result["kind"], "audio")
        self.assertFalse(result["has_video"])

    @patch("backend.app.main.public_hostname", return_value="xhamster.desi")
    @patch("backend.app.main.yt_dlp.YoutubeDL")
    def test_hls_formats_are_returned(self, youtube_dl, _hostname):
        info = {
            "title": "Sample HLS video",
            "duration": 120,
            "thumbnail": None,
            "url": "https://cdn.example/video.m3u8",
            "formats": [
                {
                    "format_id": "hls-2649-1",
                    "ext": "mp4",
                    "width": 1920,
                    "height": 1080,
                    "vcodec": "avc1",
                    "acodec": "mp4a.40.2",
                    "url": "https://cdn.example/video.m3u8",
                }
            ],
        }
        youtube_dl.return_value.__enter__.return_value.extract_info.return_value = info
        result = asyncio.run(analyze(AnalyzeRequest(url="https://xhamster.desi/videos/sample-xh123")))
        self.assertEqual(result["default_format_id"], "hls-2649-1")
        self.assertEqual(result["formats"][0]["kind"], "video+audio")
        self.assertIn("formats", result)

    @patch("backend.app.main.public_hostname", return_value="example.com")
    def test_direct_media_preserves_contract(self, _hostname):
        result = analyze_url("https://example.com/video.mp4")
        self.assertEqual(result["default_format_id"], "direct-mp4")
        self.assertEqual(result["formats"][0]["format_id"], "direct-mp4")
        self.assertIsNone(result["formats"][0]["filesize_source"])


class ErrorAndJobTests(unittest.TestCase):
    def test_error_mapping_is_user_friendly(self):
        self.assertIn("authentication", extractor_error_message(Exception("Sign in required")))
        self.assertIn("rate limiting", extractor_error_message(Exception("HTTP Error 429: Too Many Requests")))
        self.assertIn("protected", extractor_error_message(Exception("DRM protected")))

    def test_filename_is_sanitized(self):
        filename = safe_filename('bad<>:"/\\|?* name', "mp4")
        self.assertNotIn("<", filename)
        self.assertNotIn("/", filename)

    def test_progress_hook_updates_job(self):
        job_id = "test-job"
        jobs[job_id] = {"status": "queued", "cancel_event": threading.Event()}
        try:
            progress_hook(job_id, {"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100, "speed": 10, "eta": 5})
            self.assertEqual(jobs[job_id]["status"], "downloading")
            self.assertEqual(jobs[job_id]["progress"], 50.0)
        finally:
            jobs.pop(job_id, None)

    def test_cancelled_job_stops_progress(self):
        job_id = "cancelled-job"
        event = threading.Event()
        event.set()
        jobs[job_id] = {"status": "cancelled", "cancel_event": event}
        try:
            with self.assertRaises(JobCancelled):
                progress_hook(job_id, {"status": "downloading"})
        finally:
            jobs.pop(job_id, None)


if __name__ == "__main__":
    unittest.main()
