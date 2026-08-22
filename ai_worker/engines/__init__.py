"""Accuracy-oriented speech engine contracts and local implementations."""

from .base import (
    ASREngine,
    ASRResult,
    EngineCapabilities,
    LanguageDetection,
    Timestamp,
)
from .qwen3 import Qwen3ASREngine
from .whisper import CurrentASREngine, WhisperLargeV3Engine

__all__ = [
    "ASREngine",
    "ASRResult",
    "CurrentASREngine",
    "EngineCapabilities",
    "LanguageDetection",
    "Qwen3ASREngine",
    "Timestamp",
    "WhisperLargeV3Engine",
]
