"""LLM Engine: Azure OpenAI streaming for answer suggestions.

Ported from PyQt6 QThread to plain threading for FastAPI backend.
Communicates via callbacks instead of Qt signals.
"""

import json
import re
import sys
import threading
import time
from typing import Callable

import pykakasi
from openai import AzureOpenAI

_VI_DELIM_RE = re.compile(r'-{2,}\s*VI\s*-{0,}')
_ROMAJI_DELIM_CLEANUP = re.compile(r'-{2,}\s*vi\s*-{0,}', re.IGNORECASE)
_JA_CHAR_RE = re.compile(r'[\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\u4e00-\u9faf]')
_JA_SENTENCE_END = frozenset("。！？\n")
_SECTION_PREFIX_RE = re.compile(r'^(?:SECTION|Part)\s*\d*\s*:?\s*', re.IGNORECASE)
_ROMAJI_FIRST_FLUSH = 2
_ROMAJI_FLUSH_TOKENS = 4
_ROMAJI_FLUSH_MS = 0.2
_REASONING_MODEL_RE = re.compile(r'(?:^o[134]|gpt-5|o\d+-mini)', re.IGNORECASE)


def _is_reasoning_model(deployment: str) -> bool:
    return bool(_REASONING_MODEL_RE.search(deployment))


def _find_delim(text: str) -> str | None:
    m = _VI_DELIM_RE.search(text)
    return m.group(0) if m else None


def _strip_section_prefix(text: str) -> str:
    return _SECTION_PREFIX_RE.sub("", text)


def _clean_romaji(text: str) -> str:
    return _ROMAJI_DELIM_CLEANUP.sub("", text).strip().rstrip("-").strip()


