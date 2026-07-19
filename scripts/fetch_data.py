#!/usr/bin/env python3
"""買い増しタイミング判定用の市場データを取得して data/data.json を生成する。

データソース(すべて無料・認証不要):
  - Yahoo Finance chart API: ^VIX, ^N225, ACWI, JPY=X
  - CNN Fear & Greed Index: fear_and_greed + put_call_options コンポーネント

GitHub Actions から毎日実行される想定。個別ソースの取得失敗時は
前回の data.json の該当セクションを引き継ぎ、errors に記録する。

`--sample` を付けるとネットワークを使わず決定論的なダミーデータを生成する
(ローカルでの UI 開発・初回コミット用)。
"""

import argparse
import json
import math
import os
import random
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "data.json")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

YAHOO_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

HISTORY_DAYS = 260  # チャート表示用に保持する日数(約1年の営業日)


def http_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


def fetch_yahoo(symbol, range_="2y", interval="1d"):
    """Yahoo Finance から日足を取得し (dates, closes) を返す。"""
    last_err = None
    for host in YAHOO_HOSTS:
        url = (
            f"https://{host}/v8/finance/chart/{urllib.parse.quote(symbol)}"
            f"?range={range_}&interval={interval}"
        )
        try:
            data = http_get_json(url)
            result = data["chart"]["result"][0]
            ts = result["timestamp"]
            closes = result["indicators"]["quote"][0]["close"]
            dates, values = [], []
            for t, c in zip(ts, closes):
                if c is None:
                    continue
                d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
                # 同一日の重複(当日ザラ場)は最後の値で上書き
                if dates and dates[-1] == d:
                    values[-1] = c
                else:
                    dates.append(d)
                    values.append(c)
            if len(values) < 30:
                raise ValueError(f"{symbol}: too few data points ({len(values)})")
            return dates, values
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"Yahoo fetch failed for {symbol}: {last_err}")


def fetch_cnn():
    return http_get_json(CNN_URL)


# ---------- 指標計算 ----------

def rsi14(values):
    period = 14
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def sma(values, window):
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def sma_series(values, window):
    """values と同じ長さの配列(先頭 window-1 個は None)。"""
    out = [None] * len(values)
    if len(values) < window:
        return out
    s = sum(values[:window])
    out[window - 1] = s / window
    for i in range(window, len(values)):
        s += values[i] - values[i - window]
        out[i] = s / window
    return out


def percentile_rank(values, x):
    if not values:
        return None
    below = sum(1 for v in values if v <= x)
    return 100.0 * below / len(values)


def hist(dates, values, n=HISTORY_DAYS):
    return [
        {"d": d, "v": round(v, 3)}
        for d, v in zip(dates[-n:], values[-n:])
        if v is not None
    ]


def build_asset(name, currency, dates, closes):
    last = closes[-1]
    win52 = closes[-252:] if len(closes) >= 252 else closes
    high52 = max(win52)
    drawdown = (last / high52 - 1.0) * 100.0
    ma200 = sma(closes, 200)
    ma_dev = (last / ma200 - 1.0) * 100.0 if ma200 else None
    ma_hist_full = sma_series(closes, 200)
    return {
        "name": name,
        "currency": currency,
        "price": round(last, 2),
        "date": dates[-1],
        "high_52w": round(high52, 2),
        "drawdown_pct": round(drawdown, 2),
        "rsi14": round(rsi14(closes), 1) if rsi14(closes) is not None else None,
        "ma200": round(ma200, 2) if ma200 else None,
        "ma200_dev_pct": round(ma_dev, 2) if ma_dev is not None else None,
        "history": hist(dates, closes),
        "ma200_history": hist(dates, ma_hist_full),
    }


# ---------- スコアリング ----------
# 各指標を段階的な点数に変換する。閾値と配点は UI にもそのまま表示される。

def band(value, bands):
    """bands: [(上限, 点数), ...] 昇順。value が None なら (0, None)。"""
    if value is None:
        return 0, None
    for upper, pts in bands:
        if value < upper:
            return pts, upper
    return bands[-1][1], None


