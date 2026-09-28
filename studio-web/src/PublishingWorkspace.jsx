import React, { useEffect, useMemo, useState } from "react";
import {
  BookOpenText,
  CheckCircle2,
  Download,
  FileAudio,
  FileText,
  Globe2,
  LoaderCircle,
  RefreshCw,
  Rss,
  Save,
  Upload,
} from "lucide-react";

import { api } from "./api.js";

function bytes(value) {
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)} GB`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)} MB`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)} KB`;
  return `${value || 0} B`;
}

function duration(value) {
  const total = Math.max(0, Math.round(value || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function PublishingWorkspace() {
  const [channel, setChannel] = useState(null);
  const [sources, setSources] = useState([]);
  const [episodes, setEpisodes] = useState([]);
  const [takeId, setTakeId] = useState("");
  const [audioId, setAudioId] = useState("");
  const [chapters, setChapters] = useState([]);
  const [form, setForm] = useState({ title: "", description: "", publication_date: "" });
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const selected = sources.find((item) => item.take_id === takeId) || null;
  const audio = selected?.audio_artifacts.find((item) => item.id === audioId) || null;
  const existing = episodes.find((item) => item.take_id === takeId) || null;

  const load = async () => {
    const [nextChannel, nextSources, nextEpisodes] = await Promise.all([
      api.publishingChannel(),
      api.publishingSources(),
      api.publishingEpisodes(),
    ]);
    setChannel(nextChannel);
    setSources(nextSources);
    setEpisodes(nextEpisodes);
    setTakeId((current) => current && nextSources.some((item) => item.take_id === current)
      ? current
      : nextSources[0]?.take_id || "");
  };

  useEffect(() => {
    load().catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!selected) {
      setAudioId("");
      setChapters([]);
      return;
    }
    setAudioId((current) => selected.audio_artifacts.some((item) => item.id === current)
      ? current
      : selected.audio_artifacts[0]?.id || "");
    const published = episodes.find((item) => item.take_id === selected.take_id);
    setForm({
      title: published?.title || selected.project_name,
      description: published?.description || "",
      publication_date: published?.publication_date?.slice(0, 10) || "",
    });
    api.publishingChapters(selected.take_id)
      .then(setChapters)
      .catch((reason) => setError(reason.message));
  }, [selected?.take_id, episodes]);

  const channelReady = Boolean(channel?.media_base_url);
  const chapterSummary = useMemo(() => {
    if (!chapters.length) return "No Markdown headings detected";
    return `${chapters.length} chapter${chapters.length === 1 ? "" : "s"} detected`;
  }, [chapters]);

  const saveChannel = async () => {
    setBusy("channel");
    setError("");
    setNotice("");
    try {
      setChannel(await api.savePublishingChannel(channel));
      setNotice("Channel settings saved and the local feed was rebuilt.");
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };

  const exportTranscript = async () => {
    if (!selected) return;
    setBusy("transcript");
    setError("");
    try {
      const result = await api.exportPublishingTranscript(selected.take_id);
      window.location.assign(result.download_url);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };

  const publish = async () => {
    if (!selected || !audio) return;
    setBusy("publish");
    setError("");
    setNotice("");
    try {
      const episode = await api.publishEpisode({
        take_id: selected.take_id,
        audio_artifact_id: audio.id,
        title: form.title,
        description: form.description,
        publication_date: form.publication_date || null,
      });
      setEpisodes((current) => [episode, ...current.filter((item) => item.id !== episode.id)]);
      setNotice(existing
        ? "Episode updated. Its episode number and stable feed identity were preserved."
        : "Episode published into the local feed workspace.");
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };

  if (!channel) {
    return <main className="publishing-workspace"><section className="surface publishing-loading"><LoaderCircle className="spin" /><p>Loading publishing workspace…</p></section></main>;
  }

  return (
    <main className="publishing-workspace">
      <header className="workspace-header publishing-header">
        <div><p className="eyebrow">Local delivery</p><h1>Publish</h1><p>Build transcripts, chapters, a podcast-ready media folder, and RSS without uploading anything.</p></div>
        <a className="secondary-button" href="/v1/studio/publishing/feed" download><Rss size={16} />Download feed</a>
      </header>

      <div className="publishing-local-note"><Globe2 size={18} /><span><strong>Local build only</strong>No files or metadata leave this computer. The media base URL tells feed readers where you intend to host the exported folder.</span></div>
      {error && <p className="inline-error">{error}</p>}
      {notice && <p className="publishing-notice"><CheckCircle2 size={16} />{notice}</p>}

      <div className="publishing-layout">
        <div className="publishing-main-stack">
          <section className="surface publishing-source">
            <div className="section-heading"><div><p className="eyebrow">01 · Source</p><h2>Choose a completed take</h2></div><FileAudio size={20} /></div>
            {sources.length ? (
              <div className="publishing-source-grid">
                <label className="control"><span>Project and take</span><select value={takeId} onChange={(event) => setTakeId(event.target.value)}>{sources.map((item) => <option key={item.take_id} value={item.take_id}>{item.project_name} · {item.take_label}</option>)}</select></label>
                <label className="control"><span>Audio artifact</span><select value={audioId} onChange={(event) => setAudioId(event.target.value)}>{selected?.audio_artifacts.map((item) => <option key={item.id} value={item.id}>{item.name} · {bytes(item.size_bytes)}</option>)}</select></label>
              </div>
            ) : <div className="publishing-empty"><FileAudio size={24} /><strong>No completed audio takes yet</strong><span>Finish a narration or conversion first.</span></div>}
          </section>

          <section className="surface publishing-episode-editor">
            <div className="section-heading"><div><p className="eyebrow">02 · Episode</p><h2>Describe this release</h2></div><Upload size={20} /></div>
            <div className="publishing-fields">
              <label className="control"><span>Episode title</span><input value={form.title} maxLength="500" onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} /></label>
              <label className="control"><span>Publication date</span><input type="date" value={form.publication_date} onChange={(event) => setForm((current) => ({ ...current, publication_date: event.target.value }))} /></label>
              <label className="control wide"><span>Show notes</span><textarea rows="5" value={form.description} maxLength="50000" onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} placeholder="A concise summary for listeners…" /></label>
            </div>
            <div className="publishing-actions">
              <span>{existing ? `Updates episode ${existing.episode_number}` : "Creates the next numbered episode"}</span>
              <button className="secondary-button" type="button" disabled={!selected || !!busy} onClick={exportTranscript}><FileText size={16} />{busy === "transcript" ? "Exporting…" : "Export transcript"}</button>
              <button className="primary-button" type="button" disabled={!selected || !audio || !form.title.trim() || !channelReady || !!busy} onClick={publish}>{busy === "publish" ? <LoaderCircle className="spin" size={16} /> : <Rss size={16} />}{existing ? "Update episode" : "Publish locally"}</button>
            </div>
            {!channelReady && <small className="publishing-requirement">Save a public media base URL in Channel settings before publishing.</small>}
          </section>
        </div>

        <aside className="publishing-side-stack">
          <section className="surface publishing-channel">
            <div className="section-heading compact"><div><p className="eyebrow">Channel</p><h2>Feed identity</h2></div><Rss size={18} /></div>
            <label className="control"><span>Channel title</span><input value={channel.title} onChange={(event) => setChannel({ ...channel, title: event.target.value })} /></label>
            <label className="control"><span>Description</span><textarea rows="3" value={channel.description} onChange={(event) => setChannel({ ...channel, description: event.target.value })} /></label>
            <div className="publishing-channel-pair"><label className="control"><span>Author</span><input value={channel.author} onChange={(event) => setChannel({ ...channel, author: event.target.value })} /></label><label className="control"><span>Language</span><input value={channel.language} onChange={(event) => setChannel({ ...channel, language: event.target.value })} /></label></div>
            <label className="control"><span>Public media base URL</span><input type="url" value={channel.media_base_url} onChange={(event) => setChannel({ ...channel, media_base_url: event.target.value })} placeholder="https://example.com/podcast" /><small>Feed enclosure paths are built beneath this URL.</small></label>
            <label className="control"><span>Website URL</span><input type="url" value={channel.website_url} onChange={(event) => setChannel({ ...channel, website_url: event.target.value })} /></label>
            <label className="control"><span>Artwork URL</span><input type="url" value={channel.artwork_url} onChange={(event) => setChannel({ ...channel, artwork_url: event.target.value })} /></label>
            <div className="publishing-channel-pair"><label className="control"><span>Category</span><input value={channel.category} onChange={(event) => setChannel({ ...channel, category: event.target.value })} /></label><label className="check-control publishing-explicit"><input type="checkbox" checked={channel.explicit} onChange={(event) => setChannel({ ...channel, explicit: event.target.checked })} /><span><strong>Explicit</strong><small>Mark the feed</small></span></label></div>
            <button className="secondary-button publishing-save" type="button" disabled={!!busy || !channel.title.trim() || !channel.description.trim()} onClick={saveChannel}>{busy === "channel" ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}Save channel</button>
          </section>

          <section className="surface publishing-chapters">
            <div className="section-heading compact"><div><p className="eyebrow">Detected structure</p><h2>Chapters</h2></div><BookOpenText size={18} /></div>
            <p>{chapterSummary}</p>
            <ol>{chapters.slice(0, 12).map((chapter, index) => <li key={`${chapter.seconds}-${chapter.title}-${index}`}><time>{duration(chapter.seconds)}</time><span>{chapter.title}</span><i>H{chapter.level}</i></li>)}</ol>
            {chapters.length > 12 && <small>+ {chapters.length - 12} more chapters</small>}
          </section>

          <section className="surface publishing-history">
            <div className="section-heading compact"><div><p className="eyebrow">Feed contents</p><h2>{episodes.length} episodes</h2></div><RefreshCw size={18} /></div>
            {episodes.length ? episodes.slice().sort((a, b) => b.episode_number - a.episode_number).map((episode) => <article key={episode.id}><span><strong>{episode.episode_number}. {episode.title}</strong><small>{duration(episode.duration_seconds)} · {bytes(episode.media_size_bytes)}</small></span><a href={episode.media_url} download aria-label={`Download ${episode.title}`}><Download size={15} /></a></article>) : <p>No episodes in this feed yet.</p>}
          </section>
        </aside>
      </div>
    </main>
  );
}
