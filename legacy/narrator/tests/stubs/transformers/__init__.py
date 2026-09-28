"""Stand-in for the transformers package, just enough surface for
audio8_engine.py: AutoModel/AutoProcessor with the specific call shape
that module uses (processor(text=, ref_audio=, ref_text=,
return_tensors=), model.generate(**inputs), model.decode_audio(out)).

Not a general transformers stub -- narrower on purpose, so a test that
accidentally relies on unstubbed behaviour fails loudly instead of
silently matching real transformers by luck.
"""
import numpy as np
from _stublog import record


class _Inputs(dict):
    def to(self, device):
        return self


class AutoProcessor:
    @classmethod
    def from_pretrained(cls, repo, trust_remote_code=False):
        record({"call": "audio8_processor_load", "repo": repo,
               "trust_remote_code": trust_remote_code})
        return cls()

    def __call__(self, text="", ref_audio=None, ref_text="",
                return_tensors="pt"):
        record({"call": "audio8_process", "text_len": len(text or ""),
               "ref_text_len": len(ref_text or "")})
        return _Inputs(text=text, ref_audio=ref_audio, ref_text=ref_text)


# Controls what the stub's generated audio looks like, so a test can make
# it produce plausible, too-short, or too-long output on demand -- the
# thing that actually needs exercising is the retry/screening logic in
# audio8_engine.py, not any real model behaviour.
_MODE = {"value": "normal"}


def set_stub_mode(mode):
    _MODE["value"] = mode


class _Model:
    def eval(self):
        return self

    def to(self, device):
        record({"call": "audio8_to_device", "device": str(device)})
        return self

    def generate(self, **inputs):
        record({"call": "audio8_generate",
               "text_len": len(inputs.get("text", "") or "")})
        return {"_text": inputs.get("text", "")}

    def decode_audio(self, out):
        text = out.get("_text", "")
        rate = 44100
        chars = max(1, len(text))
        mode = _MODE["value"]
        if mode == "too_short":
            seconds = (chars / 20.0) * 0.1     # far below the floor
        elif mode == "too_long":
            seconds = chars * 0.5 * 3          # far above the ceiling
        elif mode == "silent":
            seconds = 0.0
        elif mode == "recovers_on_retry":
            # First call for each distinct text is bad; a retry with the
            # SAME text (the model is re-invoked, nothing else changes)
            # succeeds -- exercises the retry path actually helping.
            key = f"seen:{text}"
            seen = getattr(_Model, "_seen", None) or {}
            count = seen.get(key, 0) + 1
            seen[key] = count
            _Model._seen = seen
            seconds = (chars / 20.0) * 0.1 if count == 1 else chars / 14.0
        else:
            seconds = chars / 14.0             # plausible normal speech
        n = max(1, int(seconds * rate))
        audio = (np.sin(np.arange(n, dtype=np.float32) * 0.05) * 0.2)
        return audio, rate


class AutoModel:
    @classmethod
    def from_pretrained(cls, repo, trust_remote_code=False, dtype=None):
        record({"call": "audio8_model_load", "repo": repo,
               "trust_remote_code": trust_remote_code})
        return _Model()


__version__ = "4.57.1-stub"
