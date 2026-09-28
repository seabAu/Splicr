import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  BookMarked,
  CheckCircle2,
  FileAudio,
  Plus,
  Replace,
  Save,
  Search,
  Trash2,
} from "lucide-react";

import { api } from "./api.js";

function Message({ kind = "info", children }) {
  if (!children) return null;
  return <div className={`language-message ${kind}`}>{children}</div>;
}

function PronunciationPanel() {
  const [saved, setSaved] = useState([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [word, setWord] = useState("");
  const [respelling, setRespelling] = useState("");
  const [current, setCurrent] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [toolStatus, setToolStatus] = useState(null);

  const reload = async () => {
    const entries = await api.pronunciations();
    setSaved(entries);
    return entries;
  };

  useEffect(() => {
    Promise.all([reload(), api.pronunciationStatus()])
      .then(([, status]) => setToolStatus(status))
      .catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    if (toolStatus === null) return undefined;
    if (!trimmed) {
      setResults(saved.map((entry) => ({ ...entry, phonemes: entry.ipa, source: "override" })));
      return undefined;
    }
    if (toolStatus?.available === false) {
      setResults(saved
        .filter((entry) => entry.word.includes(trimmed.toLowerCase()))
        .map((entry) => ({ ...entry, phonemes: entry.ipa, source: "override" })));
      return undefined;
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const response = await api.pronunciationSearch(trimmed);
        if (!cancelled) {
          setResults(response.matches || []);
          setError(response.error || "");
        }
      } catch (reason) {
        if (!cancelled) {
          setResults(saved
            .filter((entry) => entry.word.includes(trimmed.toLowerCase()))
            .map((entry) => ({ ...entry, phonemes: entry.ipa, source: "override" })));
          setError(reason.message);
        }
      }
    }, 280);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, saved, toolStatus?.available]);

  useEffect(() => {
    const value = respelling.trim();
    if (toolStatus === null) return undefined;
    if (!value || toolStatus?.available === false) {
      setPreview(null);
      return undefined;
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const response = await api.pronunciationPreview(value);
        if (!cancelled) {
          setPreview(response);
          if (response.failed) setError(`Kokoro does not recognize “${response.failed}”.`);
        }
      } catch (reason) {
        if (!cancelled) {
          setPreview(null);
          setError(reason.message);
        }
      }
    }, 320);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [respelling, toolStatus?.available]);

  const selectWord = async (selectedWord) => {
    const normalized = selectedWord.trim().toLowerCase();
    if (!normalized) return;
    setWord(normalized);
    setNotice("");
    setError("");
    const override = saved.find((entry) => entry.word === normalized);
    setRespelling(override?.respelling || "");
    if (toolStatus?.available === false) {
      setCurrent(override ? {
        word: normalized,
        phonemes: override.ipa,
        source: "override",
        error: null,
      } : null);
      return;
    }
    setBusy("check");
    try {
      setCurrent(await api.pronunciationWord(normalized));
    } catch (reason) {
      setCurrent(override ? {
        word: normalized,
        phonemes: override.ipa,
        source: "override",
        error: null,
      } : null);
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };

  const save = async () => {
    if (!word.trim() || !respelling.trim()) return;
    setBusy("save");
    setError("");
    setNotice("");
    try {
      const entry = await api.savePronunciation(word.trim().toLowerCase(), respelling.trim());
      await reload();
      setCurrent({ word: entry.word, phonemes: entry.ipa, source: "override", error: null });
      setNotice(`Saved ${entry.word}. New jobs will use this pronunciation.`);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };

  const remove = async () => {
    if (!saved.some((entry) => entry.word === word)) return;
    setBusy("delete");
    setError("");
    try {
      await api.deletePronunciation(word);
      await reload();
      setRespelling("");
      setPreview(null);
      setCurrent(null);
      setNotice(`Removed the override for ${word}.`);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };

  const isSaved = saved.some((entry) => entry.word === word);
  return (
    <div className="language-grid">
      <section className="surface language-browser">
        <div className="section-heading compact">
          <div><p className="eyebrow">Kokoro lexicon</p><h2>Find a word</h2></div>
          <span>{saved.length} custom</span>
        </div>
        <label className="language-search">
          <Search size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && selectWord(query)}
            placeholder="Search, or type any word…"
          />
          <button onClick={() => selectWord(query)} disabled={!toolStatus?.available || !query.trim() || busy === "check"}>
            Check
          </button>
        </label>
        <p className="language-hint">
          You can inspect any word, including names and terms missing from Kokoro’s dictionary.
        </p>
        <div className="lexicon-list">
          {results.length ? results.map((entry) => (
            <button
              key={entry.word}
              className={word === entry.word ? "active" : ""}
              onClick={() => selectWord(entry.word)}
            >
              <span><strong>{entry.word}</strong><small>{entry.phonemes}</small></span>
              <i className={entry.source}>{entry.source}</i>
            </button>
          )) : (
            <div className="language-empty"><BookMarked size={24} /><span>Type a word to search Kokoro.</span></div>
          )}
        </div>
      </section>

      <section className="surface pronunciation-editor">
        <div className="section-heading">
          <div><p className="eyebrow">Pronunciation editor</p><h2>{word || "Choose a word"}</h2></div>
          <FileAudio size={20} />
        </div>
        <Message kind="error">{error}</Message>
        {toolStatus?.available === false && <Message>{toolStatus.message}</Message>}
        <Message kind="success">{notice}</Message>
        <div className="phoneme-comparison">
          <div>
            <span>Current output</span>
            <strong>{current?.phonemes || "—"}</strong>
            <small>{current?.source ? `From ${current.source}` : current?.error || "Check a word to inspect it."}</small>
          </div>
          <ArrowRight size={18} />
          <div className={preview?.failed ? "invalid" : ""}>
            <span>New output</span>
            <strong>{preview?.ipa || "—"}</strong>
            <small>{preview?.failed ? `Unknown piece: ${preview.failed}` : "Live preview from the respelling below."}</small>
          </div>
        </div>
        <label className="control">
          <span>Word to override</span>
          <input value={word} onChange={(event) => setWord(event.target.value.toLowerCase())} placeholder="narrativizing" />
        </label>
        <label className="control">
          <span>Write it the way it should sound</span>
          <input value={respelling} onChange={(event) => setRespelling(event.target.value)} placeholder="narrative *eye zing" />
          <small>Use ordinary words or syllables Kokoro already knows. Prefix the stressed piece with *.</small>
        </label>
        <div className="language-example">
          <span>Example</span>
          <code>an on nim *my nation</code>
          <small>Each piece keeps its sound; the starred piece receives primary stress.</small>
        </div>
        <div className="language-actions">
          <button className="primary-button" onClick={save} disabled={!toolStatus?.available || !word.trim() || !respelling.trim() || !!preview?.failed || !!busy}>
            <Save size={16} />{busy === "save" ? "Saving…" : "Save pronunciation"}
          </button>
          <button className="secondary-button danger" onClick={remove} disabled={!isSaved || !!busy}>
            <Trash2 size={15} />Remove override
          </button>
        </div>
        <p className="snapshot-note"><CheckCircle2 size={15} />Each new Kokoro take snapshots these overrides, so resumed work remains consistent.</p>
      </section>
    </div>
  );
}

function SubstitutionPanel() {
  const [items, setItems] = useState({});
  const [source, setSource] = useState("");
  const [replacement, setReplacement] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const entries = useMemo(() => Object.entries(items).sort(([left], [right]) => left.localeCompare(right)), [items]);
  const reload = async () => setItems(await api.substitutions());
  useEffect(() => { reload().catch((reason) => setError(reason.message)); }, []);

  const edit = (from, to) => {
    setSource(from);
    setReplacement(to);
    setMessage("");
  };
  const save = async () => {
    if (!source.trim() || !replacement.trim()) return;
    setBusy(true);
    setError("");
    try {
      setItems(await api.saveSubstitution(source, replacement));
      setMessage(`Saved “${source}” → “${replacement}”.`);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async (value = source) => {
    if (!value) return;
    setBusy(true);
    setError("");
    try {
      await api.deleteSubstitution(value);
      await reload();
      if (source === value) {
        setSource("");
        setReplacement("");
      }
      setMessage(`Removed “${value}”.`);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="language-grid">
      <section className="surface language-browser">
        <div className="section-heading compact">
          <div><p className="eyebrow">All engines</p><h2>Saved substitutions</h2></div>
          <span>{entries.length} rules</span>
        </div>
        <button className="secondary-button language-new" onClick={() => edit("", "")}><Plus size={15} />New substitution</button>
        <div className="substitution-list">
          {entries.length ? entries.map(([from, to]) => (
            <button key={from} onClick={() => edit(from, to)} className={source === from ? "active" : ""}>
              <span><strong>{from}</strong><small>{to}</small></span><ArrowRight size={15} />
            </button>
          )) : <div className="language-empty"><Replace size={24} /><span>No substitutions yet.</span></div>}
        </div>
      </section>
      <section className="surface pronunciation-editor">
        <div className="section-heading"><div><p className="eyebrow">Text preparation</p><h2>Permanent substitution</h2></div><Replace size={20} /></div>
        <Message kind="error">{error}</Message>
        <Message kind="success">{message}</Message>
        <p className="language-intro">Rewrite exact words or phrases before SPLICR splits the document. Rules are case-insensitive, match whole words, and apply to local and remote engines.</p>
        <label className="control"><span>When the source contains</span><input value={source} onChange={(event) => setSource(event.target.value)} placeholder="Dr." /></label>
        <label className="control"><span>Speak this instead</span><input value={replacement} onChange={(event) => setReplacement(event.target.value)} placeholder="Doctor" /></label>
        <div className="substitution-preview"><span>Preview</span><strong>{source || "Original text"}<ArrowRight size={16} />{replacement || "Spoken text"}</strong></div>
        <div className="language-actions">
          <button className="primary-button" onClick={save} disabled={!source.trim() || !replacement.trim() || busy}><Save size={16} />Save rule</button>
          <button className="secondary-button danger" onClick={() => remove()} disabled={!items[source] || busy}><Trash2 size={15} />Delete rule</button>
        </div>
      </section>
    </div>
  );
}

export function LanguageWorkspace() {
  const [tab, setTab] = useState("pronunciation");
  return (
    <main className="language-workspace">
      <header className="workspace-header">
        <div><p className="eyebrow">Voice direction</p><h1>Teach every engine how your text should sound.</h1></div>
        <span className="local-pill"><i />Stored locally</span>
      </header>
      <div className="language-tabs" role="tablist" aria-label="Language tools">
        <button className={tab === "pronunciation" ? "active" : ""} onClick={() => setTab("pronunciation")}><FileAudio size={16} />Kokoro pronunciation</button>
        <button className={tab === "substitutions" ? "active" : ""} onClick={() => setTab("substitutions")}><Replace size={16} />All-engine substitutions</button>
      </div>
      {tab === "pronunciation" ? <PronunciationPanel /> : <SubstitutionPanel />}
    </main>
  );
}
