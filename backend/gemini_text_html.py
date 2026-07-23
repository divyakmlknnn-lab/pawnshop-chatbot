"""Convert Gemini text responses to safe HTML for the frontend."""

from __future__ import annotations

import html
import re

import bleach
import markdown

ALLOWED_TAGS = [
    "p",
    "br",
    "strong",
    "em",
    "b",
    "i",
    "u",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "a",
    "code",
    "pre",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "blockquote",
    "hr",
]

ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel"],
    "th": ["scope"],
    "td": ["colspan", "rowspan"],
}

_HTML_TAG_PATTERN = re.compile(
    r"<\s*(?:p|div|ul|ol|li|table|thead|tbody|tr|th|td|h[1-6]|blockquote|pre|hr|br|strong|em|b|i|a|code)\b",
    re.IGNORECASE,
)

_MARKDOWN_LIST_LINE = re.compile(r"(?m)^\s*(?:[\*\-]\s+\S|\d+\.\s+\S)")


def looks_like_html(text: str) -> bool:
    """Return True when the text appears to already contain HTML markup."""
    stripped = (text or "").strip()
    if not stripped.startswith("<"):
        return False
    return bool(_HTML_TAG_PATTERN.search(stripped))


def _sanitize_html(fragment: str) -> str:
    return bleach.clean(
        fragment,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True,
    ).strip()


def _contains_markdown_list_syntax(text: str) -> bool:
    """Return True when plain-text Markdown list markers appear in the content."""
    return bool(_MARKDOWN_LIST_LINE.search(text or ""))


def _ensure_blank_line_before_lists(text: str) -> str:
    """Insert a blank line before list markers so Markdown parsers recognize them."""
    return re.sub(
        r"(?m)(?<=\S)\n(\s*(?:[\*\-]\s+\S|\d+\.\s+\S))",
        r"\n\n\1",
        text,
    )


def _html_with_markdown_lists_to_markdown(text: str) -> str:
    """Normalize hybrid Gemini HTML so Markdown conversion can run on list lines."""
    normalized = text
    for pattern, replacement in (
        (r"<strong>(.*?)</strong>", r"**\1**"),
        (r"<b>(.*?)</b>", r"**\1**"),
        (r"<em>(.*?)</em>", r"*\1*"),
        (r"<i>(.*?)</i>", r"*\1*"),
    ):
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE | re.DOTALL)
    normalized = re.sub(r"<br\s*/?>", "\n", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"</p\s*>", "\n\n", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"<p[^>]*>", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"</div\s*>", "\n\n", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"<div[^>]*>", "", normalized, flags=re.IGNORECASE)
    normalized = bleach.clean(normalized, tags=[], attributes={}, strip=True)
    return _ensure_blank_line_before_lists(html.unescape(normalized).strip())


def _render_markdown(raw: str) -> str:
    rendered = markdown.markdown(
        raw,
        extensions=["extra", "nl2br", "sane_lists"],
    )
    return _sanitize_html(rendered)


def gemini_text_to_html(text: str) -> str:
    """Render Gemini output as safe HTML, converting Markdown when needed."""
    raw = (text or "").strip()
    if not raw:
        return '<p class="empty-message"></p>'

    if looks_like_html(raw):
        if _contains_markdown_list_syntax(raw):
            body = _render_markdown(_html_with_markdown_lists_to_markdown(raw))
        else:
            body = _sanitize_html(raw)
    else:
        body = _render_markdown(raw)

    if not body:
        return f'<p class="empty-message">{html.escape(raw)}</p>'
    return body