def score_signal(asset, vix, fg_score, pc_value, pc_kind):
    components = []

    # --- 市場全体の恐怖 (最大50点) ---
    pts, _ = band(vix, [(20, 0), (25, 6), (30, 12), (40, 16), (math.inf, 20)])
    components.append({
        "key": "vix", "label": "VIX(恐怖指数)", "points": pts, "max": 20,
        "value": vix, "unit": "", "group": "market",
        "desc": "20未満:平常 / 20-25 / 25-30 / 30-40 / 40以上で最大",
    })

    if fg_score is None:
        fg_pts = 0
    elif fg_score >= 45:
        fg_pts = 0
    elif fg_score >= 25:
        fg_pts = 6
    elif fg_score >= 10:
        fg_pts = 11
    else:
        fg_pts = 15
    components.append({
        "key": "fear_greed", "label": "Fear & Greed指数", "points": fg_pts, "max": 15,
        "value": fg_score, "unit": "", "group": "market",
        "desc": "45以上:0点 / 25-45 / 10-25 / 10未満(極度の恐怖)で最大",
    })

    if pc_value is None:
        pc_pts = 0
    elif pc_kind == "ratio":
        if pc_value < 0.9:
            pc_pts = 0
        elif pc_value < 1.0:
            pc_pts = 5
        elif pc_value < 1.2:
            pc_pts = 10
        else:
            pc_pts = 15
    else:  # CNNの0-100スコア(低い=弱気=買い場)
        if pc_value >= 50:
            pc_pts = 0
        elif pc_value >= 30:
            pc_pts = 5
        elif pc_value >= 15:
            pc_pts = 10
        else:
            pc_pts = 15
    components.append({
        "key": "put_call", "label": "プットコールレシオ", "points": pc_pts, "max": 15,
        "value": pc_value, "unit": "", "group": "market",
        "desc": "0.9未満:0点 / 0.9-1.0 / 1.0-1.2 / 1.2以上(弱気の極み)で最大"
        if pc_kind == "ratio" else
        "50以上:0点 / 30-50 / 15-30 / 15未満(弱気の極み)で最大",
    })

    # --- 資産固有の押し目 (最大50点) ---
    dd = asset["drawdown_pct"]  # 負の値
    depth = -dd if dd is not None else None
    pts, _ = band(depth, [(5, 0), (10, 7), (15, 12), (20, 16), (math.inf, 20)])
    components.append({
        "key": "drawdown", "label": "52週高値からの下落率", "points": pts, "max": 20,
        "value": dd, "unit": "%", "group": "asset",
        "desc": "-5%以内:0点 / -5〜-10% / -10〜-15% / -15〜-20% / -20%超で最大",
    })

    rsi = asset["rsi14"]
    if rsi is None:
        rsi_pts = 0
    elif rsi >= 45:
        rsi_pts = 0
    elif rsi >= 35:
        rsi_pts = 5
    elif rsi >= 30:
        rsi_pts = 10
    else:
        rsi_pts = 15
    components.append({
        "key": "rsi", "label": "RSI(14日)", "points": rsi_pts, "max": 15,
        "value": rsi, "unit": "", "group": "asset",
        "desc": "45以上:0点 / 35-45 / 30-35 / 30未満(売られすぎ)で最大",
    })

    dev = asset["ma200_dev_pct"]
    if dev is None:
        dev_pts = 0
    elif dev >= 0:
        dev_pts = 0
    elif dev >= -5:
        dev_pts = 5
    elif dev >= -10:
        dev_pts = 10
    else:
        dev_pts = 15
    components.append({
        "key": "ma200", "label": "200日移動平均線との乖離", "points": dev_pts, "max": 15,
        "value": dev, "unit": "%", "group": "asset",
        "desc": "プラス:0点 / 0〜-5% / -5〜-10% / -10%超の下方乖離で最大",
    })

    score = sum(c["points"] for c in components)

    if score < 20:
        level, level_name = 1, "通常の積立のみ"
        action = "特に割安のシグナルはありません。いつも通りの積立を続けましょう。"
    elif score < 40:
        level, level_name = 2, "調整の兆し・注視"
        action = "調整の初期段階の可能性。買い増し資金を準備しつつ、指標の悪化(=買い場の接近)を待ちましょう。"
    elif score < 65:
        level, level_name = 3, "買い増し検討"
        action = "恐怖指標と価格の両面で割安シグナルが出ています。予定資金の一部(例:1/3〜1/2)での買い増しを検討できる水準です。"
    else:
        level, level_name = 4, "絶好の買い増しチャンス"
        action = "複数の指標が極端な水準です。歴史的にはこうした局面での買い増しが長期リターンに寄与してきました。資金を分割しつつ積極的な買い増しを検討する水準です。"

    return {
        "score": score,
        "level": level,
        "level_name": level_name,
        "action": action,
        "components": components,
    }


