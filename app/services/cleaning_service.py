"""Deterministic text normalization — no LLM involved. Runs after the
contract gate passes, before chunking."""
import re


def clean_text(raw_text: str) -> str:
    text = raw_text.replace("\n\n[PAGE_BREAK]\n\n", "\n\n")

    # Fix hyphenation broken across a PDF line-wrap, e.g. "confiden-\ntiality"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # Normalize unicode quotes/dashes to plain ASCII equivalents
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("–", "-").replace("—", "-")

    # Strip trailing whitespace per line, collapse 3+ blank lines to 2
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
