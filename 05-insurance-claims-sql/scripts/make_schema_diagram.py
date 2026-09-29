"""Render the ER / schema diagram for claims.db -> images/schema_diagram.png (reads the live schema)."""

import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
con = sqlite3.connect(ROOT / "data" / "claims.db")

NAVY, TEAL, INK, MUTED, BG = "#0B1F3A", "#0F9D8F", "#1F2937", "#6B7280", "#FFFFFF"

# table -> (x, y) of the top-left corner, in axis units
LAYOUT = {
    "members": (0.5, 9.3),
    "policies": (0.5, 4.6),
    "claims": (6.2, 9.9),
    "providers": (12.0, 9.3),
    "diagnosis_codes": (12.0, 4.9),
    "procedure_codes": (12.0, 2.55),
    "rejection_reasons": (6.2, 2.4),
}
W, ROW_H, HEAD_H = 4.6, 0.34, 0.5

cols, fks = {}, []
for t in LAYOUT:
    info = con.execute(f"PRAGMA table_info({t})").fetchall()
    cols[t] = [(c[1], c[2], c[5] > 0) for c in info]
    for fk in con.execute(f"PRAGMA foreign_key_list({t})").fetchall():
        fks.append((t, fk[3], fk[2], fk[4]))
fk_cols = {(t, c) for t, c, _, _ in fks}

fig, ax = plt.subplots(figsize=(17, 11))
ax.set_xlim(0, 17)
ax.set_ylim(-1.0, 11)
ax.axis("off")
fig.patch.set_facecolor(BG)

anchors = {}
for t, (x, y) in LAYOUT.items():
    n = len(cols[t])
    h = HEAD_H + n * ROW_H + 0.12
    ax.add_patch(FancyBboxPatch((x, y - h), W, h, boxstyle="round,pad=0,rounding_size=0.12",
                                fc="#F8FAFC", ec="#CBD5E1", lw=1.2, zorder=2))
    ax.add_patch(FancyBboxPatch((x, y - HEAD_H), W, HEAD_H, boxstyle="round,pad=0,rounding_size=0.12",
                                fc=NAVY, ec=NAVY, lw=1.2, zorder=3))
    ax.text(x + 0.18, y - HEAD_H / 2, t, color="white", fontsize=12.5, fontweight="bold", va="center", zorder=4)
    for i, (name, typ, pk) in enumerate(cols[t]):
        cy = y - HEAD_H - (i + 0.5) * ROW_H - 0.06
        tag = "PK" if pk else ("FK" if (t, name) in fk_cols else "")
        if tag:
            ax.text(x + 0.18, cy, tag, color=TEAL if tag == "PK" else "#E0694F", fontsize=8.5,
                    fontweight="bold", va="center", zorder=4)
        ax.text(x + 0.62, cy, name, color=INK, fontsize=10, va="center", zorder=4,
                fontweight="bold" if pk else "normal")
        ax.text(x + W - 0.15, cy, typ.lower(), color=MUTED, fontsize=8.5, va="center", ha="right", zorder=4)
        anchors[(t, name)] = cy

def edge(t, side):
    x, _ = LAYOUT[t]
    return x + (W if side == "right" else 0)

for t, col, ref_t, ref_col in fks:
    y1, y2 = anchors[(t, col)], anchors[(ref_t, ref_col)]
    tx, rx = LAYOUT[t][0], LAYOUT[ref_t][0]
    if rx < tx:
        x1, x2 = edge(t, "left"), edge(ref_t, "right")
    elif rx > tx:
        x1, x2 = edge(t, "right"), edge(ref_t, "left")
    else:  # same column: loop out to the left
        x1, x2 = edge(t, "left"), edge(ref_t, "left")
    if x1 == x2:
        xs = [x1, x1 - 0.35, x1 - 0.35, x2]
        ys = [y1, y1, y2, y2]
    else:
        mid = (x1 + x2) / 2 + (0.25 if ref_t == "procedure_codes" else 0)
        xs, ys = [x1, mid, mid, x2], [y1, y1, y2, y2]
    ax.plot(xs, ys, color=TEAL, lw=1.6, zorder=1, solid_capstyle="round")
    ax.plot([x1], [y1], marker="o", ms=5, color=TEAL, zorder=5)        # many side
    ax.plot([x2], [y2], marker="D", ms=5, color=NAVY, zorder=5)        # one side

counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in LAYOUT}
ax.text(0.5, 10.65, "Health Insurance Claims - Schema (SQLite: data/claims.db)", fontsize=17,
        fontweight="bold", color=NAVY)
ax.text(0.5, -0.35, "   ".join(f"{t}: {n:,}" for t, n in counts.items()), fontsize=9.5, color=MUTED)
ax.text(0.5, -0.75, "o many   ◆ one   PK primary key   FK foreign key", fontsize=9.5, color=MUTED)

out = ROOT / "images" / "schema_diagram.png"
out.parent.mkdir(exist_ok=True)
fig.savefig(out, dpi=140, bbox_inches="tight", facecolor=BG)
print("wrote", out)
