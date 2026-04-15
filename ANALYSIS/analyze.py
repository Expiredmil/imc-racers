import csv
import os
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

# ── paths ────────────────────────────────────────────────────────────────────
BASE   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA   = os.path.join(BASE, "DATA_ROUND1")
OUT    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "round1")
os.makedirs(OUT, exist_ok=True)

DAYS   = ["-2", "-1", "0"]
COLORS = {"-2": "#4C72B0", "-1": "#DD8452", "0": "#55A868"}
PRODUCTS = ["INTARIAN_PEPPER_ROOT", "ASH_COATED_OSMIUM"]

# ── loaders ──────────────────────────────────────────────────────────────────
def load_prices(day: str) -> dict[str, list]:
    path = os.path.join(DATA, f"prices_round_1_day_{day}.csv")
    data: dict[str, list] = defaultdict(list)
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            p = row["product"]
            mid = float(row["mid_price"])
            bid1 = float(row["bid_price_1"]) if row["bid_price_1"] else None
            ask1 = float(row["ask_price_1"]) if row["ask_price_1"] else None
            ts   = int(row["timestamp"])
            data[p].append({"ts": ts, "mid": mid, "bid1": bid1, "ask1": ask1})
    return data

def load_trades(day: str) -> dict[str, list]:
    path = os.path.join(DATA, f"trades_round_1_day_{day}.csv")
    data: dict[str, list] = defaultdict(list)
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            sym   = row["symbol"]
            price = float(row["price"])
            qty   = int(row["quantity"])
            ts    = int(row["timestamp"])
            data[sym].append({"ts": ts, "price": price, "qty": qty})
    return data

all_prices = {d: load_prices(d) for d in DAYS}
all_trades = {d: load_trades(d) for d in DAYS}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PLOT 1 — Mid-price over time, both products, all 3 days
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=False)
fig.suptitle("Mid-Price Over Time — All Days", fontsize=14, fontweight="bold")

for ax, product in zip(axes, PRODUCTS):
    for day in DAYS:
        rows = [r for r in all_prices[day][product] if r["mid"] > 0]
        ts   = [r["ts"] for r in rows]
        mid  = [r["mid"] for r in rows]
        ax.plot(ts, mid, color=COLORS[day], label=f"Day {day}", linewidth=0.8, alpha=0.9)

    ax.set_title(product, fontsize=11)
    ax.set_xlabel("Timestamp")
    ax.set_ylabel("Mid Price")
    ax.legend()
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUT, "01_midprice_over_time.png"), dpi=150)
plt.close()
print("Saved: 01_midprice_over_time.png")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PLOT 2 — All 3 days concatenated as one continuous price series
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
fig, axes = plt.subplots(2, 1, figsize=(14, 9))
fig.suptitle("Mid-Price — Concatenated Across Days", fontsize=14, fontweight="bold")

for ax, product in zip(axes, PRODUCTS):
    combined_ts, combined_mid = [], []
    offset = 0
    for day in DAYS:
        rows = [r for r in all_prices[day][product] if r["mid"] > 0]
        ts   = [r["ts"] + offset for r in rows]
        mid  = [r["mid"] for r in rows]
        combined_ts.extend(ts)
        combined_mid.extend(mid)
        if ts:
            offset = ts[-1] + 100

    ax.plot(combined_ts, combined_mid, linewidth=0.7, color="#2c7bb6")

    # Day boundary lines
    boundary = 0
    for i, day in enumerate(DAYS):
        rows = [r for r in all_prices[day][product] if r["mid"] > 0]
        if rows:
            day_len = rows[-1]["ts"] - rows[0]["ts"]
            if i > 0:
                ax.axvline(x=boundary, color="red", linestyle="--", alpha=0.6, linewidth=1)
                ax.text(boundary + 5000, ax.get_ylim()[0] if ax.get_ylim()[0] != 0 else combined_mid[0],
                        f"Day {day}", color="red", fontsize=8, va="bottom")
            boundary += day_len + 100

    ax.set_title(product, fontsize=11)
    ax.set_xlabel("Cumulative Timestamp")
    ax.set_ylabel("Mid Price")
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUT, "02_midprice_concatenated.png"), dpi=150)
plt.close()
print("Saved: 02_midprice_concatenated.png")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PLOT 3 — Bid-Ask Spread over time
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
fig, axes = plt.subplots(2, 3, figsize=(16, 8), sharey="row")
fig.suptitle("Bid-Ask Spread Over Time", fontsize=14, fontweight="bold")

