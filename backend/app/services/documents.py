"""Document text extraction and keyword analysis."""

import re
from pathlib import Path


STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "and", "but", "or",
    "nor", "not", "so", "yet", "for", "at", "by", "in", "of", "on", "to",
    "up", "out", "if", "then", "than", "too", "very", "just", "about",
    "that", "this", "with", "from", "into", "over", "after", "before",
    "between", "under", "above", "each", "every", "all", "both", "few",
    "more", "most", "other", "some", "such", "only", "own", "same",
}


def extract_text_from_file(filepath: str) -> str:
    """Extract text content from PDF, DOCX, or TXT files."""
    p = Path(filepath)
    ext = p.suffix.lower()

    if ext == ".txt":
        return p.read_text(encoding="utf-8", errors="replace")

    if ext == ".pdf":
        try:
            import pdfplumber
            texts = []
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        texts.append(t)
            return "\n".join(texts)
        except Exception:
            return ""

    if ext in (".docx", ".doc"):
        try:
            import docx
            doc = docx.Document(filepath)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            return ""

    return ""


def extract_keywords(text: str, max_keywords: int = 200) -> list[str]:
    """Extract meaningful keywords for STT phrase list boost."""
    if not text:
        return []

    keywords = set()

    # Japanese katakana words (2+ chars)
    katakana = re.findall(r'[\u30A0-\u30FF]{2,}', text)
    keywords.update(katakana)

    # Japanese kanji words (2+ chars)
    kanji = re.findall(r'[\u4E00-\u9FFF]{2,}', text)
    keywords.update(kanji)

    # English/romaji words (3+ chars, not stop words)
    en_words = re.findall(r'\b[A-Za-z]{3,}\b', text)
    for w in en_words:
        if w.lower() not in STOP_WORDS:
            keywords.add(w)

    result = sorted(keywords)
    return result[:max_keywords]
