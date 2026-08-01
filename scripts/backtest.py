#!/usr/bin/env python3
"""スコア設計の妥当性検証バックテスト(GitHub Actions上で手動実行)。

過去約10年の日足に対して本番と同じ閾値でスコアを毎日計算し、
各資産の下落局面でスコアがきちんと上昇するかを確認する。

制約: Fear&Greed・プットコールレシオ・騰落レシオの長期履歴は無料では
取得できないため、検証は「恐怖指数20点+価格指標50点=70点満点」で行う
(金は本番同様に価格指標のみ100点満点)。センチメント30点は本番では
上乗せ方向にしか働かないため、この部分点で構造の検証は成立する。
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_data import (  # noqa: E402
    VOL_NKVI, VOL_VIX, band, fetch_nikkei_vi, fetch_yahoo, to_yen_series,
)


# ---------- 系列計算(本番 build_asset と同じ定義をローリングで計算) ----------

def rsi_series(values, period=14):
    out = [None] * len(values)
    if len(values) < period + 1:
        return out
    gains, losses = [], []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    def to_rsi(g, l):
        if l == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + g / l)
    out[period] = to_rsi(avg_gain, avg_loss)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = to_rsi(avg_gain, avg_loss)
    return out


def ma_series(values, window):
    out = [None] * len(values)
    if len(values) < window:
        return out
    s = sum(values[:window])
    out[window - 1] = s / window
    for i in range(window, len(values)):
        s += values[i] - values[i - window]
        out[i] = s / window
    return out


def dd_series(values, window=252):
    """52週高値からの下落率(%)のローリング系列。"""
    out = []
    for i in range(len(values)):
        lo = max(0, i - window + 1)
        high = max(values[lo:i + 1])
        out.append((values[i] / high - 1.0) * 100.0)
    return out


# ---------- スコア計算(fetch_data.py の本番閾値と同一) ----------

def price_points_stock(dd, rsi, dev):
    depth = -dd if dd is not None else None
    p1, _ = band(depth, [(5, 0), (10, 7), (15, 12), (20, 16), (math.inf, 20)])
    if rsi is None:
        p2 = 0
    elif rsi >= 45:
        p2 = 0
    elif rsi >= 35:
        p2 = 5
    elif rsi >= 30:
        p2 = 10
    else:
        p2 = 15
    if dev is None or dev >= 0:
        p3 = 0
    elif dev >= -5:
        p3 = 5
    elif dev >= -10:
        p3 = 10
    else:
        p3 = 15
    return p1 + p2 + p3  # 最大50


def price_points_gold(dd, rsi, dev):
    depth = -dd if dd is not None else None
    p1, _ = band(depth, [(5, 0), (10, 14), (15, 24), (20, 32), (math.inf, 40)])
    if rsi is None:
        p2 = 0
    elif rsi >= 45:
        p2 = 0
    elif rsi >= 35:
        p2 = 10
    elif rsi >= 30:
        p2 = 20
    else:
        p2 = 30
    if dev is None or dev >= 0:
        p3 = 0
    elif dev >= -5:
        p3 = 10
    elif dev >= -10:
        p3 = 20
    else:
        p3 = 30
    return p1 + p2 + p3  # 最大100


def pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    vy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return cov / (vx * vy) if vx and vy else float("nan")


# ---------- バックテスト本体 ----------

def find_episodes(dates, dds, threshold=-12.0, merge_gap=60):
    """dd が threshold を下回った日を、gap営業日以内なら同一局面としてまとめる。"""
    idxs = [i for i, d in enumerate(dds) if d is not None and d <= threshold]
    episodes = []
    for i in idxs:
        if episodes and i - episodes[-1][-1] <= merge_gap:
            episodes[-1].append(i)
        else:
            episodes.append([i])
    return episodes


def run_asset(title, dates, closes, scores, dds, max_score):
    print(f"\n=== {title}(満点{max_score}点)===")
    start = 252  # 52週窓が揃ってから
    d_, s_, dd_ = dates[start:], scores[start:], dds[start:]

    valid = [(s, dd) for s, dd in zip(s_, dd_) if s is not None]
    med = sorted(s for s, _ in valid)[len(valid) // 2]
    corr = pearson([s for s, _ in valid], [dd for _, dd in valid])
    print(f"対象期間: {d_[0]} 〜 {d_[-1]} ({len(d_)}営業日)")
    print(f"スコア中央値: {med}点 / スコアとドローダウンの相関: {corr:+.2f} (負=下落ほど高スコア)")

    episodes = find_episodes(d_, dd_)
    if not episodes:
        print("  -12%超の下落局面なし")
        return
    print(f"下落局面(52週高値から-12%超): {len(episodes)}回")
    for ep in episodes:
        trough = min(ep, key=lambda i: dd_[i])
        peak_score_i = max(ep, key=lambda i: s_[i] or 0)
        first, last = ep[0], ep[-1]
        print(
            f"  {d_[first]}〜{d_[last]} | 底: {d_[trough]} ({dd_[trough]:+.1f}%) "
            f"底日のスコア: {s_[trough]}点 | 局面中の最大スコア: {s_[peak_score_i]}点 ({d_[peak_score_i]})"
        )

    # 平常時(dd>-5%)との比較
    calm = [s for s, dd in valid if dd > -5]
    deep = [s for s, dd in valid if dd <= -15]
    if calm and deep:
        print(
            f"平常時(DD>-5%)の平均スコア: {sum(calm)/len(calm):.1f}点 / "
            f"深い下落時(DD≤-15%)の平均スコア: {sum(deep)/len(deep):.1f}点"
        )


def main():
    # 価格データ(10年)
    n225_d, n225_v = fetch_yahoo("^N225", range_="10y")
    acwi_d, acwi_v = fetch_yahoo("ACWI", range_="10y")
    gold_d, gold_v = fetch_yahoo("GLD", range_="10y")
    vix_d, vix_v = fetch_yahoo("^VIX", range_="10y")
    vix_map = dict(zip(vix_d, vix_v))

    # 日経VI(公式CSVで取れる範囲。無い日はVIXで代替=本番と同じフォールバック)
    try:
        nkvi_d, nkvi_v = fetch_nikkei_vi()
        nkvi_map = dict(zip(nkvi_d, nkvi_v))
        print(f"日経VI履歴: {len(nkvi_d)}日分 ({nkvi_d[0]}〜{nkvi_d[-1]})")
    except Exception as e:  # noqa: BLE001
        print(f"日経VI取得失敗({e})→ 全期間VIXで代替")
        nkvi_map = {}

    def vol_points(date, prefer_nkvi):
        if prefer_nkvi and date in nkvi_map:
            pts, _ = band(nkvi_map[date], VOL_NKVI["bands"])
            return pts
        v = vix_map.get(date)
        if v is None:
            return 0
        pts, _ = band(v, VOL_VIX["bands"])
        return pts

    def build_scores(dates, closes, prefer_nkvi=False, gold=False):
        rsis = rsi_series(closes)
        mas = ma_series(closes, 200)
        dds = dd_series(closes)
        scores = []
        for i in range(len(closes)):
            rsi, ma = rsis[i], mas[i]
            dev = (closes[i] / ma - 1.0) * 100.0 if ma else None
            if gold:
                s = price_points_gold(dds[i], rsi, dev)
            else:
                s = price_points_stock(dds[i], rsi, dev) + vol_points(dates[i], prefer_nkvi)
            scores.append(s)
        return scores, dds

    s, dd = build_scores(n225_d, n225_v, prefer_nkvi=True)
    run_asset("日経平均", n225_d, n225_v, s, dd, 70)

    s, dd = build_scores(acwi_d, acwi_v)
    run_asset("オルカン(ACWI・ドル建て/参考)", acwi_d, acwi_v, s, dd, 70)

    # 本番仕様: 円建て換算値で価格指標を計算
    fx_d, fx_v = fetch_yahoo("JPY=X", range_="10y")
    yen_d, yen_v = to_yen_series(acwi_d, acwi_v, fx_d, fx_v)
    s, dd = build_scores(yen_d, yen_v)
    run_asset("オルカン(ACWI・円建て=本番仕様)", yen_d, yen_v, s, dd, 70)

    s, dd = build_scores(gold_d, gold_v, gold=True)
    run_asset("金(GLD)", gold_d, gold_v, s, dd, 100)

    print("\n※ 検証はセンチメント指標(騰落レシオ/F&G/プットコール、30点分)を除いた部分点。")
    print("  本番スコアはこれに上乗せされるため、下落局面ではさらに高く出る方向。")


if __name__ == "__main__":
    main()
