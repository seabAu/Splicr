"""Stand-in for the kokoro package: same call shapes, no model download."""
import numpy as np, re
from _stublog import record

_KNOWN_UNRESOLVED = {"non", "ni", "mization", "zzq", "nnn", "shun"}
_GOLDS = {"narrative": "nˈæɹətɪv", "narrator": "nˈæɹeɪtəɹ",
          "narrate": "nˈæɹeɪt", "anonymous": "ənˈɑnəməs",
          "digital": "dˈɪdʒətəl", "twin": "twˈɪn", "twine": "twˈaɪn",
          "read": {"VERB": "ɹˈid", "DEFAULT": "ɹˈɛd"}, "the": "ðə",
          "statecraft": "stˈeɪtkɹæft"}

def _fake_g2p(text):
    key = (text or "").strip().lower()
    if key in _GOLDS:
        v = _GOLDS[key]
        return (v if isinstance(v, str) else v.get("DEFAULT", "")), []
    if key in _KNOWN_UNRESOLVED or not key:
        return "❓", []
    if all(c.isalpha() or c.isspace() for c in key):
        return "ˈ" + ("".join(c for c in key if c not in "aeiou") or "ə"), []
    return "❓", []

class Result(tuple):
    """Unpackable as (graphemes, phonemes, audio), with attributes too."""
    def __new__(cls, graphemes, phonemes, audio):
        self = super().__new__(cls, (graphemes, phonemes, audio))
        self.graphemes, self.phonemes, self.audio = graphemes, phonemes, audio
        self.tokens = []
        return self


class _Lexicon:
    def __init__(self): self.golds = dict(_GOLDS)

class _G2P:
    def __init__(self): self.lexicon = _Lexicon()
    def __call__(self, text): return _fake_g2p(text)

class KPipeline:
    def __init__(self, lang_code="a", model=True, **kw):
        record({"call": "kokoro", "lang": lang_code, "model": bool(model)})
        self.model = model
        self.g2p = _G2P()
    def __call__(self, text, voice="af_heart", speed=1.0):
        # The real Result unpacks to (graphemes, phonemes, audio) AND
        # exposes attributes, so the stub must do both or callers that
        # unpack it break.
        for part in [p for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]:
            n = max(2400, len(part) * 240)
            yield Result(part, "",
                         np.sin(np.arange(n, dtype=np.float32) * 0.05) * 0.3)
