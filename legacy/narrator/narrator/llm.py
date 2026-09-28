"""Pluggable LLM providers, local or hosted, chosen per job.

Narrator ships no API keys and no model weights. Everything here points at
something the person configured themselves -- their own Ollama, their own
OpenAI key, their own endpoint. That is not only a privacy choice: it is
what keeps licence obligations where they belong. A model whose weights
carry usage restrictions (Gemma's Terms, Llama's Community Licence) can be
used through here without Narrator ever distributing those weights, in the
same way the app offers `mutagen` as an optional install rather than
bundling it.

**Everything speaks the OpenAI chat-completions shape.** Ollama, llama.cpp,
LM Studio and vLLM all expose it; so do OpenRouter, Groq and DeepInfra;
OpenAI itself obviously does; and Anthropic and Google each publish an
OpenAI-compatible endpoint alongside their native APIs. One client
therefore covers every provider, and anything unusual can be added as a
custom base URL rather than needing new code.

Requests go through `urllib` from the standard library on purpose: a
local-first tool should not require an extra HTTP package to be installed
before it can talk to a local model.
"""

import json
import os
import time
import urllib.error
import urllib.request

from .config import DATA_DIR

# Keys live apart from the ordinary settings file, which gets copied
# between machines and pasted into bug reports.
LLM_CONFIG_PATH = os.path.join(DATA_DIR, "narrator_llm.json")

# Starting points, not a closed list. `base_url` is the OpenAI-compatible
# endpoint. `local` means it runs on this machine, so no key is needed and
# nothing leaves it.
PROVIDER_TEMPLATES = {
    "ollama": {
        "label": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "local": True, "needs_key": False,
        "example_model": "qwen3:14b",
        "note": "Install Ollama, then `ollama pull qwen3:14b`. Nothing "
                "leaves this machine.",
    },
    "llamacpp": {
        "label": "llama.cpp server (local)",
        "base_url": "http://localhost:8080/v1",
        "local": True, "needs_key": False,
        "example_model": "local-model",
        "note": "Run llama-server with an OpenAI-compatible port.",
    },
    "lmstudio": {
        "label": "LM Studio (local)",
        "base_url": "http://localhost:1234/v1",
        "local": True, "needs_key": False,
        "example_model": "local-model",
        "note": "Enable the local server in LM Studio's Developer tab.",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "local": False, "needs_key": True,
        "example_model": "gpt-5-mini",
        "note": "Your key, your account, your bill.",
    },
    "anthropic": {
        "label": "Anthropic (OpenAI-compatible endpoint)",
        "base_url": "https://api.anthropic.com/v1",
        "local": False, "needs_key": True,
        "example_model": "claude-haiku-4-5",
        "note": "Uses Anthropic's OpenAI-compatible endpoint. If it "
                "misbehaves, check their current path -- compatibility "
                "layers move.",
    },
    "gemini": {
        "label": "Google Gemini (OpenAI-compatible endpoint)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "local": False, "needs_key": True,
        "example_model": "gemini-flash-latest",
        "note": "Very large context, so a long chapter may not need "
                "splitting at all.",
    },
    "openrouter": {
        "label": "OpenRouter (many models, one key)",
        "base_url": "https://openrouter.ai/api/v1",
        "local": False, "needs_key": True,
        "example_model": "qwen/qwen3-14b",
        "note": "Useful for running the same open model you'd run "
                "locally, when you don't want to run it locally.",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "local": False, "needs_key": True,
        "example_model": "llama-3.3-70b-versatile",
        "note": "Fast, cheap, hosts open-weight models.",
    },
    "deepinfra": {
        "label": "DeepInfra",
        "base_url": "https://api.deepinfra.com/v1/openai",
        "local": False, "needs_key": True,
        "example_model": "Qwen/Qwen3-14B",
        "note": "Cheap hosting for open-weight models.",
    },
    "custom": {
        "label": "Anything else (OpenAI-compatible)",
        "base_url": "", "local": False, "needs_key": False,
        "example_model": "",
        "note": "Any endpoint that speaks the OpenAI chat-completions "
                "API. Leave the key blank if it doesn't need one.",
    },
}


