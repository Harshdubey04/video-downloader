from __future__ import annotations

import ipaddress
import os
import socket
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, HttpUrl

app = FastAPI(title="Fetchly API", version="1.0.0")
jobs: dict[str, dict[str, str]] = {}


class AnalyzeRequest(BaseModel):
    url: HttpUrl


class DownloadRequest(BaseModel):
    url: HttpUrl
    format_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Only HTTP and HTTPS URLs are supported.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "metadata.google.internal"}:
        raise HTTPException(status_code=400, detail="This destination is not allowed.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="The URL hostname could not be resolved.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise HTTPException(status_code=400, detail="Private and internal network destinations are not allowed.")
    return hostname


def direct_format(url: str, content_type: str | None = None) -> dict | None:
    path = urlparse(url).path.lower()
    extension = os.path.splitext(path)[1].lstrip(".")
    if extension not in {"mp4", "webm", "m4v", "mov"}:
        return None
    container = "webm" if extension == "webm" else "mp4"
    return {"format_id": f"direct-{extension}", "container": container, "resolution": None, "filesize_bytes": None, "has_audio": True, "video_codec": None, "audio_codec": None}


@app.get("/api/v1/health")
async def health() -> dict:
    return {"status": "ok", "service": "fetchly-api"}


@app.post("/api/v1/analyze")
async def analyze(request: AnalyzeRequest) -> dict:
    hostname = validate_public_url(str(request.url))
    media_format = direct_format(str(request.url))
    if not media_format:
        raise HTTPException(status_code=422, detail="This source is not supported. Use a direct MP4 or WebM media URL.")
    return {"source": hostname, "title": None, "duration_seconds": None, "thumbnail_url": None, "drm_status": "unknown", "download_supported": True, "formats": [media_format]}


@app.post("/api/v1/downloads", status_code=status.HTTP_202_ACCEPTED)
async def create_download(request: DownloadRequest) -> dict:
    hostname = validate_public_url(str(request.url))
    media_format = direct_format(str(request.url))
    if not media_format or media_format["format_id"] != request.format_id:
        raise HTTPException(status_code=422, detail="The selected format is not approved for this URL.")
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"url": str(request.url), "format_id": request.format_id}
    return {"job_id": job_id, "status": "queued", "status_url": f"/api/v1/downloads/{job_id}", "file_url": f"/api/v1/downloads/{job_id}/file", "source": hostname}


@app.get("/api/v1/downloads/{job_id}")
async def download_status(job_id: str) -> dict:
    try:
        uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Download job not found.") from exc
    return {"job_id": job_id, "status": "queued", "progress": None, "error_code": None, "created_at": datetime.now(timezone.utc).isoformat(), "expires_at": None}


@app.get("/api/v1/downloads/{job_id}/file")
async def download_file(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Download job not found.")
    source_url = job["url"]
    validate_public_url(source_url)

    async def stream():
        async with httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            response = await client.get(source_url)
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                yield chunk

    extension = urlparse(source_url).path.rsplit(".", 1)[-1].lower()
    media_type = "video/webm" if extension == "webm" else "video/mp4"
    return StreamingResponse(stream(), media_type=media_type, headers={"Content-Disposition": f'attachment; filename="fetchly-{job_id}.{extension}"'})


@app.delete("/api/v1/downloads/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_download(job_id: str):
    jobs.pop(job_id, None)
    return None
