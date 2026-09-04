#!/usr/bin/env python3
"""Render a chat.py --trace JSON (one turn) as an SVG waterfall.

    python scripts/render_trace.py TRACE.json docs/assets/trace-waterfall.svg [--turn N]
"""
import html
import json
import sys

COLORS = {"stride": "#111827", "strands": "#2563eb", "tool": "#059669", "dynamodb": "#d97706", "other": "#6b7280"}


def kind(name):
    n = name.lower()
    if n.startswith("stride."):
        return "stride"
    if "dynamodb" in n:
        return "dynamodb"
    if n.startswith("tool") or n.startswith("execute_tool") or n.endswith("_tool"):
        return "tool"
    if any(k in n for k in ("agent", "cycle", "model", "invoke", "chat", "strands")):
        return "strands"
    return "other"


def pick_turn(spans, turn_index):
    roots = sorted([s for s in spans if s["parent_id"] is None], key=lambda s: s["start_ns"])
    root = roots[turn_index]
    by_parent = {}
    for s in spans:
        by_parent.setdefault(s["parent_id"], []).append(s)
    ordered = []

    def walk(node, depth):
        ordered.append((node, depth))
        for c in sorted(by_parent.get(node["span_id"], []), key=lambda s: s["start_ns"]):
            walk(c, depth + 1)

    walk(root, 0)
    return ordered


def render(ordered, width=900):
    t0 = ordered[0][0]["start_ns"]
    total = max(s["end_ns"] for s, _ in ordered) - t0 or 1
    label_w, row_h, top = 300, 22, 30
    height = top + row_h * len(ordered) + 30
    parts = [f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
             f'<text x="12" y="20" font-size="13" font-family="Helvetica, Arial, sans-serif" fill="#374151">'
             f'One SMS turn · {total / 1e6:.0f} ms · {len(ordered)} spans</text>']
    for i, (s, depth) in enumerate(ordered):
        y = top + i * row_h
        x0 = label_w + (s["start_ns"] - t0) / total * (width - label_w - 20)
        w = max(2, (s["end_ns"] - s["start_ns"]) / total * (width - label_w - 20))
        ms = (s["end_ns"] - s["start_ns"]) / 1e6
        name = s["name"] if len(s["name"]) <= 40 else s["name"][:37] + "..."
        parts.append(f'<text x="{12 + depth * 14}" y="{y + 15}" font-size="12" font-family="Menlo, Consolas, monospace" fill="#111827">{html.escape(name)}</text>')
        parts.append(f'<rect x="{x0:.1f}" y="{y + 4}" width="{w:.1f}" height="{row_h - 8}" rx="3" fill="{COLORS[kind(s["name"])]}"/>')
        parts.append(f'<text x="{min(x0 + w + 6, width - 60):.1f}" y="{y + 15}" font-size="11" font-family="Helvetica, Arial, sans-serif" fill="#6b7280">{ms:.0f} ms</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            + "".join(parts) + "</svg>\n")


if __name__ == "__main__":
    src, out = sys.argv[1:3]
    turn = int(sys.argv[sys.argv.index("--turn") + 1]) if "--turn" in sys.argv else 1
    spans = json.load(open(src))
    ordered = pick_turn(spans, turn)
    with open(out, "w") as f:
        f.write(render(ordered))
    print(f"wrote {out}: {len(ordered)} spans")
