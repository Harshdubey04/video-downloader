# Fetchly

Fetchly is a small full-stack starter for inspecting and downloading authorized,
non-DRM direct media URLs. It uses Next.js for the web UI and FastAPI for the
API service.

## Supported sources and limitations

The initial adapter supports publicly reachable direct URLs ending in:

- `.mp4`, served as an MP4 download
- `.webm`, served as a WebM download
- `.m4v` and `.mov`, normalized to the MP4 format choice

The analyzer does not claim that a website is supported merely because its
domain is recognized. HLS/DASH manifests, DRM-protected media, login-gated
content, private network destinations, cloud metadata endpoints, and arbitrary
website pages are rejected. A future adapter can add an authorized provider
integration without changing the API contract.

This starter streams an approved direct media URL after a validated job is
created. Production deployment should replace the in-memory job store with
PostgreSQL and Redis/Celery, persist analysis snapshots, store results in
private S3-compatible storage, add user authentication, enforce rate limits,
and implement revalidation for every redirect and connection.

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

The frontend defaults to `http://localhost:8000`; set
`NEXT_PUBLIC_API_URL` to use another API host.

## API

- `GET /api/v1/health`
- `POST /api/v1/analyze`
- `POST /api/v1/downloads`
- `GET /api/v1/downloads/{job_id}`
- `GET /api/v1/downloads/{job_id}/file`
- `DELETE /api/v1/downloads/{job_id}`
