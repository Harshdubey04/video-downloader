from __future__ import annotations

import ipaddress
import os
import re
import shutil
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yt_dlp
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl

app = FastAPI(title="Fetchly API", version="2.0.0")
allowed_origins = [origin.strip() for origin in os.getenv("FETCHLY_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"], max_age=600)

DOWNLOAD_DIR = Path(os.getenv("FETCHLY_DOWNLOAD_DIR", str(Path.home() / "Downloads" / "Fetchly"))).expanduser().resolve()
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_DOWNLOAD_BYTES = int(os.getenv("FETCHLY_MAX_DOWNLOAD_BYTES", str(4 * 1024 * 1024 * 1024)))
MAX_JOBS = max(1, int(os.getenv("FETCHLY_MAX_CONCURRENT_JOBS", "2")))
JOB_TTL = timedelta(hours=24)
executor = ThreadPoolExecutor(max_workers=MAX_JOBS, thread_name_prefix="fetchly-download")
jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.RLock()


class AnalyzeRequest(BaseModel):
    url: HttpUrl


class DownloadRequest(BaseModel):
    url: HttpUrl
    format_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9._+/-]+$")


class JobCancelled(Exception):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def public_hostname(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Only HTTP and HTTPS URLs are supported.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "metadata.google.internal", "instance-data.ec2.internal"}:
        raise HTTPException(status_code=400, detail="This destination is not allowed.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="The URL hostname could not be resolved.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise HTTPException(status_code=400, detail="Private and internal network destinations are not allowed.")
    return hostname


def direct_format(url: str) -> dict[str, Any] | None:
    extension = Path(urlparse(url).path).suffix.lower().lstrip(".")
    if extension not in {"mp4", "webm", "m4v", "mov"}:
        return None
    return {"format_id": f"direct-{extension}", "container": "webm" if extension == "webm" else "mp4", "resolution": None, "width": None, "height": None, "filesize_bytes": None, "has_audio": True, "video_codec": None, "audio_codec": None, "needs_merge": False}


def is_direct(url: str) -> bool:
    return direct_format(url) is not None


def safe_filename(value: str, extension: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)[:180] or "fetchly-video"
    return f"{cleaned}.{extension.lstrip('.')}"


def cleanup_stale_jobs() -> None:
    cutoff = now() - JOB_TTL
    with jobs_lock:
        stale = [job_id for job_id, job in jobs.items() if job["created_at"] < cutoff and job["status"] in {"completed", "failed", "cancelled"}]
        for job_id in stale:
            job = jobs.pop(job_id)
            for path_key in ("file_path", "temp_path"):
                path = job.get(path_key)
                if path:
                    Path(path).unlink(missing_ok=True)


def update_job(job_id: str, **updates: Any) -> None:
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(updates)


def format_info(item: dict[str, Any]) -> dict[str, Any]:
    width = item.get("width")
    height = item.get("height")
    extension = item.get("ext") or "unknown"
    return {
        "format_id": str(item.get("format_id", "")),
        "container": extension,
        "resolution": f"{width}x{height}" if width and height else (item.get("resolution") or "audio only" if item.get("vcodec") == "none" else "Original"),
        "width": width,
        "height": height,
        "filesize_bytes": item.get("filesize") or item.get("filesize_approx"),
        "has_audio": item.get("acodec") not in {None, "none"},
        "has_video": item.get("vcodec") not in {None, "none"},
        "video_codec": None if item.get("vcodec") in {None, "none"} else item.get("vcodec"),
        "audio_codec": None if item.get("acodec") in {None, "none"} else item.get("acodec"),
        "needs_merge": item.get("vcodec") not in {None, "none"} and item.get("acodec") in {None, "none"},
    }


def analyze_url(url: str) -> dict[str, Any]:
    hostname = public_hostname(url)
    direct = direct_format(url)
    if direct:
        return {"source": hostname, "title": None, "duration_seconds": None, "thumbnail_url": None, "drm_status": "unknown", "download_supported": True, "formats": [direct], "default_format_id": direct["format_id"]}
    options = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True, "socket_timeout": 20, "extractor_args": {}}
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        message = str(exc)
        if "DRM" in message.upper() or "protected" in message.lower():
            raise HTTPException(status_code=422, detail="This media appears to be DRM-protected and cannot be downloaded by Fetchly.") from exc
        raise HTTPException(status_code=422, detail="The source could not be analyzed. It may be private, restricted, unavailable, or unsupported.") from exc
    entries = info.get("entries") if info.get("_type") == "playlist" else [info]
    item = next((entry for entry in entries if entry), info)
    formats = [format_info(item_format) for item_format in item.get("formats", []) if item_format.get("vcodec") not in {None, "none"} or item_format.get("acodec") not in {None, "none"}]
    formats = [item_format for item_format in formats if item_format["format_id"]]
    if not formats:
        raise HTTPException(status_code=422, detail="No downloadable formats were reported by this source.")
    combined = [item_format for item_format in formats if item_format["has_video"] and item_format["has_audio"]]
    video_with_merge = [item_format for item_format in formats if item_format["has_video"]]
    default = max(combined or video_with_merge, key=lambda item_format: (item_format["height"] or 0, item_format["filesize_bytes"] or 0))
    return {"source": hostname, "title": item.get("title"), "duration_seconds": item.get("duration"), "thumbnail_url": item.get("thumbnail"), "drm_status": "unknown", "download_supported": True, "formats": formats, "default_format_id": default["format_id"]}


