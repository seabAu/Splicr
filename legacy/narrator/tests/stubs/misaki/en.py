"""Stand-in for misaki's English G2P. `_KNOWN_UNRESOLVED` holds pieces
verified against the REAL misaki earlier in this project as returning the
unresolved marker; how far misaki's own rules stretch for other words is
not something this stub can claim, so tests shouldn't depend on it."""
from _stublog import record
from kokoro import _GOLDS, _fake_g2p, _Lexicon

class G2P:
    def __init__(self, trf=False, british=False):
        record({"call": "G2P", "british": british})
        self.lexicon = _Lexicon()
    def __call__(self, text): return _fake_g2p(text)
