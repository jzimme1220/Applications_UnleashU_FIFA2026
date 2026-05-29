#!/usr/bin/env python3
"""
Network inventory spreadsheet comparator (V5 vs V6).

Performs two independent key-based analyses (row order is ignored):
  1. Request Code (col D) -> Component (col W) mapping consistency
  2. Component (col W) -> Profile (col AI) relationship consistency

Results are printed to the terminal and exported to a scannable HTML report.
"""

from __future__ import annotations

import argparse
import html
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

# Excel column letters for this inventory layout
COL_REQUEST_CODE = "D"   # unique request identifier
COL_COMPONENT = "W"      # requested network component / service
COL_PROFILE = "AI"       # technical profile / site mapping identifier


def col_letter_to_index(letter: str) -> int:
    """Convert Excel column letter(s) to 0-based index (A=0, Z=25, AA=26, ...)."""
    index = 0
    for char in letter.upper():
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def normalize_cell(value: object) -> str | None:
    """Normalize a cell for comparison; treat blanks and NaN as missing."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text if text else None


@dataclass(frozen=True)
class KeyValueDelta:
    """A mismatch between two versions for a single logical key."""

    key: str
    v5_values: frozenset[str]
    v6_values: frozenset[str]
    issue: str  # e.g. 'changed', 'only_in_v5', 'only_in_v6', 'ambiguous_in_v5', ...

    @property
    def v5_display(self) -> str:
        return _format_value_set(self.v5_values)

    @property
    def v6_display(self) -> str:
        return _format_value_set(self.v6_values)


def _format_value_set(values: frozenset[str]) -> str:
    if not values:
        return "(missing)"
    if len(values) == 1:
        return next(iter(values))
    return " | ".join(sorted(values))


def load_inventory(path: Path, sheet: str | int | None) -> pd.DataFrame:
    """Load spreadsheet; all columns are kept so letter-based indexing stays valid."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return pd.read_excel(path, sheet_name=sheet if sheet is not None else 0, header=0)


def extract_column(df: pd.DataFrame, letter: str) -> pd.Series:
    """Return a series for the given Excel column letter (position-based)."""
    idx = col_letter_to_index(letter)
    if idx >= len(df.columns):
        raise ValueError(
            f"Column {letter} (index {idx}) is out of range; "
            f"file has {len(df.columns)} column(s)."
        )
    return df.iloc[:, idx]


def build_key_to_values(
    keys: pd.Series,
    values: pd.Series,
) -> tuple[dict[str, frozenset[str]], list[tuple[str, frozenset[str]]]]:
    """
    Build key -> set(values) from paired columns.

    Returns:
        mapping: each key to the set of distinct non-null values seen
        ambiguous: keys that map to more than one value (clerical error signal)
    """
    mapping: dict[str, set[str]] = {}
    for key_raw, value_raw in zip(keys, values, strict=False):
        key = normalize_cell(key_raw)
        if key is None:
            continue
        value = normalize_cell(value_raw)
        if value is None:
            continue
        mapping.setdefault(key, set()).add(value)

    ambiguous: list[tuple[str, frozenset[str]]] = []
    frozen: dict[str, frozenset[str]] = {}
    for key, value_set in mapping.items():
        frozen[key] = frozenset(value_set)
        if len(value_set) > 1:
            ambiguous.append((key, frozen[key]))
    return frozen, ambiguous


def compare_mappings(
    v5_map: dict[str, frozenset[str]],
    v6_map: dict[str, frozenset[str]],
    v5_ambiguous: list[tuple[str, frozenset[str]]],
    v6_ambiguous: list[tuple[str, frozenset[str]]],
) -> list[KeyValueDelta]:
    """
    Compare two key->values maps. Keys are unioned; both analyses always run fully.
    """
    deltas: list[KeyValueDelta] = []

    for key, values in v5_ambiguous:
        deltas.append(
            KeyValueDelta(
                key=key,
                v5_values=values,
                v6_values=v6_map.get(key, frozenset()),
                issue="ambiguous_in_v5",
            )
        )
    for key, values in v6_ambiguous:
        if key in {d.key for d in deltas if d.issue == "ambiguous_in_v5"}:
            continue
        deltas.append(
            KeyValueDelta(
                key=key,
                v5_values=v5_map.get(key, frozenset()),
                v6_values=values,
                issue="ambiguous_in_v6",
            )
        )

    seen_ambiguous = {d.key for d in deltas}
    all_keys = sorted(set(v5_map) | set(v6_map))

    for key in all_keys:
        if key in seen_ambiguous:
            continue
        v5_vals = v5_map.get(key, frozenset())
        v6_vals = v6_map.get(key, frozenset())
        if v5_vals == v6_vals:
            continue
        if not v5_vals:
            issue = "only_in_v6"
        elif not v6_vals:
            issue = "only_in_v5"
        else:
            issue = "changed"
        deltas.append(
            KeyValueDelta(key=key, v5_values=v5_vals, v6_values=v6_vals, issue=issue)
        )

    return deltas


