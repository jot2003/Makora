"""Document processing: extract text from PDF/DOCX/TXT, extract keywords for Phrase List."""

import re
import shutil
from pathlib import Path
from typing import Optional


def extract_text(file_path: str) -> str:
    """Extract plain text from PDF, DOCX, or TXT file."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")

    if suffix == ".pdf":
        return _extract_pdf(path)

    if suffix in (".docx", ".doc"):
        return _extract_docx(path)

    raise ValueError(f"Unsupported file type: {suffix}")


def _extract_pdf(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("pdfplumber required for PDF: pip install pdfplumber")

    text_parts = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n\n".join(text_parts)


def _extract_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError:
        raise ImportError("python-docx required for DOCX: pip install python-docx")

    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


_JP_PATTERN = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uFF00-\uFFEF]+")
_KATAKANA_WORD = re.compile(r"[\u30A0-\u30FF]{2,}")
_KANJI_WORD = re.compile(r"[\u4E00-\u9FFF]{2,}")

_EN_WORD = re.compile(r"\b[A-Za-z][A-Za-z''-]{2,}\b")
_EN_STOPWORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "any",
    "can", "had", "her", "was", "one", "our", "out", "has", "his",
    "how", "its", "may", "new", "now", "old", "see", "way", "who",
    "did", "get", "let", "say", "she", "too", "use", "will", "with",
    "this", "that", "have", "from", "they", "been", "said", "each",
    "which", "their", "about", "would", "there", "could", "other",
    "into", "more", "some", "than", "them", "very", "when", "what",
    "your", "also", "just", "most", "only", "over", "such", "take",
    "because", "these", "those", "should", "between", "through",
})


def extract_keywords(text: str, max_keywords: int = 200, language: str = "ja-JP") -> list[str]:
    """Extract keywords from text for Azure Speech Phrase List.

    Supports Japanese (kanji, katakana) and English (significant words).
    """
    if language.startswith("en"):
        return _extract_english_keywords(text, max_keywords)
    return _extract_japanese_keywords(text, max_keywords)


def _extract_japanese_keywords(text: str, max_keywords: int) -> list[str]:
    keywords = set()
    for match in _KATAKANA_WORD.finditer(text):
        keywords.add(match.group())
    for match in _KANJI_WORD.finditer(text):
        keywords.add(match.group())
    sorted_kw = sorted(keywords, key=lambda w: (-len(w), w))
    return sorted_kw[:max_keywords]


def _extract_english_keywords(text: str, max_keywords: int) -> list[str]:
    words: dict[str, int] = {}
    for match in _EN_WORD.finditer(text):
        w = match.group().lower()
        if w not in _EN_STOPWORDS and len(w) > 2:
            words[w] = words.get(w, 0) + 1
    sorted_kw = sorted(words, key=lambda w: (-words[w], w))
    return sorted_kw[:max_keywords]


def copy_to_session(source_path: str, session_docs_dir: Path) -> Path:
    """Copy a document file into the session's documents directory."""
    session_docs_dir.mkdir(parents=True, exist_ok=True)
    src = Path(source_path)
    dest = session_docs_dir / src.name

    counter = 1
    while dest.exists():
        dest = session_docs_dir / f"{src.stem}_{counter}{src.suffix}"
        counter += 1

    shutil.copy2(str(src), str(dest))
    return dest


def get_all_text_from_session(session_docs_dir: Path) -> str:
    """Extract and concatenate text from all documents in a session."""
    if not session_docs_dir.exists():
        return ""

    all_text = []
    for f in sorted(session_docs_dir.iterdir()):
        if f.suffix.lower() in (".txt", ".pdf", ".docx", ".doc"):
            try:
                all_text.append(extract_text(str(f)))
            except Exception:
                continue
    return "\n\n".join(all_text)


def get_text_by_category(
    session_docs_dir: Path,
    doc_meta: dict[str, str],
    notes: dict[str, str] | None = None,
) -> dict[str, str]:
    """Extract text grouped by category.

    Returns {"personal": "...", "company": "..."} with concatenated text per category.
    ``notes`` is an optional dict {"personal": "...", "company": "..."} of manual notes
    that will be prepended to each category.
    """
    result: dict[str, list[str]] = {"personal": [], "company": [], "general": []}

    if notes:
        for cat in ("personal", "company", "general"):
            txt = notes.get(cat, "").strip()
            if txt:
                result[cat].append(txt)

    if session_docs_dir.exists():
        for f in sorted(session_docs_dir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in (".txt", ".pdf", ".docx", ".doc"):
                continue
            try:
                text = extract_text(str(f))
            except Exception:
                continue
            category = doc_meta.get(f.name, "company")
            if category in result:
                result[category].append(text)

    return {k: "\n\n".join(v) for k, v in result.items()}
