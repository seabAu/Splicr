"""Stand-in for the qwen-tts package's Qwen3TTSModel, narrow to the two
call shapes ensure_qwen_voice() and fetch_qwen_custom_speakers() actually
use: generate_voice_design(text=, instruct=, language=) -> (wavs, rate),
and get_supported_speakers(). Neither the narration-render path
(_run_qwen_local, which normally runs in the isolated qwen3 worker) nor
voice cloning is exercised through this stub -- those are covered
elsewhere via the worker-dispatch tests.
"""
import numpy as np
from _stublog import record


class Qwen3TTSModel:
    @classmethod
    def from_pretrained(cls, repo, **kwargs):
        record({"call": "qwen_model_load", "repo": repo})
        return cls()

    def generate_voice_design(self, text="", instruct="", language="English"):
        record({"call": "qwen_voice_design", "text_len": len(text or ""),
               "instruct_len": len(instruct or "")})
        rate = 24000
        seconds = 2.0
        n = int(seconds * rate)
        audio = (np.sin(np.arange(n, dtype=np.float32) * 0.03) * 0.15)
        return [audio], rate

    def get_supported_speakers(self):
        record({"call": "qwen_get_speakers"})
        return ["Ethan", "Sunny", "Chloe"]
