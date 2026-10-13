from pathlib import Path

WIKI = Path(__file__).resolve().parents[2] / "llm_wiki"


def retrieve(query, limit=18000):
    """Bounded lexical retrieval, not the unbounded contents of the entire wiki."""
    terms = set(query.lower().split())
    documents = []
    for path in WIKI.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        score = sum(term in text.lower() for term in terms) + (20 if "03_rules" in str(path) else 0)
        documents.append((score, path.relative_to(WIKI).as_posix(), text))
    output, used = [], 0
    for _, name, text in sorted(documents, reverse=True):
        text = text[:max(0, limit-used)]
        if not text:
            break
        output.append({"document": name, "text": text})
        used += len(text)
    return output
