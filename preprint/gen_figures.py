"""Generate proto figures for the preprint from observatory data."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path
from observatory.store import Store

OUT = Path(__file__).parent / "figs"
OUT.mkdir(exist_ok=True)

# Tufte-inspired style: minimal ink, no chartjunk
plt.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.spines.left": False,
    "axes.grid": True,
    "axes.grid.axis": "x",
    "grid.color": "#e0e0e0",
    "grid.linewidth": 0.5,
    "figure.dpi": 150,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
})

TRANSLATIONS = {
    "Politik": "Politics",
    "Menschenrechte": "Human Rights",
    "Tiere": "Animals",
    "Umwelt": "Environment",
    "Wirtschaftliche Gerechtigkeit": "Economic Justice",
    "Gesundheit": "Health",
    "Tierrechte": "Animal Rights",
    "Strafjustiz": "Criminal Justice",
    "Familie": "Family",
    "Frauenrechte": "Women's Rights",
    "Staatsregierung": "Government",
    "Tierwohl": "Animal Welfare",
    "Zugang zu Pflege": "Access to Care",
    "Bildung": "Education",
    "Tierschutz": "Animal Protection",
    "Einwanderung": "Immigration",
    "Verbraucherschutz": "Consumer Rights",
    "Coronavirus": "COVID-19",
    "Immigranten": "Immigration",
}


# ---------------------------------------------------------------------------
# Figure 1: Top topics by cumulative signatures
# ---------------------------------------------------------------------------
store = Store("../data/observatory.db")
rows = store._conn.execute(
    "SELECT name, signature_count FROM topics "
    "WHERE signature_count IS NOT NULL "
    "ORDER BY signature_count DESC LIMIT 15"
).fetchall()
store.close()

names_de = [r[0] for r in rows]
names_en = [TRANSLATIONS.get(r[0], r[0]) for r in rows]
counts = [r[1] / 1e6 for r in rows]  # millions

fig, ax = plt.subplots(figsize=(5.5, 4.2))
colors = ["#2c5f8a" if i < 5 else "#6b9bbf" for i in range(len(counts))]
bars = ax.barh(range(len(names_en)), counts, color=colors, height=0.65, zorder=3)

ax.set_yticks(range(len(names_en)))
ax.set_yticklabels(names_en, fontsize=8.5)
ax.invert_yaxis()
ax.set_xlabel("Cumulative signatures (millions)", labelpad=6)
ax.set_title("Top 15 topic categories by total signatures", fontsize=10, pad=8)

# Value labels
for bar, val in zip(bars, counts):
    ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
            f"{val:.1f}M", va="center", fontsize=7.5, color="#444")

ax.tick_params(left=False)
ax.set_xlim(0, max(counts) * 1.18)

note = ("Source: Change.org topic directory, scraped June 2026.\n"
        "Platform-displayed cumulative signature totals.")
fig.text(0.02, -0.04, note, fontsize=6.5, color="#666", style="italic")

plt.tight_layout()
fig.savefig(OUT / "fig1_top_topics.pdf")
fig.savefig(OUT / "fig1_top_topics.png")
print("Figure 1 saved.")


# ---------------------------------------------------------------------------
# Figure 2: Sitemap temporal distribution (petition volume per month)
# ---------------------------------------------------------------------------
import requests, re, time

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}

print("Fetching sitemap index for monthly counts ...")
r = requests.get("https://www.change.org/sitemap.xml", headers=HEADERS, timeout=20)
sitemap_urls = re.findall(r"<loc>(https://www.change.org/sitemap-(\d{4}_\d{2})_\d+\.xml)</loc>", r.text)

months, counts_m = [], []
for url, ym in sitemap_urls:
    time.sleep(0.4)
    try:
        rs = requests.get(url, headers=HEADERS, timeout=30)
        n = len(re.findall(r"<loc>https://www.change.org/p/", rs.text))
        year, month = ym.split("_")
        months.append(f"{year}-{month}")
        counts_m.append(n)
        print(f"  {ym}: {n} petitions")
    except Exception as e:
        print(f"  {ym}: error {e}")

if months:
    fig2, ax2 = plt.subplots(figsize=(6, 3))
    x = np.arange(len(months))
    ax2.bar(x, counts_m, color="#2c5f8a", width=0.75, zorder=3)
    step = max(1, len(months) // 12)
    ax2.set_xticks(x[::step])
    ax2.set_xticklabels(months[::step], rotation=45, ha="right", fontsize=7)
    ax2.set_ylabel("Petitions in sitemap")
    ax2.set_title("Monthly petition volume in Change.org sitemaps", fontsize=10, pad=8)
    ax2.tick_params(bottom=False)

    note2 = "Source: Change.org XML sitemaps, retrieved June 2026."
    fig2.text(0.02, -0.12, note2, fontsize=6.5, color="#666", style="italic")
    plt.tight_layout()
    fig2.savefig(OUT / "fig2_monthly_volume.pdf")
    fig2.savefig(OUT / "fig2_monthly_volume.png")
    print("Figure 2 saved.")


# ---------------------------------------------------------------------------
# Figure 3: Data collection architecture (conceptual diagram via matplotlib)
# ---------------------------------------------------------------------------
fig3, ax3 = plt.subplots(figsize=(5.5, 3.2))
ax3.set_xlim(0, 10)
ax3.set_ylim(0, 6)
ax3.axis("off")

def box(ax, x, y, w, h, label, sublabel="", color="#2c5f8a", tc="white"):
    rect = mpatches.FancyBboxPatch((x - w/2, y - h/2), w, h,
                                   boxstyle="round,pad=0.1",
                                   facecolor=color, edgecolor="#aaa", linewidth=0.7)
    ax.add_patch(rect)
    ax.text(x, y + (0.18 if sublabel else 0), label, ha="center", va="center",
            color=tc, fontsize=8, fontweight="bold")
    if sublabel:
        ax.text(x, y - 0.28, sublabel, ha="center", va="center",
                color=tc, fontsize=6.5, style="italic")

def arrow(ax, x1, y1, x2, y2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color="#555", lw=0.9))

# Boxes
box(ax3, 5, 5.1, 4.5, 0.75, "Change.org", "sitemap index + petition pages", "#1a3a5c")
box(ax3, 2, 3.5, 2.8, 0.75, "Sitemap scraper", "topics + petition URLs")
box(ax3, 7.3, 3.5, 2.8, 0.75, "Petition scraper", "JSON-LD + changeTargetingData")
box(ax3, 5, 1.9, 3.2, 0.75, "SQLite store", "topics / petitions / snapshots", "#3a6b3a")
box(ax3, 2, 0.5, 2.4, 0.65, "CSV / JSON export", "", "#5a7a5a", "white")
box(ax3, 7.3, 0.5, 2.4, 0.65, "Analysis / vis.", "", "#5a7a5a", "white")

# Arrows
arrow(ax3, 3, 4.73, 2, 3.88)
arrow(ax3, 7, 4.73, 7.3, 3.88)
arrow(ax3, 2, 3.12, 3.4, 2.27)
arrow(ax3, 7.3, 3.12, 6.6, 2.27)
arrow(ax3, 3.9, 1.52, 2.8, 0.83)
arrow(ax3, 6.1, 1.52, 7.1, 0.83)

ax3.set_title("Observatory data collection architecture", fontsize=10, pad=4)
plt.tight_layout()
fig3.savefig(OUT / "fig3_architecture.pdf")
fig3.savefig(OUT / "fig3_architecture.png")
print("Figure 3 saved.")
print("All figures written to preprint/figs/")