for row_i, product in enumerate(PRODUCTS):
    for col_i, day in enumerate(DAYS):
        ax = axes[row_i][col_i]
        rows = [r for r in all_prices[day][product] if r["bid1"] and r["ask1"]]
        ts     = [r["ts"] for r in rows]
        spread = [r["ask1"] - r["bid1"] for r in rows]

        ax.plot(ts, spread, color=COLORS[day], linewidth=0.5, alpha=0.7)
        ax.axhline(y=np.mean(spread), color="black", linestyle="--", linewidth=1,
                   label=f"Mean={np.mean(spread):.1f}")
        ax.set_title(f"{product.split('_')[0]}... Day {day}", fontsize=9)
        ax.set_xlabel("Timestamp", fontsize=8)
        ax.set_ylabel("Spread" if col_i == 0 else "", fontsize=8)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUT, "03_spread_over_time.png"), dpi=150)
plt.close()
print("Saved: 03_spread_over_time.png")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PLOT 4 — Tick-to-tick change distribution (histogram)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle("Tick-to-Tick Mid-Price Change Distribution (all days combined)", fontsize=13, fontweight="bold")

for ax, product in zip(axes, PRODUCTS):
    all_changes = []
    for day in DAYS:
        prices = [r["mid"] for r in all_prices[day][product] if r["mid"] > 0]
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        all_changes.extend(changes)

    # Clip outliers for readability
    clipped = [c for c in all_changes if -30 <= c <= 30]
    bins = np.arange(-30, 31, 0.5)
    ax.hist(clipped, bins=bins, color="#4C72B0", edgecolor="white", linewidth=0.3, alpha=0.85)
    ax.axvline(x=0, color="red", linestyle="--", linewidth=1.2, label="Zero")
    mean_c = np.mean(all_changes)
    ax.axvline(x=mean_c, color="orange", linestyle="-", linewidth=1.5, label=f"Mean={mean_c:.3f}")
    ax.set_title(product, fontsize=10)
    ax.set_xlabel("Price Change per Tick")
    ax.set_ylabel("Frequency")
    ax.legend()
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUT, "04_tick_change_distribution.png"), dpi=150)
plt.close()
print("Saved: 04_tick_change_distribution.png")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PLOT 5 — INTARIAN_PEPPER_ROOT: price vs. linear fair value
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharey=False)
fig.suptitle("INTARIAN_PEPPER_ROOT: Actual Price vs. Linear Fair Value", fontsize=13, fontweight="bold")

for ax, day in zip(axes, DAYS):
    rows   = [r for r in all_prices[day]["INTARIAN_PEPPER_ROOT"] if r["mid"] > 0]
    ts     = np.array([r["ts"] for r in rows])
    mid    = np.array([r["mid"] for r in rows])

    # fit linear trend
    coeffs = np.polyfit(ts, mid, 1)
    fair   = np.polyval(coeffs, ts)
    deviation = mid - fair

    ax2 = ax.twinx()
    ax.plot(ts, mid,  color="#2c7bb6", linewidth=0.8, label="Mid Price", zorder=2)
    ax.plot(ts, fair, color="red",     linewidth=1.5, linestyle="--", label=f"Fair Value (slope={coeffs[0]*100:.4f}/100ts)", zorder=3)
    ax2.plot(ts, deviation, color="green", linewidth=0.5, alpha=0.6, label="Deviation")
    ax2.axhline(0, color="green", linestyle=":", linewidth=0.8)

    ax.set_title(f"Day {day}", fontsize=10)
    ax.set_xlabel("Timestamp")
    ax.set_ylabel("Price", color="#2c7bb6")
    ax2.set_ylabel("Deviation from Fair", color="green")
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="upper left")
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUT, "05_pepper_vs_fairvalue.png"), dpi=150)
plt.close()
print("Saved: 05_pepper_vs_fairvalue.png")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PLOT 6 — ASH_COATED_OSMIUM: mean-reversion profile
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
fig, axes = plt.subplots(2, 1, figsize=(14, 9))
fig.suptitle("ASH_COATED_OSMIUM — Mean Reversion Analysis", fontsize=13, fontweight="bold")

