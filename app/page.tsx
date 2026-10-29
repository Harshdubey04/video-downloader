"use client";

import { FormEvent, useEffect, useState } from "react";
import { ArrowDownToLine, Check, Clipboard, Clock3, Download, FileVideo, Link2, Loader2, ShieldCheck, Sparkles, TriangleAlert } from "lucide-react";

type Format = {
  format_id: string;
  container: string;
  resolution: string | null;
  filesize_bytes: number | null;
  has_audio: boolean;
  video_codec?: string | null;
  audio_codec?: string | null;
  has_video?: boolean;
  needs_merge?: boolean;
};

type Analysis = {
  source: string;
  title: string | null;
  duration_seconds: number | null;
  thumbnail_url: string | null;
  drm_status: "clear" | "unknown" | "detected";
  download_supported: boolean;
  formats: Format[];
  default_format_id: string;
};

type DownloadJob = {
  job_id: string;
  status: "queued" | "downloading" | "processing" | "completed" | "failed" | "cancelled";
  progress: number | null;
  downloaded_bytes: number;
  total_bytes: number | null;
  speed_bytes_per_second: number | null;
  eta_seconds: number | null;
  filename?: string;
  error_message?: string | null;
  file_url?: string;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function formatDuration(seconds: number | null) {
  if (seconds === null) return "Duration unavailable";
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

function formatSize(bytes: number | null | undefined) {
  if (bytes === null) return "Size unavailable";
  if (!bytes) return "Size unavailable";
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatSpeed(bytes: number | null) {
  if (!bytes) return "";
  return `${(bytes / 1024 / 1024).toFixed(1)} MB/s`;
}

function formatEta(seconds: number | null) {
  if (!seconds) return "";
  return `${Math.ceil(seconds)}s remaining`;
}

export default function Home() {
  const [url, setUrl] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [job, setJob] = useState<DownloadJob | null>(null);
  const activeJobId = job?.job_id;
  const activeJobStatus = job?.status;

  useEffect(() => {
    if (!activeJobId || !activeJobStatus || !["queued", "downloading", "processing"].includes(activeJobStatus)) return;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API_URL}/api/v1/downloads/${activeJobId}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail ?? "Could not read download status.");
        setJob(data);
        if (data.status === "failed") setError(data.error_message ?? "The download failed.");
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Could not read download status.");
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [activeJobId, activeJobStatus]);

  async function pasteUrl() {
    const text = await navigator.clipboard.readText();
    setUrl(text);
    setError("");
  }

  async function analyze(event: FormEvent) {
    event.preventDefault();
    setError("");
    setAnalysis(null);
    setLoading(true);
    try {
      const response = await fetch(`${API_URL}/api/v1/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "We could not analyze that URL.");
      setAnalysis(data);
      setSelected(data.default_format_id ?? data.formats[0]?.format_id ?? "");
    } catch (reason) {
      setError(reason instanceof TypeError ? "Cannot reach the Fetchly API. Start the backend on port 8000 and try again." : reason instanceof Error ? reason.message : "Analysis failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  async function startDownload() {
    if (!analysis || !selected) return;
    setError("");
    setJob(null);
    try {
      const response = await fetch(`${API_URL}/api/v1/downloads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, format_id: selected })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Download could not be queued.");
      setJob(data);
    } catch (reason) {
      setError(reason instanceof TypeError ? "Cannot reach the Fetchly API. Start the backend on port 8000 and try again." : reason instanceof Error ? reason.message : "Download failed. Please try again.");
    }
  }

  async function cancelDownload() {
    if (!job) return;
    try {
      const response = await fetch(`${API_URL}/api/v1/downloads/${job.job_id}`, { method: "DELETE" });
      if (!response.ok) throw new Error("The download could not be cancelled.");
      setJob({ ...job, status: "cancelled" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Cancellation failed.");
    }
  }

  return (
    <main>
      <nav className="nav shell">
        <a className="brand" href="/"><span className="brand-mark"><ArrowDownToLine size={18} /></span>fetchly</a>
        <div className="nav-links"><a href="#supported">Supported sources</a><a href="#how-it-works">How it works</a><a className="nav-button" href="#privacy">Privacy first</a></div>
      </nav>

      <section className="hero shell">
        <div className="eyebrow"><Sparkles size={15} /> Simple, fast, privacy-minded</div>
        <h1>Download videos.<br /><span>Your way.</span></h1>
        <p className="hero-copy">Inspect available media formats from supported sources and download authorized, non-DRM content in the quality you choose.</p>
        <form className="url-card" onSubmit={analyze}>
          <div className="url-input"><Link2 size={20} /><input aria-label="Video URL" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="Paste a video URL to get started" type="url" required /><button type="button" className="paste-button" onClick={pasteUrl}><Clipboard size={16} /> Paste</button></div>
          <button className="analyze-button" disabled={loading} type="submit">{loading ? <Loader2 className="spin" size={18} /> : <Download size={18} />} {loading ? "Analyzing..." : "Analyze video"}</button>
        </form>
        {error && <div className="alert error"><TriangleAlert size={18} />{error}</div>}
        <div className="trust-row"><span><ShieldCheck size={16} /> No account required</span><span><ShieldCheck size={16} /> Private by design</span><span><ShieldCheck size={16} /> Expiring links</span></div>
      </section>

      {analysis && (
        <section className="result-shell shell" aria-live="polite">
          <div className="section-label"><Check size={16} /> Analysis complete</div>
          <div className="result-grid">
            <div className="preview">{analysis.thumbnail_url ? <div className="preview-image" aria-label="Video thumbnail" role="img" style={{ backgroundImage: `url("${analysis.thumbnail_url}")` }} /> : <div className="preview-icon"><FileVideo size={38} /></div>}<div><span className="source-tag">{analysis.source}</span><h2>{analysis.title ?? "Untitled video"}</h2><p><Clock3 size={15} /> {formatDuration(analysis.duration_seconds)}</p></div></div>
            <div className="format-panel"><label htmlFor="format">Choose a format</label><select id="format" value={selected} onChange={(event) => setSelected(event.target.value)}>{analysis.formats.map((format) => <option key={format.format_id} value={format.format_id}>{format.container.toUpperCase()} · {format.resolution ?? "Original"} · {formatSize(format.filesize_bytes)}{format.has_audio ? "" : " · audio merge required"}</option>)}</select><button className="download-button" onClick={startDownload} disabled={!selected || !analysis.download_supported || Boolean(job && ["queued", "downloading", "processing"].includes(job.status))}><ArrowDownToLine size={18} /> {job && ["queued", "downloading", "processing"].includes(job.status) ? "Downloading..." : "Download selected format"}</button>{analysis.drm_status === "detected" && <p className="notice"><TriangleAlert size={15} /> DRM-protected media requires an official provider workflow.</p>}</div>
          </div>
        </section>
      )}

      {job && <section className="job-card shell" aria-live="polite">
        <div className="job-heading"><div><span className="kicker">Download status</span><h2>{job.status === "completed" ? "Your file is ready" : job.status === "failed" ? "Download failed" : job.status === "cancelled" ? "Download cancelled" : "Preparing your download"}</h2></div><span className={`status-pill ${job.status}`}>{job.status}</span></div>
        {["queued", "downloading", "processing"].includes(job.status) && <><div className="progress-track"><div className="progress-value" style={{ width: `${job.progress ?? 0}%` }} /></div><div className="job-meta"><span>{job.progress === null ? "Working..." : `${job.progress}%`}</span><span>{formatSize(job.downloaded_bytes)} {formatSpeed(job.speed_bytes_per_second)} {formatEta(job.eta_seconds)}</span></div><button className="cancel-button" onClick={cancelDownload}>Cancel download</button></>}
        {job.status === "completed" && job.file_url && <div className="success-row"><Check size={18} /> <span>{job.filename}</span><a className="download-button" href={`${API_URL}${job.file_url}`} download><ArrowDownToLine size={17} /> Save file</a></div>}
        {job.status === "failed" && <p className="notice"><TriangleAlert size={15} /> {job.error_message ?? "The download could not be completed."}</p>}
      </section>}

      <section className="feature-section shell" id="how-it-works"><div className="section-heading"><span className="kicker">Made for the web</span><h2>A better way to save what matters.</h2><p>Clear information, no guesswork. Fetchly only offers formats reported by the source.</p></div><div className="feature-grid"><article><div className="feature-icon purple"><FileVideo size={21} /></div><h3>See before you save</h3><p>Review resolution, codecs, audio, duration, and approximate size before choosing a format.</p></article><article><div className="feature-icon peach"><ShieldCheck size={21} /></div><h3>Built with boundaries</h3><p>Private destinations, DRM content, and unsupported sources are blocked rather than silently attempted.</p></article><article><div className="feature-icon mint"><Clock3 size={21} /></div><h3>Links that expire</h3><p>Completed files are temporary and securely served through short-lived download links.</p></article></div></section>
      <section className="supported shell" id="supported"><div><span className="kicker">Supported sources</span><h2>Start with a direct media URL</h2><p>Fetchly supports direct MP4 and WebM media and carefully selected public extractors. Source support can change; the analyzer always has the final say.</p></div><div className="source-list"><span>MP4</span><span>WebM</span><span>Authorized public media</span></div></section>
      <footer className="footer shell" id="privacy"><span className="brand">fetchly</span><span>For content you own or are authorized to download.</span><span>Privacy · Terms · Contact</span></footer>
    </main>
  );
}