class LLMEngine:
    def __init__(
        self,
        api_key: str,
        endpoint: str,
        deployment: str,
        fast_deployment: str = "",
        on_tier2_result: Callable[[dict], None] | None = None,
        on_answer_streaming: Callable[[str, str], None] | None = None,
        on_manual_result: Callable[[dict], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_usage: Callable[[dict], None] | None = None,
    ):
        self._api_version = "2025-01-01-preview"
        self._client = AzureOpenAI(
            api_key=api_key, azure_endpoint=endpoint, api_version=self._api_version,
        )
        self._deployment = deployment
        self._fast_deployment = fast_deployment or deployment
        self._active_deployment = fast_deployment or deployment
        self._active_client = self._client
        self._queue: list[dict] = []
        self._running = False
        self._personal_info = ""
        self._company_info = ""
        self._general_context = ""
        self._glossary: list[dict] = []
        self._recent_transcript: list[dict] = []
        self._source_language_name = "Japanese"
        self._has_romaji = True
        self._answer_length: int = 3
        self._jp_level = "natural"
        self._event = threading.Event()

        self._kakasi = pykakasi.kakasi()
        self._kakasi_lock = threading.Lock()

        self._on_tier2_result = on_tier2_result or (lambda _: None)
        self._on_answer_streaming = on_answer_streaming or (lambda *_: None)
        self._on_manual_result = on_manual_result or (lambda _: None)
        self._on_error = on_error or (lambda _: None)
        self._on_usage = on_usage or (lambda _: None)

        self._thread: threading.Thread | None = None

    def set_answer_length(self, length):
        if isinstance(length, int):
            self._answer_length = max(1, min(10, length))
        elif isinstance(length, str):
            _LEGACY_MAP = {"short": 2, "standard": 3, "detailed": 6}
            self._answer_length = _LEGACY_MAP.get(length, 3)

    def get_answer_length(self) -> int:
        return self._answer_length

    def switch_model(self, api_key: str, endpoint: str, deployment: str):
        """Hot-swap to a different Azure OpenAI deployment."""
        self._active_client = AzureOpenAI(
            api_key=api_key, azure_endpoint=endpoint, api_version=self._api_version,
        )
        self._active_deployment = deployment
        print(f"  [LLM] Switched to {deployment} @ {endpoint}", file=sys.stderr)

    def get_active_model(self) -> str:
        return self._active_deployment

    def set_language(self, source_name: str, has_romaji: bool):
        self._source_language_name = source_name
        self._has_romaji = has_romaji

    def set_context(self, personal_text: str, company_text: str, glossary: list[dict],
                    general_context: str = ""):
        self._personal_info = personal_text[:6000]
        self._company_info = company_text[:4000]
        self._general_context = general_context[:4000]
        self._glossary = glossary

    def set_recent_transcript(self, entries: list[dict]):
        self._recent_transcript = entries[-10:]

    def set_jp_level(self, level: str):
        if level in ("simple", "natural", "formal"):
            self._jp_level = level

    def get_jp_level(self) -> str:
        return self._jp_level

    def enqueue(self, ja: str, romaji_azure: str, vi_azure: str):
        self._queue.append({"type": "tier2", "ja": ja, "romaji_azure": romaji_azure, "vi_azure": vi_azure})
        self._event.set()

    def enqueue_manual(self, text: str, ai_refine: bool):
        self._queue.append({"type": "manual", "text": text, "ai_refine": ai_refine})
        self._event.set()

    def add_user_speech(self, ja: str, vi: str):
        self._recent_transcript.append({"speaker": "me", "ja": ja, "vi": vi})
        if len(self._recent_transcript) > 10:
            self._recent_transcript = self._recent_transcript[-10:]

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="llm-engine")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def _create_with_fallback(self, kwargs: dict):
        try:
            return self._active_client.chat.completions.create(**kwargs)
        except Exception as e:
            err_msg = str(e).lower()
            if "temperature" in err_msg or "not supported" in err_msg or "unsupported" in err_msg:
                retry_kwargs = {k: v for k, v in kwargs.items() if k != "temperature"}
                print(f"  [LLM] Retrying without temperature for {self._active_deployment}", file=sys.stderr)
                return self._active_client.chat.completions.create(**retry_kwargs)
            raise

    def _ja_to_romaji(self, text: str) -> str:
        if not text.strip():
            return ""
        try:
            with self._kakasi_lock:
                result = self._kakasi.convert(text)
            return " ".join(item["hepburn"] for item in result if item.get("hepburn"))
        except Exception:
            return text

    def _clean_vi(self, text: str) -> str:
        return _JA_CHAR_RE.sub("", text)

    def _flush_ja_buffer(self, ja_buffer: str, all_romaji_parts: list[str], emit: bool = True) -> str:
        clean = _VI_DELIM_RE.sub("", ja_buffer).strip().rstrip("-").strip()
        clean = _strip_section_prefix(clean)
        if not clean:
            return ""
        romaji = self._ja_to_romaji(clean)
        romaji = _clean_romaji(romaji)
        if romaji:
            all_romaji_parts.append(romaji)
            if emit:
                self._on_answer_streaming("answer_romaji", romaji + " ")
        return romaji

    def _run(self):
        while self._running:
            if not self._queue:
                self._event.wait(timeout=0.1)
                self._event.clear()
                if not self._queue:
                    continue

            item = self._queue.pop(-1)

            if item.get("type") == "tier2" and self._queue:
                self._queue = [i for i in self._queue if i.get("type") != "tier2"]

            try:
                if item.get("type") == "manual":
                    self._process_manual(item)
                else:
                    self._process_answer(item)
            except Exception as e:
                self._on_error(f"LLM: {str(e)[:80]}")
                print(f"  [LLM ERROR] {e}", file=sys.stderr)

    def _process_answer(self, item: dict):
        ja = item["ja"]
        vi_azure = item["vi_azure"]
        result = self._request_answer_streaming(ja, vi_azure)
        result["ja_fixed"] = ja
        result["romaji"] = item.get("romaji_azure", "")
        result["vi_refined"] = vi_azure
        self._on_tier2_result(result)
        self._recent_transcript.append({"speaker": "interviewer", "ja": ja, "vi": vi_azure})
        if len(self._recent_transcript) > 10:
            self._recent_transcript = self._recent_transcript[-10:]

    @staticmethod
    def _length_instruction(n: int) -> str:
        if n <= 2:
            return f"- Answer in {n} short sentence(s). Be concise, no extra detail."
        if n <= 5:
            return f"- Answer in approximately {n} sentences. Include concrete examples where relevant."
        return f"- Give a thorough, well-structured answer in approximately {n} sentences with real examples, specific numbers, and concrete experiences."

    @staticmethod
    def _max_tokens_for_length(n: int) -> int:
        return max(300, n * 200)

    _JP_LEVEL_INSTRUCTIONS = {
        "simple": "LEVEL: Use basic vocabulary (N4-N3). Short sentences. です/ます form only. Avoid complex keigo.",
        "natural": "LEVEL: Natural business Japanese. Standard keigo (です/ます + 謙譲語 when appropriate).",
        "formal": "LEVEL: Full business keigo (尊敬語/謙譲語/丁寧語). Formal interview register.",
    }

    def _build_system_prompt(self, lang: str) -> str:
        length_instr = self._length_instruction(self._answer_length)

        if lang == "Japanese":
            jp_level = self._JP_LEVEL_INSTRUCTIONS.get(self._jp_level, self._JP_LEVEL_INSTRUCTIONS["natural"])
            parts = [
                "Interview answer coach. Vietnamese candidate, Japanese interview.",
                "Suggest a natural spoken answer.",
                "", "FORMAT — output exactly TWO blocks separated by ---VI--- :",
                "", "[Japanese answer in kanji/kana — NO prefix, NO label, just the answer text]",
                "---VI---",
                "[Vietnamese translation — normal spacing, translate only, NO explanation]",
                "", "CRITICAL: Do NOT write 'SECTION', 'Part', labels, or markdown.",
                "CRITICAL: Vietnamese block must be proper Vietnamese with spaces between words.",
                "", "LENGTH:", length_instr,
                "", jp_level,
                "", "STYLE: natural spoken Japanese, use candidate's real info.",
                'RHYTHM: Insert " / " between phrases for natural breath pauses.',
            ]
        elif lang == "English":
            parts = [
                "Interview answer coach. Vietnamese candidate, English interview.",
                "Suggest a natural spoken answer.",
                "", "FORMAT — output exactly TWO blocks separated by ---VI--- :",
                "", "[English answer — NO prefix, NO label, just the answer text]",
                "---VI---",
                "[Vietnamese translation — normal spacing, translate only, NO explanation]",
                "", "CRITICAL: Do NOT write 'SECTION', 'Part', labels, or markdown.",
                "", "LENGTH:", length_instr,
                "", "STYLE: natural spoken English, polite, use candidate's real info.",
            ]
        else:
            parts = [
                f"Interview coach. Vietnamese candidate, {lang} interview.",
                f"Answer in {lang}, then ---VI---, then Vietnamese translation.",
                "", "LENGTH:", length_instr,
            ]

        ctx_parts = []
        if self._general_context:
            ctx_parts.append(f"[Context] {self._general_context[:1200]}")
        if self._personal_info:
            ctx_parts.append(f"[Candidate] {self._personal_info[:1500]}")
        if self._company_info:
            ctx_parts.append(f"[Company] {self._company_info[:800]}")
        if self._glossary:
            terms = [f"{g['jp']}({g.get('reading','')}) = {g.get('vi','')}" for g in self._glossary[:30]]
            ctx_parts.append("[Glossary]\n" + "\n".join(terms))
        if self._recent_transcript:
            lines = []
            for e in self._recent_transcript[-3:]:
                sp = "You" if e.get("speaker") == "me" else "Interviewer"
                lines.append(f"  {sp}: {e.get('ja', '')}")
            ctx_parts.append("[Recent]\n" + "\n".join(lines))
        if ctx_parts:
            parts.append("\n" + "\n".join(ctx_parts))

        return "\n".join(parts)

    def _request_answer_streaming(self, ja: str, vi_azure: str, request_type: str = "suggestion") -> dict:
        lang = self._source_language_name
        system = self._build_system_prompt(lang)
        user_msg = f"Interviewer: {ja}"
        if vi_azure:
            user_msg += f"\n(VI: {vi_azure})"

        collected = ""
        current_field = "answer_primary"
        delim_switched = False
        ja_buffer = ""
        ja_token_count = 0
        ja_is_first_flush = True
        ja_last_flush_time = time.time()
        all_romaji_parts: list[str] = []
        all_vi = ""
        usage_data: dict | None = None
        t0 = time.time()

        try:
            max_tokens = self._max_tokens_for_length(self._answer_length)
            is_reasoning = _is_reasoning_model(self._active_deployment)
            if is_reasoning:
                max_tokens = max(max_tokens * 4, 3600)
            create_kwargs = {
                "model": self._active_deployment,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                "max_completion_tokens": max_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if not is_reasoning:
                create_kwargs["temperature"] = 0.7
            stream = self._active_client.chat.completions.create(**create_kwargs)

            for chunk in stream:
                if not self._running:
                    break
                if hasattr(chunk, "usage") and chunk.usage:
                    usage_data = {
                        "prompt_tokens": chunk.usage.prompt_tokens or 0,
                        "completion_tokens": chunk.usage.completion_tokens or 0,
                        "total_tokens": chunk.usage.total_tokens or 0,
                    }
                delta = chunk.choices[0].delta if chunk.choices else None
                if not (delta and delta.content):
                    continue

                token = delta.content
                collected += token

                if not delim_switched:
                    found = _find_delim(collected)
                    if found:
                        delim_switched = True
                        current_field = "answer_vi"
                        if lang == "Japanese" and ja_buffer.strip():
                            self._flush_ja_buffer(ja_buffer, all_romaji_parts)
                            ja_buffer = ""
                            ja_token_count = 0
                        after_delim = collected.split(found, 1)[1].lstrip("\n")
                        after_delim = _strip_section_prefix(after_delim)
                        if after_delim:
                            all_vi += after_delim
                            self._on_answer_streaming("answer_vi", after_delim)
                        continue

                if current_field == "answer_primary":
                    if _VI_DELIM_RE.search(token):
                        continue
                    if token.strip() and all(c == "-" for c in token.strip()):
                        ja_buffer += token
                        continue

                    if lang == "Japanese":
                        ja_buffer += token
                        ja_token_count += 1
                        threshold = _ROMAJI_FIRST_FLUSH if ja_is_first_flush else _ROMAJI_FLUSH_TOKENS
                        time_elapsed = time.time() - ja_last_flush_time
                        should_flush = (
                            any(c in token for c in _JA_SENTENCE_END)
                            or ja_token_count >= threshold
                            or (ja_buffer.strip() and time_elapsed >= _ROMAJI_FLUSH_MS)
                        )
                        if should_flush:
                            self._flush_ja_buffer(ja_buffer, all_romaji_parts)
                            ja_buffer = ""
                            ja_token_count = 0
                            ja_is_first_flush = False
                            ja_last_flush_time = time.time()
                    else:
                        clean_token = _strip_section_prefix(token) if not all_romaji_parts else token
                        if clean_token:
                            all_romaji_parts.append(clean_token)
                            self._on_answer_streaming("answer_romaji", clean_token)
                else:
                    all_vi += token
                    self._on_answer_streaming("answer_vi", token)

        except Exception as e:
            print(f"  [LLM STREAM ERR] model={self._active_deployment}: {e}", file=sys.stderr)
            self._on_error(f"LLM error: {str(e)[:80]}")
            return {"answer_vi": "", "answer_ja": "", "answer_romaji": ""}

        latency_ms = int((time.time() - t0) * 1000)

        if usage_data:
            usage_data["model"] = self._active_deployment
            usage_data["latency_ms"] = latency_ms
            usage_data["request_type"] = request_type
            try:
                self._on_usage(usage_data)
            except Exception as e:
                print(f"  [LLM USAGE CB ERR] {e}", file=sys.stderr)

        if lang == "Japanese" and ja_buffer.strip():
            self._flush_ja_buffer(ja_buffer, all_romaji_parts)

        final_romaji = " ".join(all_romaji_parts) if lang == "Japanese" else "".join(all_romaji_parts)
        if not all_vi:
            _, all_vi = self._parse_answer(collected)

        if lang == "Japanese" and all_vi:
            all_vi = self._clean_vi(all_vi)

        final_romaji = _clean_romaji(_strip_section_prefix(final_romaji))
        all_vi = _strip_section_prefix(all_vi).strip()

        result = {"answer_vi": all_vi, "answer_ja": "", "answer_romaji": final_romaji}
        print(f"  [LLM] Done model={self._active_deployment} romaji={len(final_romaji)}ch vi={len(all_vi)}ch {latency_ms}ms", file=sys.stderr)
        return result

    def _parse_answer(self, raw: str) -> tuple[str, str]:
        raw = raw.strip()
        if raw == "(empty)" or not raw:
            return "", ""
        found = _find_delim(raw)
        if found:
            parts = raw.split(found, 1)
            primary = _strip_section_prefix(parts[0].strip())
            vi = _strip_section_prefix(parts[1].strip()) if len(parts) > 1 else ""
        else:
            primary = ""
            vi = raw
        return primary, vi

    # -- Manual answer --

    def _process_manual(self, item: dict):
        text = item["text"]
        ai_refine = item["ai_refine"]
        recent_questions = [e for e in self._recent_transcript[-5:] if e.get("speaker") == "interviewer"]

        if ai_refine:
            prompt = self._build_manual_prompt_refine(text, recent_questions)
        else:
            prompt = self._build_manual_prompt_direct(text, recent_questions)

        collected = ""
        delim_switched = False
        ja_buffer = ""
        ja_token_count = 0
        all_romaji_parts: list[str] = []
        all_vi = ""
        lang = self._source_language_name
        usage_data: dict | None = None
        t0 = time.time()

        try:
            is_reasoning = _is_reasoning_model(self._active_deployment)
            max_tokens = 6400 if is_reasoning else 1600
            create_kwargs = {
                "model": self._active_deployment,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text},
                ],
                "max_completion_tokens": max_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if not is_reasoning:
                create_kwargs["temperature"] = 0.7
            stream = self._active_client.chat.completions.create(**create_kwargs)
            for chunk in stream:
                if not self._running:
                    return
                if hasattr(chunk, "usage") and chunk.usage:
                    usage_data = {
                        "prompt_tokens": chunk.usage.prompt_tokens or 0,
                        "completion_tokens": chunk.usage.completion_tokens or 0,
                        "total_tokens": chunk.usage.total_tokens or 0,
                    }
                delta = chunk.choices[0].delta if chunk.choices else None
                if not (delta and delta.content):
                    continue
                token = delta.content
                collected += token

                if not delim_switched:
                    found = _find_delim(collected)
                    if found:
                        delim_switched = True
                        if lang == "Japanese" and ja_buffer.strip():
                            self._flush_ja_buffer(ja_buffer, all_romaji_parts)
                            ja_buffer = ""
                        after = collected.split(found, 1)[1].lstrip("\n")
                        after = _strip_section_prefix(after)
                        if after:
                            all_vi += after
                            self._on_answer_streaming("answer_vi", after)
                        continue

                if not delim_switched:
                    if lang == "Japanese":
                        ja_buffer += token
                        ja_token_count += 1
                        if any(c in token for c in _JA_SENTENCE_END) or ja_token_count >= _ROMAJI_FLUSH_TOKENS:
                            self._flush_ja_buffer(ja_buffer, all_romaji_parts)
                            ja_buffer = ""
                            ja_token_count = 0
                    else:
                        clean = _strip_section_prefix(token) if not all_romaji_parts else token
                        if clean:
                            all_romaji_parts.append(clean)
                            self._on_answer_streaming("answer_romaji", clean)
                else:
                    all_vi += token
                    self._on_answer_streaming("answer_vi", token)

        except Exception as e:
            print(f"  [LLM MANUAL ERR] {e}", file=sys.stderr)
            self._on_error(f"LLM manual: {str(e)[:60]}")
            self._on_manual_result({"answer_vi": text, "answer_ja": "", "answer_romaji": "", "original_text": text})
            return

        latency_ms = int((time.time() - t0) * 1000)
        if usage_data:
            usage_data["model"] = self._active_deployment
            usage_data["latency_ms"] = latency_ms
            usage_data["request_type"] = "manual"
            try:
                self._on_usage(usage_data)
            except Exception as e:
                print(f"  [LLM USAGE CB ERR] {e}", file=sys.stderr)

        if lang == "Japanese" and ja_buffer.strip():
            self._flush_ja_buffer(ja_buffer, all_romaji_parts)
        final_romaji = " ".join(all_romaji_parts) if lang == "Japanese" else "".join(all_romaji_parts)
        if not all_vi:
            _, all_vi = self._parse_answer(collected)
        if lang == "Japanese" and all_vi:
            all_vi = self._clean_vi(all_vi)
        final_romaji = _clean_romaji(_strip_section_prefix(final_romaji))
        all_vi = _strip_section_prefix(all_vi).strip()

        result = {"answer_vi": all_vi, "answer_ja": "", "answer_romaji": final_romaji, "original_text": text}
        self._on_manual_result(result)

    def _build_manual_prompt_refine(self, text: str, recent_questions: list[dict]) -> str:
        lang = self._source_language_name
        parts = [
            "Expert interview coach. Candidate wrote a draft answer in Vietnamese.",
            f"1. Improve it professionally. 2. Translate to {lang}.",
        ]
        if self._has_romaji:
            parts.append("3. Generate romaji.")
        parts += ['Output ONLY JSON: "answer_vi", "answer_ja"' + (', "answer_romaji"' if self._has_romaji else "")]
        if self._personal_info:
            parts.append(f"\nCandidate: {self._personal_info[:2000]}")
        if recent_questions:
            q = "\n".join(f"  Q: {e.get('ja','')} -> {e.get('vi','')}" for e in recent_questions[-3:])
            parts.append(f"\nRecent questions:\n{q}")
        return "\n".join(parts)

    def _build_manual_prompt_direct(self, text: str, recent_questions: list[dict]) -> str:
        lang = self._source_language_name
        parts = [
            f"Translate Vietnamese to {lang}. Keep meaning exactly.",
            'Output ONLY JSON: "answer_vi" (unchanged), "answer_ja"' + (', "answer_romaji"' if self._has_romaji else ""),
        ]
        if recent_questions:
            q = "\n".join(f"  Q: {e.get('ja','')} -> {e.get('vi','')}" for e in recent_questions[-3:])
            parts.append(f"\nContext:\n{q}")
        return "\n".join(parts)

    def _parse_manual_result(self, raw: str, original_text: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[:-3]
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            return {"answer_vi": original_text, "answer_ja": "", "answer_romaji": ""}
        return {
            "answer_vi": result.get("answer_vi", original_text),
            "answer_ja": result.get("answer_ja", ""),
            "answer_romaji": result.get("answer_romaji", ""),
        }
