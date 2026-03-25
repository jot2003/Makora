"""LLM Engine: Azure OpenAI streaming for answer suggestions.

Architecture:
  - Fast model for auto answer suggestions
  - Main model for manual answer refinement
  - JP: LLM outputs Japanese -> pykakasi converts progressively to romaji (every ~5 tokens)
  - EN: LLM outputs English directly (streamed)
  - Vietnamese TRANSLATION follows after delimiter
"""

import json
import re
import sys
import time
import threading
import pykakasi
from openai import AzureOpenAI
from PyQt6.QtCore import QThread, pyqtSignal

_VI_DELIM_RE = re.compile(r'-{2,}\s*VI\s*-{0,}')
_ROMAJI_DELIM_CLEANUP = re.compile(r'-{2,}\s*vi\s*-{0,}', re.IGNORECASE)
_JA_CHAR_RE = re.compile(r'[\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\u4e00-\u9faf]')
_JA_SENTENCE_END = frozenset("。！？\n")
_SECTION_PREFIX_RE = re.compile(r'^(?:SECTION|Part)\s*\d*\s*:?\s*', re.IGNORECASE)

_ROMAJI_FLUSH_TOKENS = 5


def _find_delim(text: str) -> str | None:
    m = _VI_DELIM_RE.search(text)
    return m.group(0) if m else None


def _strip_section_prefix(text: str) -> str:
    return _SECTION_PREFIX_RE.sub("", text)


def _clean_romaji(text: str) -> str:
    """Strip any residual delimiter patterns from romaji output."""
    return _ROMAJI_DELIM_CLEANUP.sub("", text).strip().rstrip("-").strip()