def _mask(key):
    """A key you can recognise but not use. Full keys are never returned
    to an interface -- the browser UI runs in a page, and a key echoed
    into the DOM is a key in screenshots and bug reports."""
    if not key:
        return ""
    return f"{key[:3]}…{key[-4:]}" if len(key) > 10 else "…"


def load_providers():
    """Every configured provider, keys included. For internal use only --
    `safe_providers()` is what an interface should ever see."""
    try:
        with open(LLM_CONFIG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def safe_providers():
    """Configured providers with keys masked."""
    out = {}
    for name, cfg in load_providers().items():
        safe = dict(cfg)
        safe["api_key"] = _mask(cfg.get("api_key", ""))
        safe["has_key"] = bool(cfg.get("api_key"))
        out[name] = safe
    return out


def save_provider(name, cfg):
    """Add or update one provider. An empty `api_key` keeps whatever was
    already stored, so an interface can send back a masked value without
    destroying the real one."""
    providers = load_providers()
    existing = providers.get(name, {})
    merged = {**existing, **{k: v for k, v in cfg.items()
                            if k != "api_key" or v}}
    providers[name] = merged
    _write(providers)
    return merged


def delete_provider(name):
    providers = load_providers()
    providers.pop(name, None)
    _write(providers)
    return providers


def _write(providers):
    os.makedirs(os.path.dirname(LLM_CONFIG_PATH), exist_ok=True)
    temp = LLM_CONFIG_PATH + ".tmp"
    with open(temp, "w", encoding="utf-8") as fh:
        json.dump(providers, fh, indent=2)
    os.replace(temp, LLM_CONFIG_PATH)
    try:
        # Readable only by this user where the OS supports it. Keys are
        # still plaintext on disk -- this narrows who can read them, it
        # does not encrypt them, and the UI says so.
        os.chmod(LLM_CONFIG_PATH, 0o600)
    except OSError:
        pass


class LLMError(RuntimeError):
    """A provider problem, phrased for a person rather than a log."""


def complete(cfg, messages, model=None, temperature=0.7, max_tokens=2048,
             timeout=180, response_format=None):
    """One chat completion. Returns the assistant's text.

    Deliberately non-streaming: script generation is a background job
    already reported through the job log, so streaming tokens would add
    complexity for no visible benefit.
    """
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise LLMError("This provider has no endpoint URL set.")
    model = model or cfg.get("model")
    if not model:
        raise LLMError("No model chosen for this provider.")

    payload = {"model": model, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    if response_format:
        payload["response_format"] = response_format

    request = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 **({"Authorization": "Bearer " + cfg["api_key"]}
                    if cfg.get("api_key") else {})},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        if exc.code in (401, 403):
            raise LLMError(
                f"The provider rejected the key ({exc.code}). Check it is "
                "current and has access to this model.\n" + detail)
        if exc.code == 404:
            raise LLMError(
                f"Not found ({exc.code}). Usually the model name is wrong, "
                "or the endpoint URL is missing/has an extra path "
                "segment.\n" + detail)
        if exc.code == 429:
            raise LLMError("Rate limited or out of quota (429).\n" + detail)
        raise LLMError(f"The provider returned {exc.code}.\n{detail}")
    except urllib.error.URLError as exc:
        raise LLMError(
            f"Couldn't reach {base}: {exc.reason}. "
            + ("Is the local server running?" if cfg.get("local")
               else "Check the URL and your connection."))
    except TimeoutError:
        raise LLMError(f"The provider didn't answer within {timeout}s.")

    try:
        return body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError(
            "The reply didn't look like a chat completion. This endpoint "
            "may not be OpenAI-compatible.\n" + json.dumps(body)[:400])


# --- staged verification -----------------------------------------------
#
# Each stage answers one question, in the order that isolates a fault:
# is it reachable -> does it accept the key -> does the model exist and
# answer -> does it follow instructions well enough to be useful. Stopping
# at the first failure means the message names the actual problem instead
# of a symptom three steps downstream.

def verify(cfg, model=None, log=lambda _m: None):
    """Run the checks in order, stopping at the first failure. Returns a
    list of {stage, ok, detail} -- the caller shows all of them so it is
    obvious how far it got."""
    results = []

    def record(stage, ok, detail):
        results.append({"stage": stage, "ok": ok, "detail": detail})
        log(f"  {'ok' if ok else 'FAILED'}: {stage} -- {detail}")
        return ok

    base = (cfg.get("base_url") or "").rstrip("/")
    if not record("Endpoint configured", bool(base),
                  base or "no URL set"):
        return results

    # 1. Reachable at all, and speaking HTTP.
    started = time.time()
    try:
        request = urllib.request.Request(
            base + "/models",
            headers={"Authorization": "Bearer " + cfg["api_key"]}
                    if cfg.get("api_key") else {})
        with urllib.request.urlopen(request, timeout=20) as response:
            listing = json.loads(response.read().decode("utf-8"))
        names = [m.get("id") for m in (listing.get("data") or [])
                if isinstance(m, dict)]
        record("Reachable", True,
               f"answered in {time.time() - started:.1f}s"
               + (f", {len(names)} model(s) offered" if names else ""))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            record("Reachable", True, "responded, but rejected the key")
            record("Key accepted", False,
                   f"{exc.code} -- the key is missing, wrong, or lacks "
                   "access")
            return results
        # Some endpoints don't implement /models; that isn't fatal, so
        # carry on to the real test rather than failing here.
        record("Reachable", True,
               f"responded {exc.code} to a model listing; continuing")
        names = []
    except urllib.error.URLError as exc:
        record("Reachable", False,
               f"{exc.reason}. "
               + ("Is the local server running?" if cfg.get("local")
                  else "Check the URL and your connection."))
        return results
    except (ValueError, TimeoutError) as exc:
        record("Reachable", True, f"responded, but oddly: {exc}")
        names = []

    if cfg.get("api_key"):
        record("Key accepted", True, "no authentication error")

    # 2. The model exists and will actually answer.
    wanted = model or cfg.get("model")
    if names and wanted and wanted not in names:
        record("Model available", False,
               f"{wanted!r} isn't in the list this endpoint offers. "
               f"Available: {', '.join(names[:8])}"
               + ("…" if len(names) > 8 else ""))
        return results

    started = time.time()
    try:
        reply = complete(
            cfg,
            [{"role": "user",
              "content": "Reply with exactly the word: ready"}],
            model=wanted, temperature=0, max_tokens=16, timeout=60)
    except LLMError as exc:
        record("Model answers", False, str(exc))
        return results
    record("Model answers", True,
           f"replied in {time.time() - started:.1f}s: {reply.strip()[:40]!r}")

    # 3. Does it follow a shaped instruction? A model that ignores this
    # will produce an unparseable script, which is far more annoying to
    # discover after a twenty-minute generation.
    try:
        shaped = complete(
            cfg,
            [{"role": "system",
              "content": "You output dialogue turns and nothing else. "
                         "Use exactly this form:\\n"
                         "<Person1>text</Person1>\\n<Person2>text</Person2>"},
             {"role": "user",
              "content": "Two short turns introducing a podcast about "
                         "tidal patterns."}],
            model=wanted, temperature=0.4, max_tokens=200, timeout=90)
    except LLMError as exc:
        record("Follows the script format", False, str(exc))
        return results

    has_both = "<Person1>" in shaped and "<Person2>" in shaped
    record("Follows the script format", has_both,
           (shaped.strip().replace("\\n", " ")[:110] + "…") if has_both else
           "the reply didn't use the speaker tags, so scripts from this "
           "model may need cleaning up: "
           + shaped.strip().replace("\\n", " ")[:110])
    return results
