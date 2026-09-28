import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "stubs"), os.path.dirname(HERE)]
import shutil
APP = os.path.dirname(HERE)
shutil.rmtree(os.path.join(APP, "narrator_data"), ignore_errors=True)

from mockllm import Mock
from narrator import dialogue
from narrator.llm import LLMError

cfg = lambda srv: {"base_url": srv.base, "api_key": "k", "model": "test-model"}

# --- the normal path: a selection is rewritten per the instruction ---
srv = Mock(models=["test-model"])
replacement = dialogue.refine_selection(
    before="We should talk about ", selected="the weather",
    after=" today.", instruction="make it more specific: rain in April",
    speaker="Person1", provider=cfg(srv))
assert "make it more specific: rain in April" in replacement
assert "-- rewritten" in replacement
print(f"R1 ok: a normal refine call returns a rewrite reflecting the "
     f"instruction: {replacement!r}")

# the actual HTTP request sent to the provider contains the selection
# marked out and the instruction as the trailing line -- this is what a
# real LLM needs to do the edit correctly, so it's worth checking for
# real rather than assuming the prompt-building code did the right thing
sent = srv.seen[-1]
user_msg = sent["messages"][-1]["content"]
assert "[[[the weather]]]" in user_msg
assert user_msg.strip().endswith(
    "INSTRUCTION: make it more specific: rain in April")
assert "We should talk about " in user_msg and " today." in user_msg
print("R2 ok: the request actually marks the selected span with "
     "[[[...]]] and preserves the surrounding text for context")
srv.stop()

# --- neighboring turns are included as context, not sent for rewriting ---
srv2 = Mock(models=["test-model"])
dialogue.refine_selection(
    before="", selected="Sure, I agree", after=".",
    instruction="sound less certain", speaker="Person2",
    provider=cfg(srv2),
    neighbor_before={"speaker": "Person1", "text": "Is that really true?"},
    neighbor_after={"speaker": "Person1", "text": "Interesting, go on."})
sent2 = srv2.seen[-1]["messages"][-1]["content"]
assert "Is that really true?" in sent2
assert "Interesting, go on." in sent2
assert "[[[Sure, I agree]]]" in sent2
print("R3 ok: neighboring turns are passed as context alongside the "
     "marked span, without being marked for rewriting themselves")
srv2.stop()

# --- a reply with stray quotes/brackets is cleaned up ---
srv3 = Mock(models=["test-model"], mode="messy_refine")
messy = dialogue.refine_selection(
    before="", selected="fine", after="", instruction="punch it up",
    speaker="Person1", provider=cfg(srv3))
assert not messy.startswith('"') and not messy.endswith('"')
assert "[" not in messy and "]" not in messy
print(f"R4 ok: a reply wrapped in stray quotes/brackets is cleaned "
     f"before use: {messy!r}")
srv3.stop()

# --- an empty reply is treated as a failure, not silently accepted ---
srv4 = Mock(models=["test-model"], mode="empty_refine")
try:
    dialogue.refine_selection(
        before="", selected="text", after="", instruction="anything",
        speaker="Person1", provider=cfg(srv4))
    raise SystemExit("should have raised")
except LLMError as e:
    assert "empty" in str(e).lower()
print("R5 ok: a blank rewrite is refused rather than silently swapped in")
srv4.stop()

# --- input validation: no selection, no instruction ---
srv5 = Mock(models=["test-model"])
try:
    dialogue.refine_selection("", "   ", "", "do something", "Person1",
                              cfg(srv5))
    raise SystemExit("should have raised")
except LLMError as e:
    assert "selected" in str(e).lower()
print("V1 ok: an empty/whitespace-only selection is refused before "
     "any network call")

try:
    dialogue.refine_selection("", "some text", "", "  ", "Person1",
                              cfg(srv5))
    raise SystemExit("should have raised")
except LLMError as e:
    assert "change" in str(e).lower() or "instruction" in str(e).lower()
print("V2 ok: a blank instruction is refused before any network call")
assert not srv5.seen, "validation failures should not reach the network"
srv5.stop()

print("\nALL DIALOGUE REFINE TESTS PASSED")
