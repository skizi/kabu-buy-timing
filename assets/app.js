/* 買い増しタイミング判定ダッシュボード */
(async function () {
  "use strict";

  const $ = (sel, el = document) => el.querySelector(sel);
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  let data;
  try {
    const res = await fetch("data/data.json", { cache: "no-store" });
    data = await res.json();
  } catch (e) {
    $("#banner").hidden = false;
    $("#banner").textContent = "データの読み込みに失敗しました。時間をおいて再読み込みしてください。";
    return;
  }

  const LV = {
    1: { name: "通常の積立のみ", icon: "⏸️", cls: "lv1" },
    2: { name: "調整の兆し・注視", icon: "👀", cls: "lv2" },
    3: { name: "買い増し検討", icon: "🛒", cls: "lv3" },
    4: { name: "絶好の買い増しチャンス", icon: "🔥", cls: "lv4" },
  };
  const LV_FILL = { 1: "--lv1", 2: "--lv2-fill", 3: "--lv3-fill", 4: "--lv4-fill" };

  const fmt = (v, digits = 2) =>
    v == null ? "—" : Number(v).toLocaleString("ja-JP", { maximumFractionDigits: digits });

  // ---------- ヘッダー / バナー ----------
  {
    const gen = new Date(data.generated_at);
    $("#updated-at").textContent = "最終更新: " +
      gen.toLocaleString("ja-JP", { timeZone: "Asia/Tokyo", dateStyle: "medium", timeStyle: "short" }) + " JST";

    const msgs = [];
    if (data.sample) {
      msgs.push("⚠️ 現在サンプルデータを表示中です。GitHub Actions のワークフロー「Update data & deploy」が実行されると実データに置き換わります。");
    } else {
      const ageDays = (Date.now() - gen.getTime()) / 86400000;
      if (ageDays > 4) msgs.push(`⚠️ データが ${Math.floor(ageDays)} 日間更新されていません。GitHub Actions の実行状況を確認してください。`);
    }
    if (data.errors && data.errors.length) {
      msgs.push("一部データの取得に失敗しています(前回値で代用): " + data.errors.join(" / "));
    }
    if (msgs.length) {
      $("#banner").hidden = false;
      $("#banner").innerHTML = msgs.map((m) => `<div>${m}</div>`).join("");
    }
  }

  // ---------- SVG ヘルパー ----------
  const NS = "http://www.w3.org/2000/svg";
  function svgEl(tag, attrs, parent) {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
    if (parent) parent.appendChild(el);
    return el;
  }

  // スコアのドーナツゲージ
  function donut(score, level) {
    const size = 108, r = 44, cx = size / 2, cy = size / 2;
    const svg = svgEl("svg", {
      viewBox: `0 0 ${size} ${size}`, width: size, height: size,
      class: "score-donut", role: "img",
      "aria-label": `買い増しスコア ${score} / 100`,
    });
    svgEl("circle", { cx, cy, r, fill: "none", stroke: "var(--grid)", "stroke-width": 10 }, svg);
    const circ = 2 * Math.PI * r;
    svgEl("circle", {
      cx, cy, r, fill: "none",
      stroke: `var(${LV_FILL[level]})`, "stroke-width": 10, "stroke-linecap": "round",
      "stroke-dasharray": `${(circ * score) / 100} ${circ}`,
      transform: `rotate(-90 ${cx} ${cy})`,
    }, svg);
    const t = svgEl("text", { x: cx, y: cy - 2, "text-anchor": "middle", class: "score-num", fill: "currentColor" }, svg);
    t.textContent = score;
    const d = svgEl("text", { x: cx, y: cy + 18, "text-anchor": "middle", class: "score-den" }, svg);
    d.textContent = "/ 100";
    return svg;
  }

  // 折れ線チャート(ホバー付き)
  function lineChart(container, seriesList, opts = {}) {
    const H = opts.height || 150, W = 640;
    const padL = 8, padR = 8, padT = 10, padB = 20;
    const all = seriesList.flatMap((s) => s.data.map((p) => p.v)).filter((v) => v != null);
    if (!all.length) { container.textContent = "データなし"; return; }
    let min = Math.min(...all), max = Math.max(...all);
    if (opts.min != null) min = Math.min(min, opts.min);
    if (opts.max != null) max = Math.max(max, opts.max);
    const span = max - min || 1;
    min -= span * 0.06; max += span * 0.06;

    const base = seriesList[0].data;
    const n = base.length;
    const x = (i) => padL + (i / Math.max(n - 1, 1)) * (W - padL - padR);
    const y = (v) => padT + (1 - (v - min) / (max - min)) * (H - padT - padB);

    const chartDiv = document.createElement("div");
    chartDiv.className = "chart";
    container.appendChild(chartDiv);
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label || "" }, null);
    chartDiv.appendChild(svg);

    // 罫線(控えめに3本)+ 目盛
    for (let g = 0; g < 3; g++) {
      const gv = min + ((g + 0.5) / 3) * (max - min);
      svgEl("line", { x1: padL, x2: W - padR, y1: y(gv), y2: y(gv), stroke: "var(--grid)", "stroke-width": 1 }, svg);
      const tl = svgEl("text", { x: W - padR, y: y(gv) - 3, "text-anchor": "end", "font-size": 10, fill: "var(--text-muted)" }, svg);
      tl.textContent = fmt(gv, gv >= 100 ? 0 : 1);
    }
    // 横基準線(オプション:例 VIX=30)
    if (opts.refY != null && opts.refY > min && opts.refY < max) {
      svgEl("line", {
        x1: padL, x2: W - padR, y1: y(opts.refY), y2: y(opts.refY),
        stroke: "var(--baseline)", "stroke-width": 1, "stroke-dasharray": "4 4",
      }, svg);
      const rl = svgEl("text", { x: padL, y: y(opts.refY) - 3, "font-size": 10, fill: "var(--text-muted)" }, svg);
      rl.textContent = opts.refLabel || "";
    }
    // X軸日付(先頭・中央・末尾)
    [0, Math.floor((n - 1) / 2), n - 1].forEach((i, k) => {
      const anchor = k === 0 ? "start" : k === 1 ? "middle" : "end";
      const tl = svgEl("text", { x: x(i), y: H - 5, "text-anchor": anchor, "font-size": 10, fill: "var(--text-muted)" }, svg);
      tl.textContent = (base[i]?.d || "").slice(2).replace(/-/g, "/");
    });

    for (const s of seriesList) {
      const pts = s.data.map((p, i) => (p.v == null ? null : `${x(i)},${y(p.v)}`)).filter(Boolean);
      if (s.area) {
        svgEl("polygon", {
          points: `${padL},${y(min)} ${pts.join(" ")} ${x(s.data.length - 1)},${y(min)}`,
          fill: s.areaFill || "var(--series-1-soft)", stroke: "none",
        }, svg);
      }
      svgEl("polyline", {
        points: pts.join(" "), fill: "none",
        stroke: s.color || "var(--series-1)", "stroke-width": 2,
        "stroke-linejoin": "round", "stroke-linecap": "round",
        "stroke-dasharray": s.dash || "none",
      }, svg);
    }

    // ホバー(クロスヘア+ツールチップ)
    const cross = svgEl("line", { y1: padT, y2: H - padB, stroke: "var(--baseline)", "stroke-width": 1, visibility: "hidden" }, svg);
    const dot = svgEl("circle", { r: 4, fill: seriesList[0].color || "var(--series-1)", stroke: "var(--surface-1)", "stroke-width": 2, visibility: "hidden" }, svg);
    const tip = document.createElement("div");
    tip.className = "tip";
    tip.style.display = "none";
    chartDiv.appendChild(tip);

    function onMove(ev) {
      const rect = svg.getBoundingClientRect();
      const relX = ((ev.clientX - rect.left) / rect.width) * W;
      let i = Math.round(((relX - padL) / (W - padL - padR)) * (n - 1));
      i = Math.max(0, Math.min(n - 1, i));
      const p = base[i];
      if (!p || p.v == null) return;
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i));
      cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(p.v));
      dot.setAttribute("visibility", "visible");
      tip.style.display = "block";
      tip.style.left = `${(x(i) / W) * rect.width}px`;
      tip.style.top = `${(y(p.v) / H) * rect.height}px`;
      let html = `<span class="d">${p.d}</span><br><b>${fmt(p.v, opts.digits ?? 2)}</b>`;
      for (let s = 1; s < seriesList.length; s++) {
        const q = seriesList[s].data[i];
        if (q && q.v != null) html += ` <span class="d">${seriesList[s].name}: ${fmt(q.v, opts.digits ?? 2)}</span>`;
      }
      tip.innerHTML = html;
    }
    function onLeave() {
      cross.setAttribute("visibility", "hidden");
      dot.setAttribute("visibility", "hidden");
      tip.style.display = "none";
    }
    svg.addEventListener("pointermove", onMove);
    svg.addEventListener("pointerleave", onLeave);
  }

  // 閾値スケールバー
  function scaleBar(container, { min, max, segments, value, labels }) {
    const wrap = document.createElement("div");
    wrap.className = "scale";
    const bar = document.createElement("div");
    bar.className = "scale-bar";
    const total = max - min;
    for (const seg of segments) {
      const span = document.createElement("span");
      span.style.width = `${((seg.to - seg.from) / total) * 100}%`;
      span.style.background = seg.color;
      bar.appendChild(span);
    }
    if (value != null) {
      const m = document.createElement("div");
      m.className = "scale-marker";
      const clamped = Math.max(min, Math.min(max, value));
      m.style.left = `calc(${(((clamped - min) / total) * 100).toFixed(2)}% - 1px)`;
      bar.appendChild(m);
    }
    wrap.appendChild(bar);
    const lab = document.createElement("div");
    lab.className = "scale-labels";
    lab.innerHTML = labels.map((l) => `<span>${l}</span>`).join("");
    wrap.appendChild(lab);
    container.appendChild(wrap);
  }

  const segColors = {
    none: "var(--grid)",
    watch: "var(--lv2-fill)",
    buy: "var(--lv3-fill)",
    strong: "var(--lv4-fill)",
  };

  // ---------- 総合シグナルカード ----------
  {
    const grid = $("#signal-cards");
    for (const key of ["n225", "acwi", "gold"]) {
      const sig = data.signals?.[key];
      const asset = data.assets?.[key];
      if (!sig || !asset) continue;
      const lv = LV[sig.level];
      const card = document.createElement("article");
      card.className = "signal-card";
      card.innerHTML = `
        <div class="signal-head">
          <div class="signal-asset">${asset.name}</div>
          <div class="signal-price">${fmt(asset.price)} ${asset.currency === "JPY" ? "円" : "ドル"}<span style="color:var(--text-muted)"> (${asset.date})</span></div>
        </div>
        <div class="signal-main"></div>
        <p class="signal-action">${sig.action}</p>
        <details class="breakdown">
          <summary>スコア内訳を見る</summary>
          <div class="bd-rows"></div>
        </details>`;
      if (key === "gold") {
        const note = document.createElement("p");
        note.className = "signal-action";
        note.style.cssText = "color:var(--text-muted);font-size:0.78rem;margin:2px 0 0";
        note.textContent = "※ 金は恐怖局面で上がりやすいため、VIX等の恐怖指標は使わず価格指標のみ(100点満点)で判定";
        card.appendChild(note);
      }
      const main = $(".signal-main", card);
      main.appendChild(donut(sig.score, sig.level));
      const right = document.createElement("div");
      right.innerHTML = `<div class="signal-level ${lv.cls}-text"><span class="icon">${lv.icon}</span>${lv.name}</div>`;
      main.appendChild(right);

      const rows = $(".bd-rows", card);
      for (const c of sig.components) {
        const row = document.createElement("div");
        row.className = "bd-row";
        const valTxt = c.value == null ? "—" : `${fmt(c.value, 1)}${c.unit || ""}`;
        row.innerHTML = `
          <div class="bd-label" title="${c.desc}">${c.label} <span style="color:var(--text-muted)">(${valTxt})</span></div>
          <div class="bd-bar"><div class="bd-fill" style="width:${(c.points / c.max) * 100}%"></div></div>
          <div class="bd-pts">${c.points} / ${c.max}</div>`;
        rows.appendChild(row);
      }
      grid.appendChild(card);
    }
  }

  // ---------- 市場指標カード ----------
  {
    const grid = $("#market-cards");

    function card(title, meta) {
      const el = document.createElement("article");
      el.className = "card";
      el.innerHTML = `<h3>${title}</h3><div class="meta">${meta}</div>`;
      grid.appendChild(el);
      return el;
    }

    // VIX
    const vix = data.market?.vix;
    if (vix) {
      const el = card("VIX(恐怖指数)", "S&P500オプションから算出される市場の警戒度");
      const big = document.createElement("div");
      big.className = "big";
      const zone = vix.value >= 30 ? ["絶好水準", "lv4-text"] : vix.value >= 25 ? ["買い場水準", "lv3-text"] : vix.value >= 20 ? ["警戒", "lv2-text"] : ["平常", "lv1-text"];
      big.innerHTML = `${fmt(vix.value)}<span class="tag ${zone[1]}">${zone[0]}</span>`;
      el.appendChild(big);
      scaleBar(el, {
        min: 10, max: 50, value: vix.value,
        segments: [
          { from: 10, to: 20, color: segColors.none },
          { from: 20, to: 25, color: segColors.watch },
          { from: 25, to: 30, color: segColors.buy },
          { from: 30, to: 50, color: segColors.strong },
        ],
        labels: ["10", "20", "25", "30", "50"],
      });
      lineChart(el, [{ data: vix.history, area: true }], { label: "VIXの1年推移", refY: 30, refLabel: "30", digits: 1 });
      const d = document.createElement("p");
      d.className = "desc";
      d.textContent = `直近1年の中で高い方から数えて上位 ${Math.max(1, Math.round(100 - (vix.percentile_1y ?? 50)))}% 以内の水準。VIXが30を超える局面は年に数回あるかないかで、長期投資の仕込み場になりやすいゾーンです。`;
      el.appendChild(d);
    }

    // Fear & Greed
    const fg = data.market?.fear_greed;
    if (fg) {
      const el = card("Fear & Greed 指数(CNN)", "7つの市場指標を合成した投資家心理の温度計(0=極度の恐怖)");
      const zone = fg.score < 10 ? ["極度の恐怖", "lv4-text"] : fg.score < 25 ? ["強い恐怖", "lv3-text"] : fg.score < 45 ? ["恐怖寄り", "lv2-text"] : ["中立〜強気", "lv1-text"];
      const big = document.createElement("div");
      big.className = "big";
      big.innerHTML = `${fmt(fg.score, 0)}<span class="tag ${zone[1]}">${zone[0]}</span>`;
      el.appendChild(big);
      scaleBar(el, {
        min: 0, max: 100, value: fg.score,
        segments: [
          { from: 0, to: 10, color: segColors.strong },
          { from: 10, to: 25, color: segColors.buy },
          { from: 25, to: 45, color: segColors.watch },
          { from: 45, to: 100, color: segColors.none },
        ],
        labels: ["0", "10", "25", "45", "100"],
      });
      if (fg.history?.length) lineChart(el, [{ data: fg.history, area: true }], { label: "Fear&Greedの推移", min: 0, max: 100, digits: 0 });
      const d = document.createElement("p");
      d.className = "desc";
      d.textContent = "「他人が恐怖に駆られているときに貪欲であれ」の実践指標。25未満(恐怖)で買い場が近づき、10未満(極度の恐怖)は歴史的に良い仕込み場でした。";
      el.appendChild(d);
    }

    // Put/Call
    const pc = data.market?.put_call;
    if (pc) {
      const isRatio = pc.kind === "ratio";
      const el = card(
        "プットコールレシオ" + (isRatio ? "" : "(スコア表示)"),
        isRatio ? "プット(下落保険)/コール(上昇期待)の出来高比。高いほど弱気" : "CNNによる0-100スコア。低いほど弱気(=逆張りの買い場)"
      );
      let zone;
      if (isRatio) {
        zone = pc.value >= 1.2 ? ["弱気の極み", "lv4-text"] : pc.value >= 1.0 ? ["弱気優勢", "lv3-text"] : pc.value >= 0.9 ? ["やや弱気", "lv2-text"] : ["平常", "lv1-text"];
      } else {
        zone = pc.value < 15 ? ["弱気の極み", "lv4-text"] : pc.value < 30 ? ["弱気優勢", "lv3-text"] : pc.value < 50 ? ["やや弱気", "lv2-text"] : ["平常", "lv1-text"];
      }
      const big = document.createElement("div");
      big.className = "big";
      big.innerHTML = `${fmt(pc.value, isRatio ? 2 : 0)}<span class="tag ${zone[1]}">${zone[0]}</span>`;
      el.appendChild(big);
      scaleBar(el, isRatio ? {
        min: 0.5, max: 1.5, value: pc.value,
        segments: [
          { from: 0.5, to: 0.9, color: segColors.none },
          { from: 0.9, to: 1.0, color: segColors.watch },
          { from: 1.0, to: 1.2, color: segColors.buy },
          { from: 1.2, to: 1.5, color: segColors.strong },
        ],
        labels: ["0.5", "0.9", "1.0", "1.2", "1.5"],
      } : {
        min: 0, max: 100, value: pc.value,
        segments: [
          { from: 0, to: 15, color: segColors.strong },
          { from: 15, to: 30, color: segColors.buy },
          { from: 30, to: 50, color: segColors.watch },
          { from: 50, to: 100, color: segColors.none },
        ],
        labels: ["0", "15", "30", "50", "100"],
      });
      if (pc.history?.length) lineChart(el, [{ data: pc.history, area: true }], { label: "プットコールレシオの推移", digits: isRatio ? 2 : 0 });
      const d = document.createElement("p");
      d.className = "desc";
      d.textContent = "皆が下落に備えてプットを買い漁っている(レシオが高い)ときほど、悲観の売りが出尽くしに近いという逆張りシグナルです。";
      el.appendChild(d);
    }

    // USD/JPY(参考)
    const uj = data.market?.usdjpy;
    if (uj) {
      const el = card("ドル円(参考・スコア対象外)", "オルカン・金(ドル建て)の円建て評価額に効く為替レート");
      const big = document.createElement("div");
      big.className = "big";
      big.innerHTML = `${fmt(uj.value)}<span style="font-size:0.9rem;color:var(--text-muted)">円/ドル</span>`;
      el.appendChild(big);
      if (uj.history?.length) lineChart(el, [{ data: uj.history, area: true }], { label: "ドル円の推移", digits: 1 });
      const d = document.createElement("p");
      d.className = "desc";
      d.textContent = "株安と円高が同時に来ると、円建てオルカンは指数以上に下がります。逆にその局面は円ベースでの仕込み効率が良い局面でもあります。";
      el.appendChild(d);
    }
  }

  // ---------- 資産別詳細 ----------
  {
    const wrap = $("#asset-details");
    for (const key of ["n225", "acwi", "gold"]) {
      const a = data.assets?.[key];
      if (!a) continue;
      const block = document.createElement("article");
      block.className = "asset-block";
      const unit = a.currency === "JPY" ? "円" : "ドル";
      block.innerHTML = `
        <h3>${a.name}</h3>
        <div class="asset-stats">
          <div class="stat"><div class="k">終値 (${a.date})</div><div class="v">${fmt(a.price)} ${unit}</div></div>
          <div class="stat"><div class="k">52週高値からの下落</div><div class="v ${a.drawdown_pct < -5 ? "neg" : ""}">${fmt(a.drawdown_pct, 1)}%</div></div>
          <div class="stat"><div class="k">RSI(14日)</div><div class="v">${fmt(a.rsi14, 1)}</div></div>
          <div class="stat"><div class="k">200日線との乖離</div><div class="v ${a.ma200_dev_pct < 0 ? "neg" : ""}">${a.ma200_dev_pct > 0 ? "+" : ""}${fmt(a.ma200_dev_pct, 1)}%</div></div>
        </div>`;
      lineChart(block, [
        { data: a.history, area: true, name: a.name },
        { data: a.ma200_history, color: "var(--text-muted)", dash: "5 4", name: "200日線" },
      ], { label: `${a.name}の1年チャート`, height: 200, digits: 0 });
      const legend = document.createElement("div");
      legend.className = "legend";
      legend.innerHTML = `
        <span><span class="sw" style="background:var(--series-1)"></span>終値</span>
        <span><span class="sw" style="background:var(--text-muted)"></span>200日移動平均線(点線)</span>`;
      block.appendChild(legend);
      wrap.appendChild(block);
    }
  }

  // ---------- 判定基準テーブル ----------
  {
    const tbody = $("#criteria-table tbody");
    const groups = { market: "市場全体の恐怖", asset: "資産ごとの押し目" };

    function addScheme(sig, heading) {
      if (!sig) return;
      const hr = document.createElement("tr");
      hr.innerHTML = `<td colspan="4" style="font-weight:700;background:var(--page)">${heading}</td>`;
      tbody.appendChild(hr);
      for (const c of sig.components) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${c.label}</td><td class="grp">${groups[c.group]}</td><td>${c.max}点</td><td>${c.desc}</td>`;
        tbody.appendChild(tr);
      }
    }
    addScheme(data.signals?.n225 || data.signals?.acwi, "日経平均・オルカン(恐怖指標50点+価格指標50点)");
    addScheme(data.signals?.gold, "金(ゴールド)— 恐怖局面で上がりやすい資産のため、価格指標のみで100点");
  }
})();