def run_analysis_request_to_component(
    v5: pd.DataFrame,
    v6: pd.DataFrame,
) -> list[KeyValueDelta]:
    """Analysis 1: Request Code (D) -> Component (W)."""
    v5_map, v5_amb = build_key_to_values(
        extract_column(v5, COL_REQUEST_CODE),
        extract_column(v5, COL_COMPONENT),
    )
    v6_map, v6_amb = build_key_to_values(
        extract_column(v6, COL_REQUEST_CODE),
        extract_column(v6, COL_COMPONENT),
    )
    return compare_mappings(v5_map, v6_map, v5_amb, v6_amb)


def run_analysis_component_to_profile(
    v5: pd.DataFrame,
    v6: pd.DataFrame,
) -> list[KeyValueDelta]:
    """Analysis 2: Component (W) -> Profile (AI)."""
    v5_map, v5_amb = build_key_to_values(
        extract_column(v5, COL_COMPONENT),
        extract_column(v5, COL_PROFILE),
    )
    v6_map, v6_amb = build_key_to_values(
        extract_column(v6, COL_COMPONENT),
        extract_column(v6, COL_PROFILE),
    )
    return compare_mappings(v5_map, v6_map, v5_amb, v6_amb)


ISSUE_LABELS = {
    "changed": "Value changed between V5 and V6",
    "only_in_v5": "Present in V5 only (removed or re-keyed in V6)",
    "only_in_v6": "Present in V6 only (new or re-keyed from V5)",
    "ambiguous_in_v5": "Multiple distinct values for same key in V5 (copy/paste error?)",
    "ambiguous_in_v6": "Multiple distinct values for same key in V6 (copy/paste error?)",
}


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _issue_css_class(issue: str) -> str:
    return {
        "changed": "issue-changed",
        "only_in_v5": "issue-v5",
        "only_in_v6": "issue-v6",
        "ambiguous_in_v5": "issue-ambiguous",
        "ambiguous_in_v6": "issue-ambiguous",
    }.get(issue, "issue-other")


def _render_delta_table(
    deltas: list[KeyValueDelta],
    key_label: str,
    value_label: str,
) -> str:
    if not deltas:
        return '<p class="ok">No mismatches found.</p>'

    changed = [d for d in deltas if d.issue == "changed"]
    other = [d for d in deltas if d.issue != "changed"]
    parts: list[str] = []

    def table_rows(items: list[KeyValueDelta]) -> str:
        return "\n".join(
            f"<tr class=\"{_issue_css_class(d.issue)}\">"
            f"<td>{_esc(d.key)}</td>"
            f"<td><span class=\"badge {_issue_css_class(d.issue)}\">"
            f"{_esc(ISSUE_LABELS.get(d.issue, d.issue))}</span></td>"
            f"<td>{_esc(d.v5_display)}</td>"
            f"<td>{_esc(d.v6_display)}</td>"
            "</tr>"
            for d in items
        )

    header = (
        "<thead><tr>"
        f"<th>{_esc(key_label)}</th><th>Issue</th>"
        f"<th>V5 {_esc(value_label)}</th><th>V6 {_esc(value_label)}</th>"
        "</tr></thead>"
    )

    if changed:
        parts.append(f'<h3 class="sub">Changed ({len(changed)})</h3>')
        parts.append(
            f'<table class="delta">{header}<tbody>{table_rows(changed)}</tbody></table>'
        )
    if other:
        parts.append(f'<h3 class="sub">Other issues ({len(other)})</h3>')
        parts.append(
            f'<table class="delta">{header}<tbody>{table_rows(other)}</tbody></table>'
        )

    parts.append(f'<p class="total">Total flagged: <strong>{len(deltas)}</strong></p>')
    return "\n".join(parts)


