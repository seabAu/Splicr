import React, { useEffect, useState } from "react";
import {
  searchWords,
  wordSound,
  previewRespelling,
  saveRespelling,
  deleteRespelling,
} from "./api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// Any word can be edited, not only the ones a scan flags -- a word can be
// in Kokoro's dictionary, and so never reported as unknown, and still come
// out wrong. That case is the reason this exists.

const SOURCE_LABEL = {
  override: "your override",
  dictionary: "Kokoro's dictionary",
  guessed: "guessed (not in the dictionary)",
  unknown: "Kokoro can't say this",
};

export default function Pronunciation() {
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState([]);
  const [total, setTotal] = useState(0);
  const [word, setWord] = useState(null);
  const [respelling, setRespelling] = useState("");
  const [preview, setPreview] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  // Debounced so typing doesn't fire a lookup per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      searchWords(query)
        .then((r) => {
          setMatches(r.matches || []);
          setTotal(r.total || 0);
          setError(r.error || "");
        })
        .catch((e) => setError(String(e.message || e)));
    }, 200);
    return () => clearTimeout(timer);
  }, [query]);

  const inspect = async (w) => {
    setMessage("");
    try {
      setWord(await wordSound(w));
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  // Live check of the respelling, so nothing is a surprise on save.
  useEffect(() => {
    if (!word || !respelling.trim()) return setPreview(null);
    let cancelled = false;
    previewRespelling(word.word, respelling)
      .then((r) => !cancelled && setPreview(r))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [respelling, word]);

  return (
    <div className="pron">
      <Input
        type="search"
        placeholder="Any word — type to filter Kokoro's dictionary…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {error && <p className="error">{error}</p>}
      {total > matches.length && (
        <p className="hint">
          Showing {matches.length} of {total}.
        </p>
      )}
      <ul className="wordlist">
        {matches.map((m) => (
          <li key={m.word}>
            <Button onClick={() => inspect(m.word)}>
              <span className={`mark ${m.source}`}>
                {m.source === "override" ? "*" : " "}
              </span>
              <span className="w">{m.word}</span>
              <span className="ipa">{m.phonemes}</span>
            </Button>
          </li>
        ))}
      </ul>
      {query.trim() && !matches.some((m) => m.word === query.trim().toLowerCase()) && (
        <Button variant="ghost" size="sm" onClick={() => inspect(query.trim())}>
          Not listed — check “{query.trim()}” anyway
        </Button>
      )}

      {word && (
        <div className="word-detail">
          <h3>{word.word}</h3>
          {word.error ? (
            <p className="error">{word.error}</p>
          ) : (
            <p>
              <code>{word.phonemes}</code>{" "}
              <span className="hint">
                — {SOURCE_LABEL[word.source] || word.source}
              </span>
            </p>
          )}
          <p className="hint">
            Respell it with ordinary words that sound right, separated by
            spaces. Put <code>*</code> before the stressed piece — e.g.{" "}
            <code>an on nim my *nation</code>
          </p>
          <Input
            type="text"
            value={respelling}
            placeholder="an on nim my *nation"
            onChange={(e) => setRespelling(e.target.value)}
          />
          {preview &&
            (preview.failed ? (
              <p className="error">
                “{preview.failed}” isn’t a word Kokoro knows — try another
                real word that sounds like that part.
              </p>
            ) : (
              <p className="ok">
                would become <code>{preview.ipa}</code>
              </p>
            ))}
          <div className="row">
            <Button
              disabled={!preview || preview.failed}
              onClick={() =>
                saveRespelling(word.word, respelling)
                  .then((r) => {
                    setMessage(`Saved: ${r.word} → ${r.ipa}`);
                    setRespelling("");
                    inspect(r.word);
                    setQuery((q) => q);
                  })
                  .catch((e) => setError(String(e.message || e)))
              }
            >
              Save override
            </Button>
            {word.source === "override" && (
              <Button
                onClick={() =>
                  deleteRespelling(word.word)
                    .then(() => {
                      setMessage(`Override removed for ${word.word}.`);
                      inspect(word.word);
                    })
                    .catch((e) => setError(String(e.message || e)))
                }
              >
                Remove override
              </Button>
            )}
          </div>
          {message && <p className="ok">{message}</p>}
        </div>
      )}
    </div>
  );
}
