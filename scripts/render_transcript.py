#!/usr/bin/env python3
"""Render a chat.py --record JSONL into docs/examples Markdown and an SVG excerpt.

    python scripts/render_transcript.py RECORD.jsonl docs/examples/onboarding-session.md docs/assets/transcript.svg
"""
import html
import json
import sys
import textwrap


def load(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def to_markdown(turns):
    out = ["# Annotated session: onboarding an indie developer", "",
           "Generated locally with `make chat ARGS=\"--script docs/examples/scripts/onboarding.txt --record ...\"` "
           "against the production prompt, tools and classifier. DynamoDB is mocked in-process; the model calls are real. "
           "Phone number is a placeholder.", ""]
    total_cost = 0.0
    for i, t in enumerate(turns, 1):
        user = "START (opt-in)" if t["user"] == "[USER_OPTED_IN]" else t["user"]
        out += [f"## Turn {i}", "", f"**You:** {user}", "",
                f"**Stride:** {t['reply']}", "",
                f"<sub>{t['chars']} chars · {t['segments']} SMS segment{'s' if t['segments'] > 1 else ''}</sub>", "",
                "<details><summary>Under the hood</summary>", ""]
        out += [f"- Intent (Haiku): `{t['intent']}`"]
        if t["tools"]:
            out += ["- Tool calls, in order:"]
            for c in t["tools"]:
                args = ", ".join(f"{k}={json.dumps(v)}" for k, v in c["input"].items())
                out += [f"  - `{c['name']}({args})`"]
        else:
            out += ["- Tool calls: none"]
        out += [f"- Tokens: {t['input_tokens']} in · {t['output_tokens']} out · "
                f"{t['cache_read']} cache read · {t['cache_write']} cache write",
                f"- Latency: {t['latency_ms']} ms · est. cost ${t['cost_usd']:.4f}", "",
                "</details>", ""]
        total_cost += t["cost_usd"]
    out += ["---", "", f"Session total: {len(turns)} turns, est. ${total_cost:.4f}."]
    return "\n".join(out) + "\n"


def to_svg(turns, max_turns=3, width=360):
    """Phone-style bubbles for the first few turns. Manual wrapping; SVG has no flow layout."""
    lines = []  # (side, text_lines)
    for t in turns[:max_turns]:
        if t["user"] != "[USER_OPTED_IN]":
            lines.append(("me", textwrap.wrap(t["user"], 34)))
        lines.append(("stride", textwrap.wrap(t["reply"], 34)))
    lh, pad, gap = 18, 10, 12
    y = 20
    parts = []
    for side, tl in lines:
        h = lh * len(tl) + pad * 2
        w = min(width - 40, max(len(s) for s in tl) * 7.2 + pad * 2)
        x = width - 20 - w if side == "me" else 20
        fill = "#2563eb" if side == "me" else "#e5e7eb"
        color = "#ffffff" if side == "me" else "#111827"
        parts.append(f'<rect x="{x:.0f}" y="{y}" rx="14" ry="14" width="{w:.0f}" height="{h}" fill="{fill}"/>')
        for j, s in enumerate(tl):
            parts.append(f'<text x="{x + pad:.0f}" y="{y + pad + lh * (j + 1) - 5}" font-size="13" '
                         f'font-family="-apple-system, Segoe UI, Helvetica, Arial, sans-serif" fill="{color}">{html.escape(s)}</text>')
        y += h + gap
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{y}" viewBox="0 0 {width} {y}">'
            f'<rect width="{width}" height="{y}" fill="#ffffff"/>' + "".join(parts) + "</svg>\n")


if __name__ == "__main__":
    record, md_out, svg_out = sys.argv[1:4]
    turns = load(record)
    with open(md_out, "w") as f:
        f.write(to_markdown(turns))
    with open(svg_out, "w") as f:
        f.write(to_svg(turns))
    print(f"wrote {md_out} ({len(turns)} turns) and {svg_out}")