class LLMEngine(QThread):
    tier2_result = pyqtSignal(dict)
    answer_streaming = pyqtSignal(str, str)   # (field, chunk)
    manual_answer_result = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, api_key: str, endpoint: str, deployment: str,
                 fast_deployment: str = ""):
        super().__init__()
        self._client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version="2024-12-01-preview",
        )
        self._deployment = deployment
        self._fast_deployment = fast_deployment or deployment
        self._queue: list[dict] = []
        self._running = False
        self._personal_info = ""
        self._company_info = ""
        self._general_context = ""
        self._glossary: list[dict] = []
        self._recent_transcript: list[dict] = []
        self._source_language_name = "Japanese"
        self._has_romaji = True

        self._kakasi = pykakasi.kakasi()
        self._kakasi_lock = threading.Lock()

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

    def enqueue(self, ja: str, romaji_azure: str, vi_azure: str):
        self._queue.append({"type": "tier2", "ja": ja, "romaji_azure": romaji_azure, "vi_azure": vi_azure})

    def enqueue_manual(self, text: str, ai_refine: bool):
        self._queue.append({"type": "manual", "text": text, "ai_refine": ai_refine})

    def add_user_speech(self, ja: str, vi: str):
        self._recent_transcript.append({"speaker": "me", "ja": ja, "vi": vi})
        if len(self._recent_transcript) > 10:
            self._recent_transcript = self._recent_transcript[-10:]

    def stop(self):
        self._running = False

    def _create_with_fallback(self, kwargs: dict):
        try:
            kwargs["reasoning_effort"] = "low"
            return self._client.chat.completions.create(**kwargs)
        except Exception:
            kwargs.pop("reasoning_effort", None)
            kwargs.pop("temperature", None)
            return self._client.chat.completions.create(**kwargs)

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
        """Convert ja_buffer to romaji, append to parts, optionally emit, return romaji."""
        clean = _VI_DELIM_RE.sub("", ja_buffer).strip().rstrip("-").strip()
        clean = _strip_section_prefix(clean)
        if not clean:
            return ""
        romaji = self._ja_to_romaji(clean)
        romaji = _clean_romaji(romaji)
        if romaji:
            all_romaji_parts.append(romaji)
            if emit:
                self.answer_streaming.emit("answer_romaji", romaji + " ")
        return romaji

    def run(self):
        self._running = True
        while self._running:
            if not self._queue:
                self.msleep(50)
                continue

            item = self._queue.pop(-1)

            if item.get("type") == "tier2" and self._queue:
                skipped = [i for i in self._queue if i.get("type") == "tier2"]
                self._queue = [i for i in self._queue if i.get("type") != "tier2"]
                if skipped:
                    print(f"  [LLM] Bỏ {len(skipped)} câu cũ, xử lý câu mới nhất")

            try:
                if item.get("type") == "manual":
                    self._process_manual(item)
                else:
                    print(f"  [LLM] Answer: {item.get('ja', '')[:40]}...")
                    sys.stdout.flush()
                    self._process_answer(item)
            except Exception as e:
                self.error_occurred.emit(f"LLM: {str(e)[:80]}")
                print(f"  [LLM ERROR] {e}", file=sys.stderr)
                sys.stderr.flush()

    # ── Answer generation ─────────────────────────────────────

    def _process_answer(self, item: dict):
        ja = item["ja"]
        vi_azure = item["vi_azure"]

        result = self._request_answer_streaming(ja, vi_azure)
        result["ja_fixed"] = ja
        result["romaji"] = item.get("romaji_azure", "")
        result["vi_refined"] = vi_azure
        self.tier2_result.emit(result)

        self._recent_transcript.append({
            "speaker": "interviewer",
            "ja": ja,
            "vi": vi_azure,
        })
        if len(self._recent_transcript) > 10:
            self._recent_transcript = self._recent_transcript[-10:]

    def _build_system_prompt(self, lang: str) -> str:
        if lang == "Japanese":
            parts = [
                "Interview answer coach. Vietnamese candidate, Japanese interview.",
                "Suggest a natural spoken answer.",
                "",
                "FORMAT — output exactly TWO blocks separated by ---VI--- :",
                "",
                "[Japanese answer in kanji/kana — NO prefix, NO label, just the answer text]",
                "---VI---",
                "[Vietnamese translation — normal spacing, translate only, NO explanation]",
                "",
                "CRITICAL: Do NOT write 'SECTION', 'Part', labels, or markdown.",
                "CRITICAL: Vietnamese block must be proper Vietnamese with spaces between words.",
                "",
                "LENGTH:",
                "- あいさつ/greeting → (empty)",
                "- Simple → 1-2 sentences  |  Standard → 2-3 sentences",
                "- Detailed (具体例/経験) → 3-5 sentences with real examples",
                "",
                "STYLE: natural spoken Japanese, use candidate's real info.",
            ]
        elif lang == "English":
            parts = [
                "Interview answer coach. Vietnamese candidate, English interview.",
                "Suggest a natural spoken answer.",
                "",
                "FORMAT — output exactly TWO blocks separated by ---VI--- :",
                "",
                "[English answer — NO prefix, NO label, just the answer text]",
                "---VI---",
                "[Vietnamese translation — normal spacing, translate only, NO explanation]",
                "",
                "CRITICAL: Do NOT write 'SECTION', 'Part', labels, or markdown.",
                "",
                "LENGTH:",
                "- Greeting → (empty)",
                "- Simple → 1-2 sentences  |  Standard → 2-3 sentences",
                "- Detailed → 3-5 sentences with real examples",
                "",
                "STYLE: natural spoken English, polite, use candidate's real info.",
            ]
        else:
            parts = [
                f"Interview coach. Vietnamese candidate, {lang} interview.",
                f"Answer in {lang}, then ---VI---, then Vietnamese translation.",
            ]

        ctx_parts = []
        if self._general_context:
            ctx_parts.append(f"[Context] {self._general_context[:1200]}")
        if self._personal_info:
            ctx_parts.append(f"[Candidate] {self._personal_info[:1500]}")
        if self._company_info:
            ctx_parts.append(f"[Company] {self._company_info[:800]}")
        if self._recent_transcript:
            lines = []
            for e in self._recent_transcript[-3:]:
                sp = "You" if e.get("speaker") == "me" else "Interviewer"
                lines.append(f"  {sp}: {e.get('ja', '')}")
            ctx_parts.append("[Recent]\n" + "\n".join(lines))
        if ctx_parts:
            parts.append("\n" + "\n".join(ctx_parts))

        return "\n".join(parts)

    def _request_answer_streaming(self, ja: str, vi_azure: str) -> dict:
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
        all_romaji_parts: list[str] = []
        all_vi = ""

        try:
            create_kwargs = {
                "model": self._fast_deployment,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                "max_completion_tokens": 900,
                "stream": True,
            }
            stream = self._create_with_fallback(create_kwargs)

            for chunk in stream:
                if not self._running:
                    break
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
                            self.answer_streaming.emit("answer_vi", after_delim)
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
                        should_flush = (
                            any(c in token for c in _JA_SENTENCE_END)
                            or ja_token_count >= _ROMAJI_FLUSH_TOKENS
                        )
                        if should_flush:
                            self._flush_ja_buffer(ja_buffer, all_romaji_parts)
                            ja_buffer = ""
                            ja_token_count = 0
                    else:
                        clean_token = _strip_section_prefix(token) if not all_romaji_parts else token
                        if clean_token:
                            all_romaji_parts.append(clean_token)
                            self.answer_streaming.emit("answer_romaji", clean_token)
                else:
                    all_vi += token
                    self.answer_streaming.emit("answer_vi", token)

        except Exception as e:
            self.error_occurred.emit(f"LLM answer: {str(e)[:60]}")
            print(f"  [LLM STREAM ERR] {e}", file=sys.stderr)
            return {"answer_vi": "", "answer_ja": "", "answer_romaji": ""}

        if lang == "Japanese" and ja_buffer.strip():
            self._flush_ja_buffer(ja_buffer, all_romaji_parts)

        final_romaji = " ".join(all_romaji_parts) if lang == "Japanese" else "".join(all_romaji_parts)
        if not all_vi:
            _, all_vi = self._parse_answer(collected)

        if lang == "Japanese" and all_vi:
            all_vi = self._clean_vi(all_vi)

        final_romaji = _clean_romaji(_strip_section_prefix(final_romaji))
        all_vi = _strip_section_prefix(all_vi).strip()

        print(f"  [LLM] Answer done: romaji={len(final_romaji)}c vi={len(all_vi)}c")
        sys.stdout.flush()
        return {"answer_vi": all_vi, "answer_ja": "", "answer_romaji": final_romaji}

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

    # ── Manual answer ─────────────────────────────────────────

    def _process_manual(self, item: dict):
        text = item["text"]
        ai_refine = item["ai_refine"]

        recent_questions = [
            e for e in self._recent_transcript[-5:]
            if e.get("speaker") == "interviewer"
        ]

        if ai_refine:
            prompt = self._build_manual_prompt_refine(text, recent_questions)
        else:
            prompt = self._build_manual_prompt_direct(text, recent_questions)

        collected = ""
        try:
            create_kwargs = {
                "model": self._deployment,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text},
                ],
                "max_completion_tokens": 1600,
                "stream": True,
            }
            stream = self._create_with_fallback(create_kwargs)

            for chunk in stream:
                if not self._running:
                    return
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    collected += delta.content
        except Exception as e:
            self.error_occurred.emit(f"LLM manual: {str(e)[:60]}")
            self.manual_answer_result.emit({
                "answer_vi": text, "answer_ja": "", "answer_romaji": "", "original_text": text,
            })
            return

        result = self._parse_manual_result(collected, text)
        result["original_text"] = text
        self.manual_answer_result.emit(result)

    def _build_manual_prompt_refine(self, text: str, recent_questions: list[dict]) -> str:
        lang = self._source_language_name
        parts = [
            "Expert interview coach. Candidate wrote a draft answer in Vietnamese.",
            f"1. Improve it professionally. 2. Translate to {lang}.",
        ]
        if self._has_romaji:
            parts.append("3. Generate romaji.")
        parts += [
            'Output ONLY JSON: "answer_vi", "answer_ja"' + (', "answer_romaji"' if self._has_romaji else ""),
        ]
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
