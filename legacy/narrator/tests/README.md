# Tests

**These live inside the project on purpose.** They previously sat in a
scratch directory outside it and were lost when that directory was
cleared — the source survived because it was packaged, and the tests
didn't because they weren't. Anything worth citing as evidence has to
ship with the thing it tests.

## Running them

    cd tests
    python run_all.py              # everything
    python run_all.py --quick      # skips the network-dependent suite
    python test_audiogram.py       # one suite

GUI suites need a display; under Linux use `xvfb-run -a python run_all.py`.

## Stubs

`stubs/` holds stand-ins for the heavy or unreachable dependencies
(kokoro, qwen_tts, misaki, faster_whisper, huggingface_hub, torch) so the
suites run on any machine without GPUs, model downloads, or network. They
mirror the real API surfaces; where a stub's behaviour was verified
against the real package, its comments say so.

`mockllm.py` is a real HTTP server speaking the OpenAI chat-completions
protocol, used instead of mocking the client — it can be switched to
misbehave (bad key, missing model, ignores the output format) so each
failure path is exercised over an actual socket.
