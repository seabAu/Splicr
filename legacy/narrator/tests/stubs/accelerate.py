"""Stub: audio8's env spec lists accelerate as a dependency, but
audio8_engine.py never imports it directly (transformers uses it
internally for device placement). Present only so an environment probe
or an eager import elsewhere does not fail for its absence."""
__version__ = "0.34.0-stub"