# Top: price deviation from 10000 across all days concatenated
ax = axes[0]
offset = 0
for day in DAYS:
    rows   = [r for r in all_prices[day]["ASH_COATED_OSMIUM"] if r["mid"] > 0]
    ts     = [r["ts"] + offset for r in rows]
    dev    = [r["mid"] - 10000 for r in rows]
    ax.plot(ts, dev, color=COLORS[day], linewidth=0.7, alpha=0.9, label=f"Day {day}")
    if ts:
        offset = ts[-1] + 100
ax.axhline(0, color="red", linestyle="--", linewidth=1.2, label="Mean=10000")
ax.fill_between(range(0, offset, 1000), -5, 5, alpha=0.07, color="red")
ax.set_title("Price Deviation from 10000 (concatenated)", fontsize=10)
ax.set_xlabel("Cumulative Timestamp")
ax.set_ylabel("Deviation from 10000")
ax.legend()
ax.grid(True, alpha=0.3)

# Bottom: rolling mean (window=200) to show mean-reversion
ax2 = axes[1]
all_mid = []
for day in DAYS:
    rows = [r for r in all_prices[day]["ASH_COATED_OSMIUM"] if r["mid"] > 0]
    all_mid.extend([r["mid"] for r in rows])

window = 200
rolling_mean = [np.mean(all_mid[max(0,i-window):i+1]) for i in range(len(all_mid))]
ax2.plot(all_mid, color="#4C72B0", linewidth=0.5, alpha=0.6, label="Mid Price")
ax2.plot(rolling_mean, color="orange", linewidth=1.5, label=f"Rolling Mean (w={window})")
ax2.axhline(10000, color="red", linestyle="--", linewidth=1.2, label="10000")
ax2.set_title("Mid Price with Rolling Mean", fontsize=10)
ax2.set_xlabel("Tick Index")
ax2.set_ylabel("Price")
ax2.legend()
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUT, "06_osmium_meanreversion.png"), dpi=150)
plt.close()
print("Saved: 06_osmium_meanreversion.png")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PLOT 7 — Market trade activity (timing and price)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
fig, axes = plt.subplots(2, 3, figsize=(16, 9))
fig.suptitle("Market Trade Activity (XIRECS) — Price & Size", fontsize=13, fontweight="bold")

for row_i, product in enumerate(PRODUCTS):
    for col_i, day in enumerate(DAYS):
        ax = axes[row_i][col_i]
        trades = all_trades[day].get(product, [])

        if trades:
            ts     = [t["ts"] for t in trades]
            prices = [t["price"] for t in trades]
            sizes  = [t["qty"] * 8 for t in trades]  # scale for visibility

            # background: mid price
            rows = [r for r in all_prices[day][product] if r["mid"] > 0]
            mid_ts  = [r["ts"] for r in rows]
            mid_val = [r["mid"] for r in rows]
            ax.plot(mid_ts, mid_val, color="lightgray", linewidth=0.6, zorder=1, label="Mid")
            ax.scatter(ts, prices, s=sizes, color=COLORS[day], alpha=0.7, zorder=2,
                       edgecolors="black", linewidths=0.4, label=f"{len(trades)} trades")

        ax.set_title(f"{product.split('_')[0]}... Day {day}", fontsize=9)
        ax.set_xlabel("Timestamp", fontsize=8)
        ax.set_ylabel("Price" if col_i == 0 else "", fontsize=8)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUT, "07_trade_activity.png"), dpi=150)
plt.close()
print("Saved: 07_trade_activity.png")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PLOT 8 — Summary dashboard
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
fig = plt.figure(figsize=(16, 12))
fig.suptitle("Round 1 — Market Overview Dashboard", fontsize=15, fontweight="bold", y=0.98)
gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.3)

# (0,0) PEPPER price all days
ax1 = fig.add_subplot(gs[0, 0])
for day in DAYS:
    rows = [r for r in all_prices[day]["INTARIAN_PEPPER_ROOT"] if r["mid"] > 0]
    ts   = [r["ts"] for r in rows]
    mid  = [r["mid"] for r in rows]
    ax1.plot(ts, mid, color=COLORS[day], linewidth=0.7, label=f"Day {day}")
ax1.set_title("PEPPER ROOT — Mid Price", fontsize=10)
ax1.legend(fontsize=8); ax1.grid(True, alpha=0.3)