# ---------- サンプルデータ生成 ----------

def gen_sample():
    rng = random.Random(42)
    today = datetime(2026, 7, 17)
    dates = []
    d = today - timedelta(days=730)
    while d <= today:
        if d.weekday() < 5:
            dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)

    def walk(start, drift, vol, floor=None):
        vals, v = [], start
        for _ in dates:
            v *= 1 + rng.gauss(drift, vol)
            if floor:
                v = max(v, floor)
            vals.append(v)
        return vals

    n225 = walk(36000, 0.0004, 0.011)
    acwi = walk(105, 0.0004, 0.009)
    # 直近1.5ヶ月に-12%程度の調整を入れる(買い増し検討シグナルのデモ)
    for i in range(1, 31):
        n225[-i] *= 1 - 0.004 * (31 - i)
        acwi[-i] *= 1 - 0.0035 * (31 - i)
    vix = [max(11, 16 + 14 * math.exp(-((len(dates) - 1 - i) / 12) ** 2) + rng.gauss(0, 1.5))
           for i in range(len(dates))]
    usdjpy = walk(152, 0.0, 0.004)
    fg_hist = [max(3, min(97, 50 - (vix[i] - 16) * 3 + rng.gauss(0, 4))) for i in range(len(dates))]
    pc_hist = [max(0.55, min(1.5, 0.85 + (vix[i] - 16) * 0.02 + rng.gauss(0, 0.05)))
               for i in range(len(dates))]

    return {
        "dates": dates, "n225": n225, "acwi": acwi, "vix": vix,
        "usdjpy": usdjpy, "fg": fg_hist, "pc": pc_hist,
    }


# ---------- メイン ----------

