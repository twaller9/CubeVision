"""Plug-in points for the parts other people are building.

VISION  (your friend's model)
    Implement a class with   detect(jpeg: bytes) -> list[dict]
    returning one dict per cube face visible in the frame, in the format
    documented in assemble.py, e.g.
        [{"grid": [["W","R","G"],["O","W","W"],["Y","B","W"]], "up": "G"}]
    Point the server at it with  CUBEVISION_VISION=package.module:ClassName

SPEECH  (speech-to-speech)
    Implement a class with any of these (all optional):
        async def on_audio(self, session_id: str, pcm16: bytes) -> list[dict]
            # mic audio forwarded from the glasses (16 kHz mono PCM16);
            # return extra events to send to the phone, e.g. answers to questions
        async def speak(self, session_id: str, text: str) -> bytes | None
            # turn a coaching line into audio (mp3/wav/aac bytes) to play on the glasses;
            # return None to let the phone use its built-in text-to-speech
        def context(self, session_id: str, snapshot: dict) -> None
            # receives the current cube/coaching state so the voice agent can answer
            # questions like "why that move?"
    Point the server at it with  CUBEVISION_SPEECH=package.module:ClassName
"""
from __future__ import annotations

import importlib
import logging
import os

log = logging.getLogger("cubevision")


class NullVision:
    def detect(self, jpeg: bytes) -> list[dict]:
        return []


class NullSpeech:
    async def on_audio(self, session_id: str, pcm16: bytes) -> list[dict]:
        return []

    async def speak(self, session_id: str, text: str) -> bytes | None:
        return None

    def context(self, session_id: str, snapshot: dict) -> None:
        pass


def _load(env: str, default):
    spec = os.environ.get(env)
    if not spec:
        return default()
    mod, _, cls = spec.partition(":")
    obj = getattr(importlib.import_module(mod), cls)()
    log.info("Loaded %s from %s", env, spec)
    return obj


def load_vision():
    return _load("CUBEVISION_VISION", NullVision)


def load_speech():
    sp = _load("CUBEVISION_SPEECH", NullSpeech)
    # fill in any methods the plug-in didn't implement
    for name in ("on_audio", "speak", "context"):
        if not hasattr(sp, name):
            setattr(sp, name, getattr(NullSpeech(), name))
    return sp