# (0,1) OSMIUM price all days
ax2 = fig.add_subplot(gs[0, 1])
for day in DAYS:
    rows = [r for r in all_prices[day]["ASH_COATED_OSMIUM"] if r["mid"] > 0]
    ts   = [r["ts"] for r in rows]
    mid  = [r["mid"] for r in rows]
    ax2.plot(ts, mid, color=COLORS[day], linewidth=0.7, label=f"Day {day}")
ax2.axhline(10000, color="red", linestyle="--", linewidth=1, alpha=0.8)
ax2.set_title("ASH OSMIUM — Mid Price (red=10000)", fontsize=10)
ax2.legend(fontsize=8); ax2.grid(True, alpha=0.3)

# (1,0) PEPPER deviation from linear fair value
ax3 = fig.add_subplot(gs[1, 0])
for day in DAYS:
    rows  = [r for r in all_prices[day]["INTARIAN_PEPPER_ROOT"] if r["mid"] > 0]
    ts    = np.array([r["ts"] for r in rows])
    mid   = np.array([r["mid"] for r in rows])
    coeff = np.polyfit(ts, mid, 1)
    dev   = mid - np.polyval(coeff, ts)
    ax3.plot(ts, dev, color=COLORS[day], linewidth=0.7, alpha=0.8, label=f"Day {day}")
ax3.axhline(0, color="black", linestyle="--", linewidth=0.8)
ax3.set_title("PEPPER ROOT — Deviation from Linear Trend", fontsize=10)
ax3.legend(fontsize=8); ax3.grid(True, alpha=0.3)

# (1,1) OSMIUM deviation from 10000
ax4 = fig.add_subplot(gs[1, 1])
for day in DAYS:
    rows = [r for r in all_prices[day]["ASH_COATED_OSMIUM"] if r["mid"] > 0]
    ts   = [r["ts"] for r in rows]
    dev  = [r["mid"] - 10000 for r in rows]
    ax4.plot(ts, dev, color=COLORS[day], linewidth=0.7, alpha=0.8, label=f"Day {day}")
ax4.axhline(0, color="black", linestyle="--", linewidth=0.8)
ax4.set_title("ASH OSMIUM — Deviation from 10000", fontsize=10)
ax4.legend(fontsize=8); ax4.grid(True, alpha=0.3)

# (2,0) Spread comparison bar chart
ax5 = fig.add_subplot(gs[2, 0])
pepper_spreads, osmium_spreads = [], []
for day in DAYS:
    p_rows = [r for r in all_prices[day]["INTARIAN_PEPPER_ROOT"] if r["bid1"] and r["ask1"]]
    o_rows = [r for r in all_prices[day]["ASH_COATED_OSMIUM"]    if r["bid1"] and r["ask1"]]
    pepper_spreads.append(np.mean([r["ask1"]-r["bid1"] for r in p_rows]))
    osmium_spreads.append(np.mean([r["ask1"]-r["bid1"] for r in o_rows]))
x = np.arange(3)
ax5.bar(x - 0.2, pepper_spreads, 0.35, label="PEPPER ROOT", color="#4C72B0")
ax5.bar(x + 0.2, osmium_spreads, 0.35, label="ASH OSMIUM",  color="#DD8452")
ax5.set_xticks(x); ax5.set_xticklabels([f"Day {d}" for d in DAYS])
ax5.set_title("Average Bid-Ask Spread per Day", fontsize=10)
ax5.legend(fontsize=8); ax5.grid(True, alpha=0.3, axis="y")

# (2,1) Trade count bar chart
ax6 = fig.add_subplot(gs[2, 1])
pepper_tc, osmium_tc = [], []
for day in DAYS:
    pepper_tc.append(len(all_trades[day].get("INTARIAN_PEPPER_ROOT", [])))
    osmium_tc.append(len(all_trades[day].get("ASH_COATED_OSMIUM", [])))
ax6.bar(x - 0.2, pepper_tc, 0.35, label="PEPPER ROOT", color="#4C72B0")
ax6.bar(x + 0.2, osmium_tc, 0.35, label="ASH OSMIUM",  color="#DD8452")
ax6.set_xticks(x); ax6.set_xticklabels([f"Day {d}" for d in DAYS])
ax6.set_title("Market Trade Count per Day", fontsize=10)
ax6.legend(fontsize=8); ax6.grid(True, alpha=0.3, axis="y")

plt.savefig(os.path.join(OUT, "08_dashboard.png"), dpi=150)
plt.close()
print("Saved: 08_dashboard.png")

print("\nAll plots saved to ANALYSIS/")