def progress_hook(job_id: str, hook: dict[str, Any]) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise JobCancelled()
        if job["cancel_event"].is_set():
            raise JobCancelled()
    status_value = hook.get("status")
    if status_value == "downloading":
        downloaded = hook.get("downloaded_bytes", 0)
        total = hook.get("total_bytes") or hook.get("total_bytes_estimate")
        update_job(job_id, status="downloading", downloaded_bytes=downloaded, total_bytes=total, speed_bytes_per_second=hook.get("speed"), eta_seconds=hook.get("eta"), progress=round(downloaded / total * 100, 1) if total else None)
    elif status_value == "finished":
        update_job(job_id, status="processing", downloaded_bytes=hook.get("downloaded_bytes", 0))


def download_direct(job_id: str, url: str, extension: str, title: str) -> None:
    temp_path = DOWNLOAD_DIR / f".{job_id}.part"
    update_job(job_id, status="downloading", temp_path=str(temp_path))
    try:
        with httpx.stream("GET", url, follow_redirects=False, timeout=httpx.Timeout(60.0, connect=10.0)) as response:
            response.raise_for_status()
            if response.is_redirect or response.is_permanent_redirect:
                raise ValueError("The media URL redirected. Reanalyze the source before downloading.")
            content_length = int(response.headers.get("content-length", "0"))
            if content_length > MAX_DOWNLOAD_BYTES:
                raise ValueError("The source file exceeds Fetchly's configured size limit.")
            downloaded = 0
            started = time.monotonic()
            with temp_path.open("wb") as target:
                for chunk in response.iter_bytes(1024 * 1024):
                    if jobs[job_id]["cancel_event"].is_set():
                        raise JobCancelled()
                    downloaded += len(chunk)
                    if downloaded > MAX_DOWNLOAD_BYTES:
                        raise ValueError("The download exceeded Fetchly's configured size limit.")
                    target.write(chunk)
                    elapsed = max(time.monotonic() - started, 0.001)
                    speed = downloaded / elapsed
                    update_job(job_id, status="downloading", downloaded_bytes=downloaded, total_bytes=content_length or None, speed_bytes_per_second=speed, eta_seconds=(content_length - downloaded) / speed if content_length and speed else None, progress=round(downloaded / content_length * 100, 1) if content_length else None)
        extension = "webm" if extension == "webm" else "mp4"
        final_path = DOWNLOAD_DIR / safe_filename(title or "fetchly-video", extension)
        counter = 1
        while final_path.exists():
            final_path = DOWNLOAD_DIR / safe_filename(f"{title or 'fetchly-video'} ({counter})", extension)
            counter += 1
        temp_path.replace(final_path)
        update_job(job_id, status="completed", file_path=str(final_path), filename=final_path.name, completed_at=now().isoformat(), progress=100)
    except JobCancelled:
        update_job(job_id, status="cancelled", error_code="cancelled")
    except Exception as exc:
        update_job(job_id, status="failed", error_code="download_failed", error_message=str(exc))
    finally:
        temp_path.unlink(missing_ok=True)


