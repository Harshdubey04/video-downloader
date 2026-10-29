"use client";

import { FormEvent, useState } from "react";
import { ArrowDownToLine, Check, Clipboard, Clock3, Download, FileVideo, Link2, Loader2, ShieldCheck, Sparkles, TriangleAlert } from "lucide-react";

type Format = {
  format_id: string;
  container: string;
  resolution: string | null;
  filesize_bytes: number | null;
  has_audio: boolean;
  video_codec?: string | null;
  audio_codec?: string | null;
};

type Analysis = {
  source: string;
  title: string | null;
  duration_seconds: number | null;
  thumbnail_url: string | null;
  drm_status: "clear" | "unknown" | "detected";
  download_supported: boolean;
  formats: Format[];
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function formatDuration(seconds: number | null) {
  if (seconds === null) return "Duration unavailable";
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

function formatSize(bytes: number | null) {
  if (bytes === null) return "Size unavailable";
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function Home() {
  const [url, setUrl] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

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
      setSelected(data.formats[0]?.format_id ?? "");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Analysis failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  async function startDownload() {
    if (!analysis || !selected) return;
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/v1/downloads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, format_id: selected })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Download could not be queued.");
      window.location.href = `${API_URL}${data.file_url}`;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Download failed. Please try again.");
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
            <div className="preview"><div className="preview-icon"><FileVideo size={38} /></div><div><span className="source-tag">{analysis.source}</span><h2>{analysis.title ?? "Untitled video"}</h2><p><Clock3 size={15} /> {formatDuration(analysis.duration_seconds)}</p></div></div>
            <div className="format-panel"><label htmlFor="format">Choose a format</label><select id="format" value={selected} onChange={(event) => setSelected(event.target.value)}>{analysis.formats.map((format) => <option key={format.format_id} value={format.format_id}>{format.container.toUpperCase()} · {format.resolution ?? "Original"} · {formatSize(format.filesize_bytes)}{format.has_audio ? "" : " · video only"}</option>)}</select><button className="download-button" onClick={startDownload} disabled={!selected || !analysis.download_supported}><ArrowDownToLine size={18} /> Download selected format</button>{analysis.drm_status === "detected" && <p className="notice"><TriangleAlert size={15} /> DRM-protected media requires an official provider workflow.</p>}</div>
          </div>
        </section>
      )}

      <section className="feature-section shell" id="how-it-works"><div className="section-heading"><span className="kicker">Made for the web</span><h2>A better way to save what matters.</h2><p>Clear information, no guesswork. Fetchly only offers formats reported by the source.</p></div><div className="feature-grid"><article><div className="feature-icon purple"><FileVideo size={21} /></div><h3>See before you save</h3><p>Review resolution, codecs, audio, duration, and approximate size before choosing a format.</p></article><article><div className="feature-icon peach"><ShieldCheck size={21} /></div><h3>Built with boundaries</h3><p>Private destinations, DRM content, and unsupported sources are blocked rather than silently attempted.</p></article><article><div className="feature-icon mint"><Clock3 size={21} /></div><h3>Links that expire</h3><p>Completed files are temporary and securely served through short-lived download links.</p></article></div></section>
      <section className="supported shell" id="supported"><div><span className="kicker">Supported sources</span><h2>Start with a direct media URL</h2><p>Fetchly supports direct MP4 and WebM media and carefully selected public extractors. Source support can change; the analyzer always has the final say.</p></div><div className="source-list"><span>MP4</span><span>WebM</span><span>Authorized public media</span></div></section>
      <footer className="footer shell" id="privacy"><span className="brand">fetchly</span><span>For content you own or are authorized to download.</span><span>Privacy · Terms · Contact</span></footer>
    </main>
  );
}
