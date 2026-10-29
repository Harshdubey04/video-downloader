# Fetchly

Fetchly is a local video downloader for authorized, non-DRM media. It uses
Next.js for the web UI and FastAPI for the API service, with yt-dlp handling
compatible public video pages and direct media URLs saved to the local machine.

## Supported sources and limitations

Fetchly supports publicly reachable direct URLs ending in:

- `.mp4`, served as an MP4 download
- `.webm`, served as a WebM download
- `.m4v` and `.mov`, normalized to the MP4 format choice

Video-page URLs are analyzed through yt-dlp, so support follows the extractors
available in the installed yt-dlp release. YouTube, Vimeo, TikTok, Instagram,
Facebook, and many other public platforms may work when the extractor can
access the content without a login or DRM. A platform name is not a guarantee
that every URL works.

DRM-protected media, private or login-gated content, paywalls, unsupported
extractors, and unavailable formats are rejected with an actionable error.
Fetchly does not bypass access controls. Separate video and audio streams are
merged locally when FFmpeg is installed.

Downloads are saved to `%USERPROFILE%\Downloads\Fetchly` by default. Override
this with `FETCHLY_DOWNLOAD_DIR`. Jobs are held in memory for the local process
and stale completed metadata/files are cleaned after 24 hours.

## Local development

```powershell
npm install
npm run dev
```

In another terminal:

```powershell
python -m pip install -r backend\requirements.txt
python -m uvicorn backend.app.main:app --reload --port 8000
```

Install [FFmpeg](https://ffmpeg.org/download.html) and add its `bin` directory
to `PATH` for formats that require audio/video merging. Direct files and
formats that already contain audio can work without FFmpeg.

The frontend defaults to `http://localhost:8000`; set
`NEXT_PUBLIC_API_URL` to use another API host.

## API

- `GET /api/v1/health`
- `POST /api/v1/analyze`
- `POST /api/v1/downloads`
- `GET /api/v1/downloads/{job_id}`
- `GET /api/v1/downloads/{job_id}/file`
- `DELETE /api/v1/downloads/{job_id}`

## Testing

The frontend checks are run with:

```powershell
npm test
npm run build
```

The backend can be syntax-checked with:

```powershell
python -m compileall backend\app
```

To test a real public platform, use content you own or are authorized to
download and check the API response before starting a download. Extractor
availability, geo restrictions, rate limits, and platform changes can affect
results.
