"""Local translation providers and meaning-preservation helpers."""

from .base import TranslationCapabilities, TranslationEngine, TranslationResult
from .consistency import SessionGlossary, TerminologyEngine, TranslationMemory
from .quality import TranslationQualityReport, check_translation_quality
from .transformers_mt import TransformersMTConfig, TransformersTranslationEngine

__all__ = [
    "SessionGlossary",
    "TerminologyEngine",
    "TranslationCapabilities",
    "TranslationEngine",
    "TranslationMemory",
    "TranslationQualityReport",
    "TranslationResult",
    "TransformersMTConfig",
    "TransformersTranslationEngine",
    "check_translation_quality",
]