def download_with_ytdlp(job_id: str, url: str, format_id: str, title: str | None) -> None:
    temp_dir = DOWNLOAD_DIR / f".{job_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    update_job(job_id, status="downloading", temp_path=str(temp_dir))
    try:
        approved = jobs[job_id]["analysis"]
        selected = next((item for item in approved["formats"] if item["format_id"] == format_id), None)
        if not selected:
            raise ValueError("The selected format is no longer available.")
        selected_expression = format_id
        if selected["needs_merge"]:
            selected_expression = f"{format_id}+bestaudio/best"
        output_template = str(temp_dir / "%(title).180B [%(id)s].%(ext)s")
        options: dict[str, Any] = {"format": selected_expression, "outtmpl": output_template, "noplaylist": True, "quiet": True, "no_warnings": True, "progress_hooks": [lambda hook: progress_hook(job_id, hook)], "merge_output_format": selected["container"] if selected["container"] in {"mp4", "webm", "mkv"} else "mp4", "restrictfilenames": True, "socket_timeout": 30, "max_filesize": MAX_DOWNLOAD_BYTES}
        if shutil.which("ffmpeg") is None and selected["needs_merge"]:
            raise RuntimeError("FFmpeg is required to combine this video's separate audio and video streams. Install FFmpeg and add it to PATH.")
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.download([url])
        output_files = [path for path in temp_dir.iterdir() if path.is_file() and not path.name.endswith((".part", ".ytdl"))]
        if not output_files:
            raise RuntimeError("The downloader completed without producing a media file.")
        source = output_files[0]
        final_path = DOWNLOAD_DIR / safe_filename(title or source.stem, source.suffix.lstrip("."))
        counter = 1
        while final_path.exists():
            final_path = DOWNLOAD_DIR / safe_filename(f"{title or source.stem} ({counter})", source.suffix.lstrip("."))
            counter += 1
        source.replace(final_path)
        update_job(job_id, status="completed", file_path=str(final_path), filename=final_path.name, completed_at=now().isoformat(), progress=100)
    except JobCancelled:
        update_job(job_id, status="cancelled", error_code="cancelled")
    except yt_dlp.utils.DownloadError as exc:
        update_job(job_id, status="failed", error_code="download_failed", error_message="The source could not be downloaded. It may be unavailable, restricted, or unsupported.")
    except Exception as exc:
        update_job(job_id, status="failed", error_code="download_failed", error_message=str(exc) if "FFmpeg" in str(exc) else "The download could not be completed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_download(job_id: str) -> None:
    job = jobs[job_id]
    try:
        if is_direct(job["url"]):
            extension = Path(urlparse(job["url"]).path).suffix.lower().lstrip(".")
            download_direct(job_id, job["url"], extension, job["analysis"].get("title") or "fetchly-video")
        else:
            download_with_ytdlp(job_id, job["url"], job["format_id"], job["analysis"].get("title"))
    except Exception as exc:
        update_job(job_id, status="failed", error_code="download_failed", error_message=str(exc))


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "fetchly-api"}


@app.post("/api/v1/analyze")
async def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    cleanup_stale_jobs()
    return analyze_url(str(request.url))


@app.post("/api/v1/downloads", status_code=status.HTTP_202_ACCEPTED)
async def create_download(request: DownloadRequest) -> dict[str, Any]:
    cleanup_stale_jobs()
    url = str(request.url)
    public_hostname(url)
    analysis = analyze_url(url)
    if request.format_id not in {item["format_id"] for item in analysis["formats"]}:
        raise HTTPException(status_code=422, detail="The selected format is not part of the approved analysis.")
    with jobs_lock:
        active = sum(job["status"] in {"queued", "downloading", "processing"} for job in jobs.values())
        if active >= MAX_JOBS:
            raise HTTPException(status_code=429, detail="Fetchly is handling the maximum number of concurrent downloads. Try again shortly.")
        job_id = str(uuid.uuid4())
        jobs[job_id] = {"job_id": job_id, "url": url, "format_id": request.format_id, "analysis": analysis, "status": "queued", "progress": 0, "downloaded_bytes": 0, "total_bytes": None, "speed_bytes_per_second": None, "eta_seconds": None, "error_code": None, "error_message": None, "created_at": now(), "cancel_event": threading.Event()}
    executor.submit(run_download, job_id)
    return {"job_id": job_id, "status": "queued", "status_url": f"/api/v1/downloads/{job_id}", "file_url": f"/api/v1/downloads/{job_id}/file"}


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in job.items() if key not in {"analysis", "cancel_event", "temp_path", "file_path"}}
    if job.get("status") == "completed":
        result["file_url"] = f"/api/v1/downloads/{job['job_id']}/file"
    return result


@app.get("/api/v1/downloads/{job_id}")
async def download_status(job_id: str) -> dict[str, Any]:
    cleanup_stale_jobs()
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Download job not found.")
        return public_job(job)


@app.get("/api/v1/downloads/{job_id}/file")
async def download_file(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Download job not found.")
        if job["status"] != "completed" or not job.get("file_path"):
            raise HTTPException(status_code=409, detail="The download is not complete yet.")
        path = Path(job["file_path"]).resolve()
        if DOWNLOAD_DIR not in path.parents:
            raise HTTPException(status_code=404, detail="Download file not found.")
        filename = job.get("filename", path.name)
    return FileResponse(path, filename=filename)


@app.delete("/api/v1/downloads/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_download(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Download job not found.")
        if job["status"] in {"completed", "failed", "cancelled"}:
            return None
        job["cancel_event"].set()
        job["status"] = "cancelled"
    return None
