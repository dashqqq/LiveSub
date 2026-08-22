"""Safe local Transformers adapter for reviewed built-in MT architectures."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Sequence

from .base import TranslationCapabilities, TranslationEngine, TranslationResult


@dataclass(frozen=True)
class TransformersMTConfig:
    engine_id: str
    model_id: str
    model_path: str
    source_languages: tuple[str, ...]
    target_language: str = "en"
    device: str = "cuda:0"
    dtype: str = "auto"
    beam_size: int = 5
    max_new_tokens: int = 256
    source_prefixes: tuple[tuple[str, str], ...] = ()
    model_family: str = "generic"
    source_language_codes: tuple[tuple[str, str], ...] = ()
    target_language_code: str = ""


class TransformersTranslationEngine(TranslationEngine):
    """Load only local safetensors/known Transformers code.

    `trust_remote_code` is always false. A model such as IndicTrans2 that needs
    custom code must first have that code reviewed and vendored as a normal
    package; this generic adapter will not execute repository Python files.
    """

    def __init__(self, config: TransformersMTConfig) -> None:
        if not os.path.isdir(config.model_path):
            raise FileNotFoundError(
                f"translation model must be staged and verified locally: {config.model_path}"
            )
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self.config = config
        self._tokenizer = AutoTokenizer.from_pretrained(
            config.model_path,
            local_files_only=True,
            trust_remote_code=False,
        )
        load_kwargs = {
            "local_files_only": True,
            "trust_remote_code": False,
        }
        if config.dtype != "auto":
            import torch

            dtype = {
                "float16": torch.float16,
                "bfloat16": torch.bfloat16,
                "float32": torch.float32,
            }.get(config.dtype)
            if dtype is None:
                raise ValueError(f"unsupported MT dtype: {config.dtype}")
            load_kwargs["dtype"] = dtype
        self._model = AutoModelForSeq2SeqLM.from_pretrained(
            config.model_path,
            **load_kwargs,
        )
        self._model.to(config.device)
        self._model.eval()

    def capabilities(self) -> TranslationCapabilities:
        return TranslationCapabilities(
            engine_id=self.config.engine_id,
            model_id=self.config.model_id,
            source_languages=self.config.source_languages,
            target_languages=(self.config.target_language,),
            confidence=False,
            glossary_prompt=False,
            remote_code=False,
            notes=(
                "Known Transformers architecture loaded with trust_remote_code=False.",
                "Glossary is checked after translation but not injected into unsupported tokenizers.",
            ),
        )

    def _prefix(self, source_language: str) -> str:
        return dict(self.config.source_prefixes).get(source_language, "")

    def translate(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str = "en",
        context: str = "",
        glossary: Sequence[str] = (),
    ) -> TranslationResult:
        del context, glossary
        if source_language not in self.config.source_languages:
            raise ValueError(f"{self.config.engine_id} does not support source {source_language}")
        if target_language != self.config.target_language:
            raise ValueError(f"{self.config.engine_id} does not support target {target_language}")
        import torch

        input_text = self._prefix(source_language) + text.strip()
        forced_bos_token_id = None
        if self.config.model_family == "m2m100":
            source_code = dict(self.config.source_language_codes).get(source_language)
            if not source_code or not self.config.target_language_code:
                raise ValueError(f"missing M2M100 language mapping for {source_language}")
            self._tokenizer.src_lang = source_code
            forced_bos_token_id = self._tokenizer.get_lang_id(
                self.config.target_language_code
            )
        encoded = self._tokenizer(
            input_text,
            return_tensors="pt",
            truncation=True,
        )
        encoded = {key: value.to(self.config.device) for key, value in encoded.items()}
        input_token_count = int(encoded["input_ids"].shape[-1])
        generation_limit = min(
            self.config.max_new_tokens,
            max(16, input_token_count * 2 + 16),
        )
        started = time.perf_counter_ns()
        with torch.inference_mode():
            generation_kwargs = {
                "num_beams": self.config.beam_size,
                "do_sample": False,
                "max_new_tokens": generation_limit,
                "early_stopping": True,
            }
            if forced_bos_token_id is not None:
                generation_kwargs["forced_bos_token_id"] = forced_bos_token_id
            generated = self._model.generate(**encoded, **generation_kwargs)
        completed = time.perf_counter_ns()
        translated = self._tokenizer.batch_decode(
            generated,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=True,
        )
        if len(translated) != 1:
            raise RuntimeError(f"translation model returned {len(translated)} outputs")
        return TranslationResult(
            source_text=text,
            translated_text=translated[0].strip(),
            source_language=source_language,
            target_language=target_language,
            engine_id=self.config.engine_id,
            model_id=self.config.model_id,
            inference_ms=max(0, round((completed - started) / 1_000_000)),
            confidence=None,
            metadata={
                "backend": "transformers",
                "device": self.config.device,
                "beam_size": self.config.beam_size,
                "model_family": self.config.model_family,
                "input_token_count": input_token_count,
                "generated_token_count": int(generated.shape[-1]),
                "generation_limit": generation_limit,
            },
        )

    def warmup(self) -> None:
        samples = {"ru": "Привет", "ja": "こんにちは", "hi": "नमस्ते"}
        for source in self.config.source_languages:
            sample = samples.get(source, "This is a local translation warmup")
            self.translate(f"{sample} {sample} {sample}", source_language=source)
