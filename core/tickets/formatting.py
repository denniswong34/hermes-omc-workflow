"""Helpers to turn plain text into Jira ADF / HTML snippets."""

from __future__ import annotations

from typing import Any


def plain_to_adf(text: str) -> dict[str, Any]:
    """Convert markdown-ish plain text into Jira Document Format."""
    content: list[dict[str, Any]] = []
    for raw_block in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw_block.rstrip()
        if not line.strip():
            continue
        if line.startswith("## "):
            content.append(
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": line[3:].strip() or "Section"}],
                }
            )
            continue
        if line.startswith("# "):
            content.append(
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [{"type": "text", "text": line[2:].strip() or "Section"}],
                }
            )
            continue
        if line.lstrip().startswith(("- ", "* ")):
            # Collect consecutive bullets into one list
            if content and content[-1].get("type") == "bulletList":
                content[-1]["content"].append(_adf_list_item(line.lstrip()[2:]))
            else:
                content.append(
                    {
                        "type": "bulletList",
                        "content": [_adf_list_item(line.lstrip()[2:])],
                    }
                )
            continue
        if line.startswith("> "):
            content.append(
                {
                    "type": "blockquote",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": line[2:]}],
                        }
                    ],
                }
            )
            continue
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": line}],
            }
        )

    if not content:
        content = [{"type": "paragraph", "content": [{"type": "text", "text": "(no description)"}]}]

    return {"type": "doc", "version": 1, "content": content}


def _adf_list_item(text: str) -> dict[str, Any]:
    return {
        "type": "listItem",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text or " "}],
            }
        ],
    }


def plain_to_html(text: str) -> str:
    """Minimal HTML for Plane descriptions/comments."""
    import html as html_lib

    parts: list[str] = []
    in_list = False
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            if in_list:
                parts.append("</ul>")
                in_list = False
            continue
        if line.startswith("## "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h3>{html_lib.escape(line[3:].strip())}</h3>")
            continue
        if line.lstrip().startswith(("- ", "* ")):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{html_lib.escape(line.lstrip()[2:])}</li>")
            continue
        if line.startswith("> "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<blockquote><p>{html_lib.escape(line[2:])}</p></blockquote>")
            continue
        if in_list:
            parts.append("</ul>")
            in_list = False
        parts.append(f"<p>{html_lib.escape(line)}</p>")
    if in_list:
        parts.append("</ul>")
    return "".join(parts) or "<p></p>"