def export_html_report(
    output_path: Path,
    analysis1: list[KeyValueDelta],
    analysis2: list[KeyValueDelta],
    v5_path: Path,
    v6_path: Path,
    v5_rows: int,
    v6_rows: int,
) -> None:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(analysis1) + len(analysis2)
    status = "clean" if total == 0 else "issues"

    a1_body = _render_delta_table(
        analysis1, "Request Code (Col D)", "Component (Col W)"
    )
    a2_body = _render_delta_table(
        analysis2, "Component (Col W)", "Profile (Col AI)"
    )

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Network Inventory Delta Report — V5 vs V6</title>
  <style>
    :root {{
      --bg: #0f1419;
      --surface: #1a2332;
      --border: #2d3a4f;
      --text: #e7ecf3;
      --muted: #8b9cb3;
      --accent: #3b82f6;
      --ok: #22c55e;
      --warn: #f59e0b;
      --danger: #ef4444;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }}
    h1 {{ font-size: 1.5rem; font-weight: 600; margin: 0 0 0.25rem; }}
    .meta {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 1.5rem; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1rem;
    }}
    .card .label {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }}
    .card .value {{ font-size: 1.75rem; font-weight: 700; margin-top: 0.25rem; }}
    .card.ok .value {{ color: var(--ok); }}
    .card.bad .value {{ color: var(--danger); }}
    section {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1.25rem 1.5rem 1.5rem;
      margin-bottom: 1.5rem;
    }}
    section.primary {{ border-color: var(--accent); box-shadow: 0 0 0 1px rgba(59,130,246,0.15); }}
    h2 {{ font-size: 1.1rem; margin: 0 0 0.35rem; }}
    h2 .num {{ color: var(--accent); margin-right: 0.35rem; }}
    .desc {{ color: var(--muted); font-size: 0.85rem; margin: 0 0 1rem; }}
    h3.sub {{ font-size: 0.95rem; margin: 1.25rem 0 0.5rem; color: var(--muted); }}
    table.delta {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.875rem;
    }}
    table.delta th, table.delta td {{
      text-align: left;
      padding: 0.6rem 0.75rem;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }}
    table.delta th {{
      color: var(--muted);
      font-weight: 600;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    tr.issue-changed td:nth-child(3),
    tr.issue-changed td:nth-child(4) {{ background: rgba(239,68,68,0.08); }}
    .badge {{
      display: inline-block;
      font-size: 0.7rem;
      padding: 0.15rem 0.45rem;
      border-radius: 4px;
      max-width: 220px;
      line-height: 1.3;
    }}
    .issue-changed .badge {{ background: rgba(239,68,68,0.2); color: #fca5a5; }}
    .issue-v5 .badge {{ background: rgba(245,158,11,0.2); color: #fcd34d; }}
    .issue-v6 .badge {{ background: rgba(59,130,246,0.2); color: #93c5fd; }}
    .issue-ambiguous .badge {{ background: rgba(168,85,247,0.2); color: #d8b4fe; }}
    p.ok {{ color: var(--ok); margin: 0; }}
    p.total {{ margin: 1rem 0 0; font-size: 0.9rem; color: var(--muted); }}
    .banner {{
      padding: 0.75rem 1rem;
      border-radius: 8px;
      margin-bottom: 1.5rem;
      font-weight: 500;
    }}
    .banner.clean {{ background: rgba(34,197,94,0.12); color: var(--ok); border: 1px solid rgba(34,197,94,0.35); }}
    .banner.issues {{ background: rgba(239,68,68,0.1); color: #fca5a5; border: 1px solid rgba(239,68,68,0.35); }}
    code {{ font-size: 0.8rem; word-break: break-all; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Network Inventory Comparison</h1>
    <p class="meta">V5 vs V6 · Generated {_esc(generated)}</p>

    <div class="banner {status}">
      {"No configuration deltas detected." if total == 0 else f"{total} delta(s) require review."}
    </div>

    <div class="cards">
      <div class="card {'ok' if len(analysis1) == 0 else 'bad'}">
        <div class="label">Analysis 1</div>
        <div class="value">{len(analysis1)}</div>
      </div>
      <div class="card {'ok' if len(analysis2) == 0 else 'bad'}">
        <div class="label">Analysis 2</div>
        <div class="value">{len(analysis2)}</div>
      </div>
      <div class="card">
        <div class="label">V5 rows</div>
        <div class="value">{v5_rows}</div>
      </div>
      <div class="card">
        <div class="label">V6 rows</div>
        <div class="value">{v6_rows}</div>
      </div>
    </div>

    <p class="meta">V5: <code>{_esc(str(v5_path.resolve()))}</code><br>
    V6: <code>{_esc(str(v6_path.resolve()))}</code></p>

    <section class="primary" id="analysis-1">
      <h2><span class="num">1</span>Request Code → Component (D → W)</h2>
      <p class="desc">Same request code must map to the same component in both versions.</p>
      {a1_body}
    </section>

    <section id="analysis-2">
      <h2><span class="num">2</span>Component → Profile (W → AI)</h2>
      <p class="desc">Same network component must map to the same profile identifier in both versions.</p>
      {a2_body}
    </section>
  </div>
</body>
</html>
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc, encoding="utf-8")


def print_section(
    title: str,
    deltas: list[KeyValueDelta],
    key_label: str,
    value_label: str,
) -> None:
    width = 72
    print()
    print("=" * width)
    print(title.center(width))
    print("=" * width)

    if not deltas:
        print("\n  No mismatches found.\n")
        return

    changed = [d for d in deltas if d.issue == "changed"]
    other = [d for d in deltas if d.issue != "changed"]

    if changed:
        print(f"\n  CHANGED ({len(changed)}):\n")
        for d in changed:
            print(f"    {key_label}: {d.key}")
            print(f"      V5 {value_label}: {d.v5_display}")
            print(f"      V6 {value_label}: {d.v6_display}")
            print()

    if other:
        print(f"  OTHER ISSUES ({len(other)}):\n")
        for d in other:
            print(f"    [{ISSUE_LABELS.get(d.issue, d.issue)}]")
            print(f"      {key_label}: {d.key}")
            print(f"      V5 {value_label}: {d.v5_display}")
            print(f"      V6 {value_label}: {d.v6_display}")
            print()

    print(f"  Total flagged: {len(deltas)}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare network inventory spreadsheets V5 vs V6 using "
            "key-based logical analysis (columns D/W and W/AI)."
        )
    )
    parser.add_argument("v5", type=Path, help="Path to V5 inventory (.xlsx/.xls)")
    parser.add_argument("v6", type=Path, help="Path to V6 inventory (.xlsx/.xls)")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="HTML report path (default: inventory_delta_report_<timestamp>.html)",
    )
    parser.add_argument(
        "--sheet",
        default=None,
        help="Sheet name or 0-based index (default: first sheet)",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="Print terminal report only; do not write HTML file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    sheet: str | int | None
    if args.sheet is not None:
        try:
            sheet = int(args.sheet)
        except ValueError:
            sheet = args.sheet

    try:
        v5_df = load_inventory(args.v5, sheet)
        v6_df = load_inventory(args.v6, sheet)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error loading files: {exc}", file=sys.stderr)
        return 1

    # Both analyses run independently on the full datasets
    analysis1 = run_analysis_request_to_component(v5_df, v6_df)
    analysis2 = run_analysis_component_to_profile(v5_df, v6_df)

    print("\n" + "#" * 72)
    print("NETWORK INVENTORY COMPARISON — V5 vs V6".center(72))
    print("#" * 72)
    print(f"\n  V5: {args.v5.resolve()}")
    print(f"  V6: {args.v6.resolve()}")
    print(f"  Rows: V5={len(v5_df)}, V6={len(v6_df)}")

    # Analysis 1 is listed first in the report (per requirements)
    print_section(
        "ANALYSIS 1: Request Code (D) -> Component (W)",
        analysis1,
        "Request Code",
        "Component",
    )
    print_section(
        "ANALYSIS 2: Component (W) -> Profile (AI)",
        analysis2,
        "Component",
        "Profile",
    )

    if not args.no_export:
        out = args.output or Path(
            f"inventory_delta_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        )
        export_html_report(
            out, analysis1, analysis2, args.v5, args.v6, len(v5_df), len(v6_df)
        )
        print(f"\n  HTML report written to: {out.resolve()}\n")

    total = len(analysis1) + len(analysis2)
    return 0 if total == 0 else 2  # exit 2 = mismatches found (useful for CI)


if __name__ == "__main__":
    raise SystemExit(main())
