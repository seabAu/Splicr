"""A minimal server speaking the OpenAI chat-completions shape.

Real providers can't be reached from this sandbox and would need keys, so
the client is tested against a server that implements the actual protocol.
Behaviour is switchable per-instance so each failure mode -- bad key,
missing model, non-compatible reply, a model that ignores formatting --
can be exercised for real over a socket rather than mocked out.
"""
import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

class Mock:
    def __init__(self, require_key=None, models=("test-model",),
                 mode="good", no_models_endpoint=False):
        self.require_key, self.models = require_key, list(models)
        self.mode, self.no_models_endpoint = mode, no_models_endpoint
        self.seen = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _send(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def _auth_ok(self):
                if not outer.require_key: return True
                return self.headers.get("Authorization") == "Bearer " + outer.require_key
            def do_GET(self):
                if self.path.endswith("/models"):
                    if outer.no_models_endpoint: return self._send(404, {"error": "nope"})
                    if not self._auth_ok(): return self._send(401, {"error": "bad key"})
                    return self._send(200, {"data": [{"id": m} for m in outer.models]})
                self._send(404, {"error": "not found"})
            def do_POST(self):
                if not self.path.endswith("/chat/completions"):
                    return self._send(404, {"error": "not found"})
                if not self._auth_ok(): return self._send(401, {"error": "bad key"})
                body = json.loads(self.rfile.read(
                    int(self.headers.get("Content-Length", 0))) or b"{}")
                outer.seen.append(body)
                if body.get("model") not in outer.models:
                    return self._send(404, {"error": "no such model"})
                if outer.mode == "ratelimited": return self._send(429, {"error": "slow down"})
                if outer.mode == "notcompatible": return self._send(200, {"output": "wrong shape"})
                prompt = json.dumps(body.get("messages", []))
                user = body.get("messages", [{}])[-1].get("content", "")
                if outer.mode == "ignores_format":
                    text = "Sure! Here is a podcast about it, discussed casually."
                elif "ready" in prompt:
                    text = "ready"
                elif "edit ONE marked span" in prompt:
                    # The dialogue.refine_selection() system prompt.
                    # INSTRUCTION is the last line of the user message.
                    instruction = user.rsplit("INSTRUCTION:", 1)[-1].strip()
                    if outer.mode == "messy_refine":
                        text = f'"[{instruction} -- rewritten]"'
                    elif outer.mode == "empty_refine":
                        text = "   "
                    else:
                        text = f"{instruction} -- rewritten"
                elif "running note" in prompt:
                    text = "Covered: " + user.split("Just discussed:")[-1][:120]
                elif "numbered list of segment titles" in prompt:
                    text = "1. Opening\n2. The middle\n3. Wrapping up"
                elif outer.mode == "repeats":
                    # Always emits the same point, so cross-section
                    # deduplication has something real to catch.
                    text = ("<Person1>The tidal bulge follows the moon around "
                            "the earth continuously, producing two high tides "
                            "each day in most coastal locations worldwide.</Person1>\n"
                            "<Person2>Right.</Person2>")
                elif outer.mode == "same_speaker_twice":
                    text = ("<Person1>First half of a thought.</Person1>\n"
                            "<Person1>Second half of the same thought.</Person1>")
                elif outer.mode == "chatty":
                    text = ("Certainly! Here's the dialogue:\n```xml\n"
                            "<Person1>Tagged content survives.</Person1>\n"
                            "<Person2>Even with preamble around it.</Person2>\n"
                            "```\nLet me know if you want changes!")
                else:
                    # Echo the section marker so each section is distinct.
                    marker = "unknown"
                    for line in user.splitlines():
                        if line.startswith("YOU ARE WRITING"):
                            marker = line[len("YOU ARE WRITING "):][:60]
                    starts_p2 = "begin with Person2" in user
                    a, b = ("Person2", "Person1") if starts_p2 else ("Person1", "Person2")
                    text = (f"<{a}>Discussing {marker} with distinct wording "
                            f"about topic number {len(outer.seen)}.</{a}>\n"
                            f"<{b}>A reply that also differs, mentioning item "
                            f"{len(outer.seen)} specifically.</{b}>")
                return self._send(200, {"choices": [
                    {"message": {"role": "assistant", "content": text}}]})
        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}/v1"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
    def stop(self): self._server.shutdown()
