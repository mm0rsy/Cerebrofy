"""HTML renderer for the Onboarding Navigator (no external deps)."""
from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cerebrofy.onboard.planner import OnboardPlan

_CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
     max-width:900px;margin:0 auto;padding:2rem;color:#24292e;line-height:1.6}
h1{border-bottom:2px solid #e1e4e8;padding-bottom:.5rem}
h2{border-bottom:1px solid #e1e4e8;padding-bottom:.3rem;color:#0366d6;margin-top:2rem}
h3{color:#24292e}
table{border-collapse:collapse;width:100%;margin:1rem 0}
th,td{border:1px solid #e1e4e8;padding:.5rem .75rem;text-align:left}
th{background:#f6f8fa;font-weight:600}
tr:nth-child(even){background:#f6f8fa}
code{background:#f6f8fa;padding:.1em .4em;border-radius:3px;
     font-family:"SFMono-Regular",Consolas,monospace;font-size:.9em}
pre{background:#f6f8fa;padding:1rem;border-radius:6px;overflow-x:auto}
pre code{background:none;padding:0}
ul{padding-left:1.5rem}
li{margin:.25rem 0}
hr{border:none;border-top:1px solid #e1e4e8;margin:2rem 0}
em{color:#6a737d}
"""


def render_html(plan: OnboardPlan) -> str:
    """Produce a self-contained ONBOARDING.html from an OnboardPlan."""
    from cerebrofy.onboard.renderer import render_markdown
    md = render_markdown(plan)
    body = _md_to_html(md)
    title = html.escape(f"Onboarding — {plan.repo_name}")
    return (
        "<!DOCTYPE html>\n<html lang='en'>\n<head>\n"
        "<meta charset='UTF-8'>\n"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>\n"
        f"<title>{title}</title>\n"
        f"<style>{_CSS}</style>\n"
        f"</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def _md_to_html(md: str) -> str:
    """Minimal Markdown → HTML (no external deps)."""
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    in_list = False
    in_pre = False

    while i < len(lines):
        line = lines[i]

        # Fenced code blocks
        if line.startswith("```"):
            if in_pre:
                out.append("</code></pre>")
                in_pre = False
            else:
                if in_list:
                    out.append("</ul>")
                    in_list = False
                out.append("<pre><code>")
                in_pre = True
            i += 1
            continue

        if in_pre:
            out.append(html.escape(line))
            i += 1
            continue

        # Strip HTML comments
        if line.startswith("<!--"):
            i += 1
            continue

        # Headings
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        # Horizontal rule
        if line.strip() == "---":
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<hr>")
            i += 1
            continue

        # Table — collect all consecutive pipe lines
        if line.startswith("|"):
            if in_list:
                out.append("</ul>")
                in_list = False
            table_lines: list[str] = []
            while i < len(lines) and lines[i].startswith("|"):
                table_lines.append(lines[i])
                i += 1
            out.append(_table(table_lines))
            continue

        # Unordered list item
        if re.match(r"^- ", line):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(line[2:])}</li>")
            i += 1
            continue

        # Blank line
        if not line.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
            i += 1
            continue

        # Paragraph
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{_inline(line)}</p>")
        i += 1

    if in_list:
        out.append("</ul>")
    if in_pre:
        out.append("</code></pre>")

    return "\n".join(out)


def _table(lines: list[str]) -> str:
    """Convert Markdown table lines to an HTML table."""
    rows: list[list[str]] = []
    for line in lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)

    if len(rows) < 2:
        return ""

    parts = ["<table><thead><tr>"]
    for cell in rows[0]:
        parts.append(f"<th>{_inline(cell)}</th>")
    parts.append("</tr></thead><tbody>")

    # Skip separator row at index 1 (|---|---|)
    for row in rows[2:]:
        parts.append("<tr>")
        for cell in row:
            parts.append(f"<td>{_inline(cell)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "\n".join(parts)


def _inline(text: str) -> str:
    """Apply inline Markdown: escape HTML, then bold, italic, code."""
    text = html.escape(text, quote=False)
    # Inline code first (prevent bold/italic inside code spans)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Bold
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    # Italic (underscore-bounded, not mid-word)
    text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", text)
    return text