def load_previous():
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="ダミーデータを生成")
    args = parser.parse_args()

    prev = load_previous()
    errors = []
    market = {}
    assets = {}

    if args.sample:
        s = gen_sample()
        dates = s["dates"]
        market["vix"] = {
            "value": round(s["vix"][-1], 2),
            "percentile_1y": round(percentile_rank(s["vix"][-252:], s["vix"][-1]), 1),
            "history": hist(dates, s["vix"]),
        }
        market["fear_greed"] = {
            "score": round(s["fg"][-1], 1),
            "rating": "fear",
            "history": hist(dates, s["fg"]),
        }
        market["put_call"] = {
            "value": round(s["pc"][-1], 2),
            "kind": "ratio",
            "history": hist(dates, s["pc"]),
        }
        market["usdjpy"] = {"value": round(s["usdjpy"][-1], 2), "history": hist(dates, s["usdjpy"])}
        assets["n225"] = build_asset("日経平均株価", "JPY", dates, s["n225"])
        assets["acwi"] = build_asset("オルカン(ACWI)", "USD", dates, s["acwi"])
        sample = True
    else:
        sample = False
        # VIX
        try:
            d, v = fetch_yahoo("^VIX")
            market["vix"] = {
                "value": round(v[-1], 2),
                "percentile_1y": round(percentile_rank(v[-252:], v[-1]), 1),
                "history": hist(d, v),
            }
        except Exception as e:  # noqa: BLE001
            errors.append(f"VIX: {e}")
            market["vix"] = prev.get("market", {}).get("vix")

        # 日経平均
        try:
            d, v = fetch_yahoo("^N225")
            assets["n225"] = build_asset("日経平均株価", "JPY", d, v)
        except Exception as e:  # noqa: BLE001
            errors.append(f"N225: {e}")
            assets["n225"] = prev.get("assets", {}).get("n225")

        # オルカン代替 (iShares MSCI ACWI ETF)
        try:
            d, v = fetch_yahoo("ACWI")
            assets["acwi"] = build_asset("オルカン(ACWI)", "USD", d, v)
        except Exception as e:  # noqa: BLE001
            errors.append(f"ACWI: {e}")
            assets["acwi"] = prev.get("assets", {}).get("acwi")

        # ドル円(参考表示)
        try:
            d, v = fetch_yahoo("JPY=X")
            market["usdjpy"] = {"value": round(v[-1], 2), "history": hist(d, v)}
        except Exception as e:  # noqa: BLE001
            errors.append(f"USDJPY: {e}")
            market["usdjpy"] = prev.get("market", {}).get("usdjpy")

        # CNN Fear & Greed + プットコールレシオ
        try:
            cnn = fetch_cnn()
        except Exception as e:  # noqa: BLE001
            errors.append(f"CNN: {e}")
            cnn = None
        try:
            if cnn is None:
                raise RuntimeError("CNN data unavailable")
            fg = cnn["fear_and_greed"]
            fg_hist_raw = cnn.get("fear_and_greed_historical", {}).get("data", [])
            fg_history = [
                {"d": datetime.fromtimestamp(p["x"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
                 "v": round(p["y"], 1)}
                for p in fg_hist_raw[-HISTORY_DAYS:]
            ]
            market["fear_greed"] = {
                "score": round(fg["score"], 1),
                "rating": fg.get("rating", ""),
                "history": fg_history,
            }
        except Exception as e:  # noqa: BLE001
            errors.append(f"FearGreed: {e}")
            market["fear_greed"] = prev.get("market", {}).get("fear_greed")

        try:
            if cnn is None:
                raise RuntimeError("CNN data unavailable")
            pc = cnn["put_call_options"]
            pc_data = pc.get("data", [])
            last_y = pc_data[-1]["y"] if pc_data else pc.get("score")
            # y が 0.3〜3 ならレシオそのもの、それ以外は 0-100 スコアとみなす
            kind = "ratio" if last_y is not None and 0.3 <= last_y <= 3 else "score"
            pc_history = [
                {"d": datetime.fromtimestamp(p["x"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
                 "v": round(p["y"], 3)}
                for p in pc_data[-HISTORY_DAYS:]
            ]
            market["put_call"] = {
                "value": round(last_y, 3) if last_y is not None else None,
                "kind": kind,
                "history": pc_history,
            }
        except Exception as e:  # noqa: BLE001
            errors.append(f"PutCall: {e}")
            market["put_call"] = prev.get("market", {}).get("put_call")

    # シグナル計算
    vix_val = (market.get("vix") or {}).get("value")
    fg_val = (market.get("fear_greed") or {}).get("score")
    pc = market.get("put_call") or {}
    pc_val, pc_kind = pc.get("value"), pc.get("kind", "ratio")

    signals = {}
    for key in ("n225", "acwi"):
        if assets.get(key):
            signals[key] = score_signal(assets[key], vix_val, fg_val, pc_val, pc_kind)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample": sample,
        "errors": errors,
        "market": market,
        "assets": assets,
        "signals": signals,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    print(f"wrote {os.path.normpath(OUT_PATH)} (sample={sample}, errors={errors})")
    if errors and all(market.get(k) is None for k in ("vix", "fear_greed")) :
        sys.exit(1)


if __name__ == "__main__":
    main()
