/* SACW V1.1.2 结构标注与参数校准工作台前端
 * 图表：TradingView Lightweight Charts v4（本地 vendored）
 * 数据：/api/v1/*（标准库 HTTP 服务）
 */
(function () {
  "use strict";

  var LWC = window.LightweightCharts;

  var COLORS = {
    up: "#26a69a",
    down: "#ef5350",
    sma: "#42a5f5",
    zigzag: "#ffb74d",
    atr: "#ffa726",
    structureActive: "#ab47bc",
    structureClosed: "#5c6270",
    candidate: "#b0bec5",
    pending: "#ffd54f",
    text: "#d1d4dc",
    grid: "#1f2430",
    border: "#232935",
    panel: "#0e1117"
  };

  var BULL_STATES = { UPTREND: 1, BULLISH: 1, TREND_UP: 1 };
  var BEAR_STATES = { DOWNTREND: 1, BEARISH: 1, TREND_DOWN: 1 };
  var WARN_STATES = {
    WEAKENING: 1, PULLBACK: 1, TRANSITION: 1, REVERSAL_CANDIDATE: 1, RANGE: 1
  };

  var STATE_OPTIONS = {
    "1M": ["UPTREND", "WEAKENING", "DOWNTREND", "UNKNOWN"],
    "1W": ["BULLISH", "WEAKENING", "BEARISH", "TRANSITION", "UNKNOWN"],
    "1D": ["BULLISH", "PULLBACK", "BEARISH", "TRANSITION", "UNKNOWN"],
    "4H": ["TREND_UP", "TREND_DOWN", "PULLBACK", "RANGE", "TRANSITION", "UNKNOWN"],
    "1H": ["BULLISH", "BEARISH", "PULLBACK", "RANGE", "REVERSAL_CANDIDATE",
      "TRANSITION", "UNKNOWN"]
  };

  var STATUS_FLOW = {
    DRAFT: [["SUBMITTED", "提交审核"], ["AMBIGUOUS", "标记歧义"]],
    SUBMITTED: [["REVIEWED", "审核通过"], ["REJECTED", "审核拒绝"]],
    REVIEWED: [["APPROVED", "批准"], ["REJECTED", "审核拒绝"]],
    APPROVED: [["FROZEN", "冻结"]],
    REJECTED: [["DRAFT", "退回草稿"]],
    AMBIGUOUS: [["DRAFT", "退回草稿"]]
  };

  var state = {
    meta: null,
    payload: null,
    tf: "4H",
    project: null,
    annotations: [],
    projectAnnotations: [],
    groundTruthCount: 0,
    goldenDatasets: [],
    zoneMode: "ANCHOR_ONLY",
    intervalState: null,
    protectedEventType: "INIT",
    manualOverlays: [],
    manualPriceLines: [],
    continuous: true,
    savedCount: 0,
    tool: "select",
    pending: null,
    pendingClicks: [],
    selectedBar: null,
    priceChart: null,
    atrChart: null,
    series: {},
    overlays: [],
    priceLines: [],
    syncing: false,
    lastSize: {},
    toggles: {
      sma: true, atr: true, zigzag: true, candidate: true,
      swing: true, zone: true, structure: true, levels: true, manual: true
    },
    cases: [],
    suite: null,
    selectedCase: null,
    caseFilter: { search: "", status: "" },
    snapshots: {},
    live: {
      enabled: true,
      timer: null,
      since: null,
      busy: false,
      appliedAt: 0,
      error: null,
      info: null
    },
    // 向左滚动加载更早历史：只追加 K 线，叠加层保持服务端最新一版。
    view: {
      userAdjusted: false
    },
    history: {
      busy: false,
      ready: false,
      suppress: false,
      exhausted: {},
      loadedLeft: {}
    }
  };

  var el = {};

  /* -------------------------------------------------------------- 工具函数 */

  function $(id) { return document.getElementById(id); }

  function fmt(value, digits) {
    if (value === null || value === undefined || value === "" || isNaN(value)) return "—";
    return Number(value).toFixed(digits === undefined ? 2 : digits);
  }

  function setStatus(text, target) {
    var node = target || el.status;
    if (node) node.textContent = text;
  }

  function api(path, options) {
    var opts = options || {};
    var init = { method: opts.method || "GET", cache: "no-store", headers: {} };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    return fetch(path, init).then(function (response) {
      return response.json().then(function (envelope) {
        if (!response.ok || (envelope && envelope.error)) {
          var message = envelope && envelope.error ? envelope.error.code + ": " + envelope.error.message
            : "HTTP " + response.status;
          throw new Error(message);
        }
        return envelope ? envelope.data : null;
      });
    });
  }

  function uniqueAscending(data) {
    var out = [];
    var last = -Infinity;
    for (var i = 0; i < data.length; i += 1) {
      var item = data[i];
      if (!item || typeof item.time !== "number") continue;
      if (item.time <= last) continue;
      last = item.time;
      out.push(item);
    }
    return out;
  }

  function stateClass(name) {
    if (!name) return "st-neutral";
    if (BULL_STATES[name]) return "st-up";
    if (BEAR_STATES[name]) return "st-down";
    if (WARN_STATES[name]) return "st-warn";
    return "st-neutral";
  }

  function fmtTime(seconds) {
    if (!seconds) return "—";
    var date = new Date(seconds * 1000);
    return date.toISOString().replace("T", " ").replace(".000Z", "Z");
  }

  function timeToBarIndex(candles, time) {
    for (var i = 0; i < candles.length; i += 1) {
      if (candles[i].time === time) return i;
    }
    return -1;
  }

  /* 相对前一根收盘的涨跌额与百分比，对齐 TradingView 图例的显示习惯。 */
  function changeText(section, bar, candle) {
    if (!section || !section.candles || !bar) return "";
    var index = timeToBarIndex(section.candles, bar.time);
    if (index <= 0) return "";
    var prev = section.candles[index - 1];
    var prevClose = Number(prev.close);
    if (!isFinite(prevClose) || prevClose === 0) return "";
    var diff = Number(candle.close) - prevClose;
    var pct = (diff / prevClose) * 100;
    var sign = diff >= 0 ? "+" : "";
    return "  Δ " + sign + fmt(diff) + " (" + sign + pct.toFixed(2) + "%)";
  }

  function barAt(candles, time) {
    var index = timeToBarIndex(candles, time);
    return index < 0 ? null : candles[index];
  }

  function shortId(id) {
    var text = String(id || "");
    if (text.length <= 22) return text;
    return text.slice(0, 10) + "…" + text.slice(-8);
  }

  function makeEl(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function clear(node) {
    if (node) node.textContent = "";
  }

  /* -------------------------------------------------------------- 图表选项 */

  function chartOptions() {
    return {
      layout: {
        background: { type: "solid", color: COLORS.panel },
        textColor: COLORS.text,
        fontSize: 11
      },
      grid: {
        vertLines: { color: COLORS.grid },
        horzLines: { color: COLORS.grid }
      },
      // 价格轴自动缩放：按当前可见 K 线与叠加层动态适配纵向范围。
      rightPriceScale: {
        borderColor: COLORS.border,
        autoScale: true,
        scaleMargins: { top: 0.12, bottom: 0.12 },
        entireTextOnly: true
      },
      timeScale: {
        borderColor: COLORS.border,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 6,
        barSpacing: 8,
        minBarSpacing: 0.5,
        fixLeftEdge: false,
        fixRightEdge: false,
        lockVisibleTimeRangeOnResize: true,
        shiftVisibleRangeOnNewBar: false
      },
      crosshair: {
        mode: LWC.CrosshairMode.Normal,
        vertLine: { color: COLORS.border, labelBackgroundColor: COLORS.border },
        horzLine: { color: COLORS.border, labelBackgroundColor: COLORS.border }
      },
      localization: {
        priceFormatter: function (price) { return price.toFixed(2); }
      }
    };
  }

  function destroyCharts() {
    if (state.priceChart) { state.priceChart.remove(); state.priceChart = null; }
    if (state.atrChart) { state.atrChart.remove(); state.atrChart = null; }
    state.series = {};
    state.overlays = [];
    state.priceLines = [];
    state.manualOverlays = [];
    state.manualPriceLines = [];
    state.smaTimes = [];
  }

  function bindSync(from, to) {
    from.timeScale().subscribeVisibleLogicalRangeChange(function (range) {
      if (!range || state.syncing) return;
      state.syncing = true;
      to.timeScale().setVisibleLogicalRange(range);
      state.syncing = false;
    });
  }

  /* ------------------------------------------------------- 向左滚动加载历史 */

  /* 整页只带最近 MAX_SERIES_BARS 根；用户把视野拖到最左侧时，按需向服务端
   * 取更早的一段并前插，避免首次打开就传输几十万根。 */

  var HISTORY_PAGE_BARS = 1000;
  var HISTORY_TRIGGER_BARS = 50;

  function bindHistoryLoading(chart) {
    // fitContent() 会触发一次范围回调，且初始可见范围含全部已装载 K 线。
    // 只有在首屏渲染完成（state.history.ready）后、用户把视野拖回最左端时才加载。
    chart.timeScale().subscribeVisibleLogicalRangeChange(function (range) {
      if (!range || !state.history.ready) return;
      // 程序性改写视野（前插补偿、同步图表）不应被当成用户手势，否则会连锁加载。
      if (state.history.suppress) return;
      if (range.from < HISTORY_TRIGGER_BARS) loadOlderBars();
    });
  }

  /* 在前插历史后补偿视野：同步调用期间挂起加载触发，且只在偏移确实生效时
   * 写入一次，避免与用户滚轮缩放争夺视野。 */
  function shiftVisibleRange(added) {
    if (!added || !state.priceChart) return;
    var range = state.priceChart.timeScale().getVisibleLogicalRange();
    if (!range) return;
    state.history.suppress = true;
    try {
      var shifted = { from: range.from + added, to: range.to + added };
      state.priceChart.timeScale().setVisibleLogicalRange(shifted);
      if (state.atrChart) state.atrChart.timeScale().setVisibleLogicalRange(shifted);
    } finally {
      // keepAlive 到下一帧：subscribe 回调可能在 setVisibleLogicalRange 之后异步派发。
      if (typeof requestAnimationFrame === "function") {
        requestAnimationFrame(function () { state.history.suppress = false; });
      } else {
        state.history.suppress = false;
      }
    }
  }

  function sectionCandles() {
    var section = currentSection();
    return (section && section.candles) || null;
  }

  function loadOlderBars() {
    var code = state.tf;
    if (state.history.busy || state.history.exhausted[code]) return;
    var candles = sectionCandles();
    if (!candles || !candles.length) return;

    state.history.busy = true;
    // 图表时间是秒级整数，而 /market/bars 的 to 接受 ISO 或纳秒整数；统一发 ISO，
    // 避免把秒级时间戳当成纳秒解析。
    var oldest = new Date(candles[0].time * 1000).toISOString();
    var params = "timeframe=" + encodeURIComponent(code) +
      "&to=" + encodeURIComponent(oldest) + "&limit=" + HISTORY_PAGE_BARS;

    api("/api/v1/market/bars?" + params).then(function (data) {
      state.history.busy = false;
      var older = data.bars || [];
      if (!older.length) {
        state.history.exhausted[code] = true;
        setStatus("已加载到最早一根 K 线（" + code + "）");
        return;
      }
      prependHistory(code, older);
    }).catch(function (error) {
      state.history.busy = false;
      setStatus("加载更早数据失败：" + error.message);
    });
  }

  function prependHistory(code, bars) {
    var section = (state.payload.series || {})[code];
    if (!section || !section.candles) return;

    var existing = {};
    section.candles.forEach(function (c) { existing[c.time] = true; });

    var added = bars.map(function (bar) {
      return {
        time: toChartTime(bar.openTime),
        open: Number(bar.open), high: Number(bar.high),
        low: Number(bar.low), close: Number(bar.close),
        isClosed: true,
        closeTime: toChartTime(bar.closeTime),
        barId: bar.barId
      };
    }).filter(function (candle) { return !existing[candle.time]; });

    if (!added.length) {
      state.history.exhausted[code] = true;
      return;
    }

    // 价格类序列由前端前插；指标/叠加层保持服务端下发的最新一版。
    section.candles = added.concat(section.candles);
    var volumes = bars.map(function (bar) {
      return {
        time: toChartTime(bar.openTime),
        value: Number(bar.volume),
        color: Number(bar.close) >= Number(bar.open)
          ? "rgba(38, 166, 154, 0.45)" : "rgba(239, 83, 80, 0.45)"
      };
    }).filter(function (v) { return !existing[v.time]; });
    section.volume = volumes.concat(section.volume || []);
    state.history.loadedLeft[code] = (state.history.loadedLeft[code] || 0) + added.length;

    if (code === state.tf && state.series.candles) {
      state.series.candles.setData(uniqueAscending(section.candles));
      if (state.series.volume) state.series.volume.setData(uniqueAscending(section.volume));
      // 前插后保持用户当前视野，避免画面跳动。
      shiftVisibleRange(added.length);
    }
    setStatus("已向前加载 " + added.length + " 根（" + code + "，共 " +
      section.candles.length + " 根）");
  }

  function toChartTime(iso) {
    return Math.floor(new Date(iso).getTime() / 1000);
  }

  function resizeChart(chart, container, key) {
    if (!chart || !container) return;
    var rect = container.getBoundingClientRect();
    var width = Math.floor(rect.width);
    var height = Math.floor(rect.height);
    if (width <= 0 || height <= 0) return;
    var last = state.lastSize[key];
    // 尺寸未变化时跳过 resize，避免 ResizeObserver 自触发循环。
    if (last && Math.abs(last[0] - width) < 2 && Math.abs(last[1] - height) < 2) return;
    state.lastSize[key] = [width, height];
    chart.resize(width, height);
  }

  function resizeCharts() {
    resizeChart(state.priceChart, el.priceChart, "price");
    if (state.toggles.atr) resizeChart(state.atrChart, el.atrChart, "atr");
  }

  function bindResize() {
    if (typeof ResizeObserver === "undefined") return;
    var observer = new ResizeObserver(function () { resizeCharts(); });
    observer.observe(el.priceChart);
    observer.observe(el.atrChart);
    state.resizeObserver = observer;
  }

  /* -------------------------------------------------------------- 数据访问 */

  function currentSection() {
    if (!state.payload || !state.payload.series) return null;
    return state.payload.series[state.tf] || null;
  }

  function currentFrame() {
    var frames = (state.payload && state.payload.timeframes) || [];
    for (var i = 0; i < frames.length; i += 1) {
      if (frames[i].code === state.tf) return frames[i];
    }
    return null;
  }

  function currentStructures() {
    var section = currentSection();
    return (section && section.structures) || [];
  }

  function currentZones() {
    var section = currentSection();
    return (section && section.zones) || [];
  }

  /* candidates 只包含“存在候选”的 Bar（稀疏），按需建立时间索引避免线性扫描。 */
  function currentCandidateAt(time) {
    var section = currentSection();
    if (!section || !section.candidates) return null;
    if (!section.candidateIndex || section.candidateIndexSize !== section.candidates.length) {
      var index = {};
      for (var i = 0; i < section.candidates.length; i += 1) {
        index[section.candidates[i].time] = section.candidates[i];
      }
      section.candidateIndex = index;
      section.candidateIndexSize = section.candidates.length;
    }
    return section.candidateIndex[time] || null;
  }

  /* -------------------------------------------------------------- 绘图 */

  function buildCharts() {
    destroyCharts();
    state.history.ready = false;

    var section = currentSection();
    if (!section || !section.candles || !section.candles.length) {
      setStatus("本周期无数据");
      return;
    }

    var priceRect = el.priceChart.getBoundingClientRect();
    var atrRect = el.atrChart.getBoundingClientRect();

    var priceChart = LWC.createChart(el.priceChart, Object.assign(chartOptions(), {
      width: Math.max(priceRect.width, 320),
      height: Math.max(priceRect.height, 240)
    }));
    var atrChart = LWC.createChart(el.atrChart, Object.assign(chartOptions(), {
      width: Math.max(atrRect.width, 320),
      height: Math.max(atrRect.height, 120)
    }));
    state.priceChart = priceChart;
    state.atrChart = atrChart;

    var candles = priceChart.addCandlestickSeries({
      upColor: COLORS.up,
      downColor: COLORS.down,
      borderVisible: false,
      wickUpColor: COLORS.up,
      wickDownColor: COLORS.down,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 }
    });
    candles.setData(uniqueAscending(section.candles));

    var volume = priceChart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "",
      lastValueVisible: false,
      priceLineVisible: false
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    volume.setData(uniqueAscending(section.volume));

    var sma = priceChart.addLineSeries({
      color: COLORS.sma, lineWidth: 2, priceLineVisible: false,
      lastValueVisible: false, crosshairMarkerVisible: false
    });
    sma.setData(uniqueAscending(section.sma || []));

    var zigzag = priceChart.addLineSeries({
      color: COLORS.zigzag, lineWidth: 2, priceLineVisible: false,
      lastValueVisible: false, crosshairMarkerVisible: false
    });
    zigzag.setData(uniqueAscending(section.zigzag || []));

    var atr = atrChart.addLineSeries({
      color: COLORS.atr, lineWidth: 2, priceLineVisible: false,
      lastValueVisible: true, crosshairMarkerVisible: false
    });
    atr.setData(uniqueAscending(section.atr || []));

    state.series = {
      candles: candles, volume: volume, sma: sma, zigzag: zigzag, atr: atr
    };
    state.smaTimes = uniqueAscending(section.sma || []).map(function (point) { return point.time; });

    bindSync(priceChart, atrChart);
    bindSync(atrChart, priceChart);
    bindCrosshair(priceChart, "price");
    bindCrosshair(atrChart, "atr");
    bindChartClick(priceChart);
    bindHistoryLoading(priceChart);
    bindViewportReset(priceChart);
    bindOverlayReclip(priceChart);

    applyInitialView(priceChart, atrChart);

    drawZones();
    drawStructures();
    drawLevelLines();
    drawReversalThreshold();
    refreshMarkers();
    applyToggles();

    if (typeof requestAnimationFrame === "function") requestAnimationFrame(resizeCharts);
    setTimeout(resizeCharts, 120);

    // 叠加层绘制与 resize 仍会触发范围回调，等首屏彻底稳定后再允许向左加载。
    setTimeout(function () { state.history.ready = true; }, 300);
  }

  /* ------------------------------------------------------------ 自适应视图 */

  /* TradingView 风格的首屏行为：默认展示最近一段便于阅读的根数，而不是把
   * 下发窗口里的全部 K 线塞进一屏（1200 根在 1680px 下每根不足 1.3px）。
   * 用户一旦自己缩放/平移，就不再自动改写视野（state.view.userAdjusted）。 */
  var DEFAULT_VISIBLE_BARS = 180;

  function applyInitialView(priceChart, atrChart) {
    var candles = sectionCandles() || [];
    var count = candles.length;
    if (!count) {
      priceChart.timeScale().fitContent();
      if (atrChart) atrChart.timeScale().fitContent();
      return;
    }
    var span = Math.min(DEFAULT_VISIBLE_BARS, count);
    var range = { from: count - span, to: count };
    priceChart.timeScale().setVisibleLogicalRange(range);
    if (atrChart) atrChart.timeScale().setVisibleLogicalRange(range);
    // 价格轴立即按可见区间重算，避免沿用上一周期的纵向范围。
    autoscalePrice(priceChart);
  }

  /* 视野变化后重画叠加层：Zone/N 结构需要按新的可见区重新裁剪，
   * 否则越界段会继续参与价格轴自动缩放。节流到下一帧，避免拖动时反复重绘。 */
  function bindOverlayReclip(chart) {
    var pending = false;
    chart.timeScale().subscribeVisibleLogicalRangeChange(function (range) {
      if (!range || !state.history.ready || state.history.suppress) return;
      if (pending) return;
      pending = true;
      var redraw = function () {
        pending = false;
        redrawOverlays();
      };
      if (typeof requestAnimationFrame === "function") requestAnimationFrame(redraw);
      else setTimeout(redraw, 16);
    });
  }

  function bindViewportReset(chart) {
    // 双击图区重置为自适应视图，行为对齐 TradingView。
    // 双击已被「Swing 同一根 Bar 确认」使用，因此只在选择工具且没有进行中的
    // 标注时接管，避免破坏标注流程。
    chart.subscribeDblClick(function (param) {
      if (!param || !param.point) return;
      if (state.tool !== "select" || state.pendingClicks.length) return;
      resetViewport();
    });
  }

  function autoscalePrice(chart) {
    if (!chart) return;
    try {
      if (state.series.candles) state.series.candles.priceScale().applyOptions({ autoScale: true });
    } catch (err) { /* 图表可能已被重建 */ }
  }

  /* 重置为自适应视图（工具栏按钮 / 双击图表）。 */
  function resetViewport() {
    if (!state.priceChart) return;
    var candles = sectionCandles() || [];
    var count = candles.length;
    if (!count) return;
    var span = Math.min(DEFAULT_VISIBLE_BARS, count);
    var range = { from: count - span, to: count };
    state.history.suppress = true;
    try {
      state.priceChart.timeScale().setVisibleLogicalRange(range);
      if (state.atrChart) state.atrChart.timeScale().setVisibleLogicalRange(range);
      autoscalePrice(state.priceChart);
    } finally {
      setTimeout(function () { state.history.suppress = false; }, 0);
    }
    state.view.userAdjusted = false;
    setStatus("已重置视图为最近 " + span + " 根（自适应）");
  }

  /* 显示已加载的全部 K 线（对齐 TradingView 的“全部数据”按钮）。 */
  function fitAll() {
    if (!state.priceChart) return;
    var candles = sectionCandles() || [];
    if (!candles.length) return;
    state.history.suppress = true;
    try {
      state.priceChart.timeScale().fitContent();
      if (state.atrChart) state.atrChart.timeScale().fitContent();
      autoscalePrice(state.priceChart);
    } finally {
      setTimeout(function () { state.history.suppress = false; }, 0);
    }
    state.view.userAdjusted = false;
    setStatus("已显示全部 " + candles.length + " 根 K 线");
  }

  function clearOverlays() {
    for (var i = 0; i < state.overlays.length; i += 1) {
      try { state.priceChart.removeSeries(state.overlays[i]); } catch (err) { /* 已移除 */ }
    }
    state.overlays = [];
  }

  function clearPriceLines() {
    var candles = state.series.candles;
    if (!candles) return;
    for (var i = 0; i < state.priceLines.length; i += 1) {
      try { candles.removePriceLine(state.priceLines[i]); } catch (err) { /* 已移除 */ }
    }
    state.priceLines = [];
  }

  function addZoneLine(points, color, style) {
    if (!points || points.length < 2) return;
    var line = state.priceChart.addLineSeries({
      color: color,
      lineWidth: 1,
      lineStyle: style,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false
    });
    line.setData(uniqueAscending(points.map(function (p) {
      return { time: p.time, value: p.value };
    })));
    state.overlays.push(line);
  }

  function isoToChartTime(value) {
    var ms = Date.parse(String(value || ""));
    return isFinite(ms) ? Math.floor(ms / 1000) : null;
  }

  function clearManualOverlays() {
    for (var i = 0; i < state.manualOverlays.length; i += 1) {
      try { state.priceChart.removeSeries(state.manualOverlays[i]); } catch (err) { /* 已移除 */ }
    }
    state.manualOverlays = [];
    var candles = state.series.candles;
    if (!candles) {
      state.manualPriceLines = [];
      return;
    }
    for (var j = 0; j < state.manualPriceLines.length; j += 1) {
      try { candles.removePriceLine(state.manualPriceLines[j]); } catch (err) { /* 已移除 */ }
    }
    state.manualPriceLines = [];
  }

  function addManualLine(points, color, style) {
    if (!state.priceChart || !points || points.length < 2) return;
    var line = state.priceChart.addLineSeries({
      color: color,
      lineWidth: 2,
      lineStyle: style,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false
    });
    line.setData(uniqueAscending(points));
    state.manualOverlays.push(line);
  }

  function drawManualAnnotations() {
    if (!state.priceChart || !state.toggles.manual) return;
    clearManualOverlays();
    var swings = {};
    sectionSwings().forEach(function (item) { swings[item.id] = item; });
    var lastTime = null;
    var section = currentSection();
    if (section && section.candles && section.candles.length) {
      lastTime = section.candles[section.candles.length - 1].time;
    }
    var color = "#ce93d8";
    state.annotations.forEach(function (annotation) {
      var payload = annotation.payload || {};
      if (annotation.entity_type === "STATE_INTERVAL") {
      return payload.state + " · " + payload.valid_from + " → " +
        (payload.valid_to || "—") + " · known " + (payload.known_at || "—");
    }
    if (annotation.entity_type === "PROTECTED_POINT") {
      return "Protected" + (payload.direction === "HIGH" ? "High" : "Low") +
        " " + payload.price + " · " + (payload.event_type || "INIT") +
        " · " + payload.valid_from;
    }
    if (annotation.entity_type === "ZONE") {
        var anchorPoints = (payload.anchor_swing_ids || []).map(function (id) {
          return swings[id];
        }).filter(Boolean);
        if (anchorPoints.length < 2) return;
        var startTime = Math.min.apply(null, anchorPoints.map(function (p) { return p.time; }));
        var endTime = Math.max.apply(null, anchorPoints.map(function (p) { return p.time; }));
        if (lastTime !== null && endTime < lastTime) endTime = lastTime;
        var isHuman = payload.annotation_mode === "HUMAN_BOUNDARY";
        var lower = isHuman ? Number(payload.human_lower) : Number(payload.lower);
        var upper = isHuman ? Number(payload.human_upper) : Number(payload.upper);
        var style = isHuman ? LWC.LineStyle.Dotted : LWC.LineStyle.Solid;
        if (isFinite(lower)) {
          addManualLine([{ time: startTime, value: lower }, { time: endTime, value: lower }],
            color, style);
        }
        if (isFinite(upper)) {
          addManualLine([{ time: startTime, value: upper }, { time: endTime, value: upper }],
            color, style);
        }
      } else if (annotation.entity_type === "N_STRUCTURE") {
        var ids = [payload.l1_swing_id, payload.h1_swing_id,
          payload.l2_swing_id, payload.h2_swing_id];
        var points = ids.map(function (id) {
          var point = swings[id];
          return point ? { time: point.time, value: point.price } : null;
        }).filter(Boolean);
        if (points.length === 4) addManualLine(points, "#ba68c8", LWC.LineStyle.Solid);
      } else if (annotation.entity_type === "PROTECTED_POINT") {
        var price = Number(payload.price);
        var candles = state.series.candles;
        if (!candles || !isFinite(price)) return;
        state.manualPriceLines.push(candles.createPriceLine({
          price: price,
          color: color,
          lineWidth: 1,
          lineStyle: LWC.LineStyle.Dotted,
          axisLabelVisible: true,
          title: "M Protected" + (payload.direction === "HIGH" ? "High" : "Low")
        }));
      }
    });
  }

  /* 把叠加层线段裁剪到当前可见时间范围。
   *
   * Zone 线段通常是 [createdAt, updatedAt] 两个端点。若整段都在视野之外，
   * Lightweight Charts 仍会把端点计入价格轴自动缩放，把这些金额贴到左边缘
   * 画线并撑高价格轴。裁剪后与此无关的段直接跳过。 */
  function clipSegment(points, visible) {
    if (!points || points.length < 2) return null;
    var from = points[0], to = points[points.length - 1];
    if (!visible) return { points: [from, to] };
    if (to.time < visible.fromTime || from.time > visible.toTime) return null;
    // 仅一侧越界时，用可见边界处的取值（线性插值）替换该端点。
    var startTime = Math.max(from.time, visible.fromTime);
    var endTime = Math.min(to.time, visible.toTime);
    var value = function (t) {
      if (to.time === from.time) return from.value;
      var ratio = (t - from.time) / (to.time - from.time);
      return from.value + (to.value - from.value) * ratio;
    };
    return {
      points: [
        { time: startTime, value: value(startTime) },
        { time: endTime, value: value(endTime) }
      ]
    };
  }

  function visibleTimeWindow() {
    if (!state.priceChart) return null;
    var candles = sectionCandles();
    var range = state.priceChart.timeScale().getVisibleLogicalRange();
    if (!candles || !candles.length || !range) return null;
    var fromIndex = Math.max(0, Math.floor(range.from));
    var toIndex = Math.min(candles.length - 1, Math.ceil(range.to));
    if (fromIndex > toIndex) return null;
    return { fromTime: candles[fromIndex].time, toTime: candles[toIndex].time };
  }

  function drawZones() {
    if (!state.priceChart) return;
    var zones = currentZones();
    var zoneSeriesCount = state.overlays.length;
    var visible = visibleTimeWindow();

    zones.forEach(function (zone) {
      var closed = zone.status === "BROKEN" || zone.status === "INVALIDATED";
      // 未关闭 Zone：实线边界 + 更亮颜色；终态 Zone：点线 + 低透明度。
      var alpha = closed ? 0.4 : 1.0;
      var color = hexWithAlpha(zone.color, alpha);
      var edgeStyle = closed ? LWC.LineStyle.Dotted : LWC.LineStyle.Solid;
      ["upper", "lower"].forEach(function (edge) {
        var clipped = clipSegment(zone.segments[edge], visible);
        if (clipped) addZoneLine(clipped.points, color, edgeStyle);
      });
      var center = clipSegment(zone.segments.center, visible);
      if (center) {
        addZoneLine(center.points, hexWithAlpha(zone.color, closed ? 0.25 : 0.6),
          LWC.LineStyle.Dashed);
      }
    });
    state.zoneSeriesCount = state.overlays.length - zoneSeriesCount;
  }

  function hexWithAlpha(hex, alpha) {
    var text = String(hex || "#888888").replace("#", "");
    if (text.length !== 6) return hex;
    var r = parseInt(text.slice(0, 2), 16);
    var g = parseInt(text.slice(2, 4), 16);
    var b = parseInt(text.slice(4, 6), 16);
    return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
  }

  function drawStructures() {
    var structures = currentStructures();
    var frame = currentFrame();
    structures.forEach(function (structure) {
      var closed = structure.status === "INVALIDATED" || structure.status === "EXPIRED";
      var color = closed ? COLORS.structureClosed : COLORS.structureActive;
      addZoneLine(structure.points, color, closed ? LWC.LineStyle.Dotted : LWC.LineStyle.Solid);
    });
    if (frame) {
      el.nInvalidationNotice.textContent =
        "N 结构失效判定：" + frame.nStructureInvalidationStatus +
        "（4H/1H 为 RESEARCH_ONLY，不得参与交易性失效）";
    }
  }

  function drawLevelLines() {
    clearPriceLines();
    var candles = state.series.candles;
    var section = currentSection();
    if (!candles || !section) return;
    if (!state.toggles.levels) return;

    (section.levelLines || []).forEach(function (line) {
      state.priceLines.push(candles.createPriceLine({
        price: line.price,
        color: line.color,
        lineWidth: 1,
        lineStyle: LWC.LineStyle.Dashed,
        axisLabelVisible: true,
        title: line.title
      }));
    });
  }

  function drawReversalThreshold() {
    var candles = state.series.candles;
    var frame = currentFrame();
    if (!candles || !frame) return;
    if (frame.zigzagReversalThreshold === null || frame.zigzagReversalThreshold === undefined) return;
    if (!state.toggles.candidate) return;
    state.priceLines.push(candles.createPriceLine({
      price: frame.zigzagReversalThreshold,
      color: COLORS.candidate,
      lineWidth: 1,
      lineStyle: LWC.LineStyle.Dotted,
      axisLabelVisible: true,
      title: "ZigZag 反转阈值"
    }));
  }

  function refreshMarkers() {
    var candles = state.series.candles;
    var section = currentSection();
    if (!candles || !section) return;

    var markers = [];
    if (state.toggles.swing) {
      (section.swingMarkers || []).forEach(function (m) {
        markers.push({
          time: m.time, position: m.position, color: m.color,
          shape: m.shape, text: m.text
        });
      });
    }
    if (state.toggles.candidate) {
      (section.candidateMarkers || []).forEach(function (m) {
        markers.push({
          time: m.time, position: m.position, color: m.color,
          shape: m.shape, text: m.text
        });
      });
    }
    if (state.toggles.manual) {
      state.annotations.forEach(function (annotation) {
        var payload = annotation.payload || {};
        var time = null;
        var position = "aboveBar";
        var text = "";
        if (annotation.entity_type === "SWING_POINT") {
          time = isoToChartTime(payload.occurred_at);
          position = payload.direction === "HIGH" ? "aboveBar" : "belowBar";
          text = "M " + payload.direction.charAt(0) + " " + payload.price;
        } else if (annotation.entity_type === "STATE_INTERVAL") {
          time = isoToChartTime(payload.valid_from);
          position = "belowBar";
          text = "M " + payload.state;
        } else if (annotation.entity_type === "PROTECTED_POINT") {
          time = isoToChartTime(payload.valid_from);
          position = payload.direction === "HIGH" ? "aboveBar" : "belowBar";
          text = "M P" + payload.direction.charAt(0);
        }
        if (time !== null) {
          markers.push({
            time: time, position: position, color: "#ce93d8",
            shape: "circle", text: text
          });
        }
      });
    }
    if (state.pending && state.pending.markers) {
      state.pending.markers.forEach(function (m) {
        markers.push({
          time: m.time, position: m.position, color: COLORS.pending,
          shape: "circle", text: m.text
        });
      });
    }

    markers.sort(function (a, b) { return a.time - b.time; });
    candles.setMarkers(markers);
  }

  function applyToggles() {
    var s = state.series;
    if (!s.candles) return;
    if (s.sma) s.sma.applyOptions({ visible: state.toggles.sma });
    if (s.zigzag) s.zigzag.applyOptions({ visible: state.toggles.zigzag });
    if (s.atr) s.atr.applyOptions({ visible: state.toggles.atr });
    if (el.atrChart) el.atrChart.style.display = state.toggles.atr ? "" : "none";

    // Zone 与 N 结构共用 state.overlays：每次开关变化都整体重绘，
    // 避免出现「Zone 已绘制但 N 结构被跳过」的半更新状态。
    clearOverlays();
    if (state.toggles.zone) drawZones();
    if (state.toggles.structure) drawStructures();
    if (state.toggles.levels) drawLevelLines();
    else clearPriceLines();
    drawReversalThreshold();
    drawManualAnnotations();
    refreshMarkers();
    resizeCharts();
  }

  /* -------------------------------------------------------------- 十字光标 */

  function bindCrosshair(chart, kind) {
    chart.subscribeCrosshairMove(function (param) {
      var s = state.series;
      var section = currentSection();

      if (kind === "atr") {
        if (!param || !param.time) {
          el.legendAtr.textContent = "ATR14 —";
          return;
        }
        var atr = s.atr ? param.seriesData.get(s.atr) : null;
        var parts = [];
        if (atr && typeof atr.value === "number") {
          parts.push("ATR14 " + fmt(atr.value, 3));
          parts.push("as_of " + fmtTime(param.time));
        }
        parts.push("ATR_MA22 N/A / SPEC_AMBIGUITY");
        el.legendAtr.textContent = parts.join("  ·  ");
        return;
      }

      if (!param || !param.time || !s.candles || !section) {
        el.legendOhlc.textContent = "—";
        el.legendInd.textContent = "—";
        el.legendZigzag.textContent = "—";
        return;
      }

      var candle = param.seriesData.get(s.candles);
      var sma = s.sma ? param.seriesData.get(s.sma) : null;
      if (param.point && typeof s.candles.coordinateToPrice === "function") {
        state.lastCrosshairPrice = s.candles.coordinateToPrice(param.point.y);
      }
      var candidate = currentCandidateAt(param.time);
      var bar = barAt(section.candles, param.time);
      state.selectedBar = bar;

      if (candle) {
        el.legendOhlc.textContent =
          state.tf + "  " + fmtTime(param.time) +
          "  O " + fmt(candle.open) + "  H " + fmt(candle.high) +
          "  L " + fmt(candle.low) + "  C " + fmt(candle.close) +
          changeText(section, bar, candle) +
          (bar && bar.isClosed ? "  [完成 Bar]" : "  [FORMING_BAR]");
      }
      var ind = [];
      ind.push(sma && typeof sma.value === "number" ? "SMA22 " + fmt(sma.value) : "SMA22 N/A");
      if (bar) ind.push("as_of " + fmtTime(bar.closeTime));
      ind.push("ATR_MA22 N/A / SPEC_AMBIGUITY");
      el.legendInd.textContent = ind.join("  ·  ");

      if (candidate) {
        el.legendZigzag.textContent =
          "ZigZag " + candidate.direction +
          "  候选 " + fmt(candidate.price) +
          "  冻结ATR " + fmt(candidate.atrSnapshot, 3) +
          "  阈值 " + fmt(candidate.reversalThreshold) +
          "  " + (candidate.status || "");
      } else {
        var frame = currentFrame();
        el.legendZigzag.textContent = "ZigZag " + (frame ? frame.zigzagDirection : "—") + "  无候选";
      }

      updateAtrSnapshotInspector(bar, sma, candle);
    });
  }

  function updateAtrSnapshotInspector(bar, sma, candle) {
    var frame = currentFrame();
    var field = el.atrSnapshotField ? el.atrSnapshotField.value : "";
    var rows = [];
    rows.push(["字段", field]);
    rows.push(["周期", state.tf]);
    rows.push(["来源 Bar", bar ? shortId(bar.barId) : "—"]);
    rows.push(["open_time", bar ? fmtTime(bar.time) : "—"]);
    rows.push(["close_time", bar ? fmtTime(bar.closeTime) : "—"]);
    rows.push(["is_closed", bar && bar.isClosed ? "true" : "false"]);
    rows.push(["ATR14（该 Bar）", frame ? fmt(frame.atr, 3) : "—"]);
    rows.push(["SMA22（该 Bar）", sma && typeof sma.value === "number" ? fmt(sma.value) : "—"]);

    // 该字段在 P1 事件层实现前必然缺失；显示原因而不是 0。
    var reason = state.snapshots[field];
    rows.push(["快照值", reason === undefined ? "未产生该事件" : reason]);
    rows.push(["说明", "Signal/Fill/Stop 事件尚未实现（P1）；不得伪造快照。"]);

    clear(el.atrSnapshot);
    rows.forEach(function (row) {
      el.atrSnapshot.appendChild(makeEl("dt", null, row[0]));
      el.atrSnapshot.appendChild(makeEl("dd", null, row[1]));
    });
  }

  /* -------------------------------------------------------------- 图表点击 */

  function bindChartClick(chart) {
    chart.subscribeClick(function (param) {
      if (!param || !param.time) {
        if (state.tool !== "select") {
          setStatus("请点击 K 线数据区域（当前点击位置没有对应 Bar）");
        }
        return;
      }
      var section = currentSection();
      if (!section) {
        setStatus("当前周期没有可标注的数据");
        return;
      }
      var bar = barAt(section.candles, param.time);
      if (!bar) {
        setStatus("点击位置没有对应 Bar，请点击蜡烛区域");
        return;
      }
      handleChartClick(bar, param);
    });
    // LWC 会把快速双击合并成 dblclick，第二次 click 不再触发。Swing 允许
    // occurrence 与 confirmation 是同一根 Bar，因此这里补一次确认点击。
    chart.subscribeDblClick(function (param) {
      if (state.tool !== "swing" || !param || !param.time) return;
      if (state.pendingClicks.length !== 1) return;
      var section = currentSection();
      var bar = section ? barAt(section.candles, param.time) : null;
      if (!bar || bar.time !== state.pendingClicks[0].occurredBar.time) return;
      handleSwingClick(bar);
    });
  }

  function handleChartClick(bar, param) {
    if (state.tool === "select") {
      state.selectedBar = bar;
      setStatus("已选 Bar " + fmtTime(bar.time) + "（" + state.tf +
        "）；标注请先在「标注工具」中选择 Swing / N 结构 / Zone / 保护点 / 状态区间");
      return;
    }
    if (state.tool === "swing") {
      if (state.pending) {
        setStatus("已有待提交的 SwingPoint；请先点击「保存草稿」或「取消」，再开始下一个");
        return;
      }
      handleSwingClick(bar);
      return;
    }
    if (state.tool === "nstructure" || state.tool === "zone") {
      handleAnchorClick(bar);
      return;
    }
    if (state.tool === "protected") {
      if (state.pending) {
        setStatus("已有待提交的保护点；请先保存或取消");
        return;
      }
      handleProtectedClick(bar);
      return;
    }
    if (state.tool === "state") {
      handleStateIntervalClick(bar);
    }
  }

  function clickDirection(bar) {
    var high = Number(bar.high);
    var low = Number(bar.low);
    var price = state.lastCrosshairPrice;
    if (price === undefined || price === null || !isFinite(price)) return "HIGH";
    return Number(price) >= (high + low) / 2 ? "HIGH" : "LOW";
  }

  function handleProtectedClick(bar) {
    if (state.tf === "15M") {
      setStatus("15M 不允许独立 ProtectedLow；请引用当前有效 NStructure.L2");
      return;
    }
    var direction = clickDirection(bar);
    var price = direction === "HIGH" ? Number(bar.high) : Number(bar.low);
    var eventType = el.protectedEventType.value;
    var validFrom = new Date(bar.time * 1000).toISOString();
    var payload = {
      direction: direction,
      price: price.toFixed(2),
      event_type: eventType,
      valid_from: validFrom,
      source_bar_id: bar.barId,
      annotated_at: new Date().toISOString()
    };
    if (eventType === "INVALIDATE") {
      payload.invalidated_at = validFrom;
      payload.invalidation_reason = "MANUAL_INVALIDATION";
    }
    state.pending = {
      kind: "PROTECTED_POINT",
      payload: payload,
      summary: "Protected" + (direction === "HIGH" ? "High" : "Low") + " " +
        price.toFixed(2) + " · " + eventType + " @ " + fmtTime(bar.time),
      hint: "保护点事件保存为人工标注；15M 独立 ProtectedLow 会被拒绝。",
      markers: [{
        time: bar.time,
        position: direction === "HIGH" ? "aboveBar" : "belowBar",
        text: "待提交 Protected" + (direction === "HIGH" ? "High" : "Low")
      }],
      valid: true
    };
    renderPending();
    refreshMarkers();
  }

  function handleStateIntervalClick(bar) {
    if (!STATE_OPTIONS[state.tf]) {
      setStatus("15M / 3M 没有独立趋势状态，不能标注状态区间");
      return;
    }
    if (state.pendingClicks.length === 0) {
      state.pendingClicks.push({ occurredBar: bar });
      setStatus("已记录状态区间起点 " + fmtTime(bar.time) + "；请点击结束 Bar");
      return;
    }
    var start = state.pendingClicks[0].occurredBar;
    if (bar.time < start.time) {
      setStatus("状态区间结束 Bar 不得早于开始 Bar");
      return;
    }
    var selectedState = el.stateIntervalState.value || state.intervalState;
    if (!selectedState) {
      setStatus("请先选择区间状态");
      return;
    }
    var validFrom = new Date(start.time * 1000).toISOString();
    var validTo = new Date(bar.time * 1000).toISOString();
    var knownAt = new Date((bar.closeTime || bar.time) * 1000).toISOString();
    state.pending = {
      kind: "STATE_INTERVAL",
      payload: {
        state: selectedState,
        valid_from: validFrom,
        valid_to: validTo,
        known_at: knownAt,
        reason_code: selectedState + "_MANUAL",
        annotated_at: new Date().toISOString()
      },
      summary: state.tf + " " + selectedState + " · " + fmtTime(start.time) +
        " → " + fmtTime(bar.time),
      hint: "状态区间保存为 HUMAN_JUDGED 人工标注；known_at 取结束 Bar 的收盘确认时间。",
      markers: [
        { time: start.time, position: "belowBar", text: "状态开始 " + selectedState },
        { time: bar.time, position: "belowBar", text: "状态结束" }
      ],
      valid: true
    };
    state.pendingClicks = [];
    renderPending();
    refreshMarkers();
  }

  function handleSwingClick(bar) {
    var price = state.lastCrosshairPrice;
    if (state.pendingClicks.length === 0) {
      var high = Number(bar.high);
      var low = Number(bar.low);
      // SACW 3.4A：系统默认填入该 Bar 的 High 或 Low，而不是十字光标价格。
      // 点击位置只用于判断用户想标 SwingHigh 还是 SwingLow。
      var midpoint = (high + low) / 2;
      var direction = price !== undefined && price !== null && isFinite(price)
        ? (Number(price) >= midpoint ? "HIGH" : "LOW")
        : "HIGH";
      var defaultPrice = direction === "HIGH" ? high : low;
      state.pendingClicks.push({
        occurredBar: bar,
        price: defaultPrice,
        direction: direction
      });
      setStatus("已记录发生 Bar（默认 " + (direction === "HIGH" ? "High" : "Low") +
        " " + defaultPrice.toFixed(2) + "），请点击确认 Bar");
    } else {
      var first = state.pendingClicks[0];
      if (bar.time < first.occurredBar.time) {
        setStatus("确认 Bar 不得早于发生 Bar");
        return;
      }
      var confirmedIso = new Date(bar.time * 1000).toISOString();
      var occurredIso = new Date(first.occurredBar.time * 1000).toISOString();
      state.pending = {
        kind: "SWING_POINT",
        payload: {
          direction: first.direction,
          price: first.price.toFixed(2),
          occurred_at: occurredIso,
          confirmed_at: confirmedIso,
          confirmation_policy: "HUMAN_JUDGED",
          human_judged_confirmed_at: confirmedIso,
          annotated_at: new Date().toISOString(),
          confirmation_evidence: {
            source: "MANUAL_CLICK",
            workbench: "SACW_V1.1.2",
            price_source: first.direction === "HIGH" ? "BAR_HIGH" : "BAR_LOW"
          },
          source_bar_id: first.occurredBar.barId,
          confirmed_bar_id: bar.barId
        },
        valid: true,
        summary: first.direction + " @ " + first.price.toFixed(2) +
          " 发生 " + fmtTime(first.occurredBar.time) +
          " → 确认 " + fmtTime(bar.time),
        hint: "确认策略 HUMAN_JUDGED：只在人工确认 Bar 之后才可识别，不写入 ALGORITHM_DERIVED。",
        markers: [{
          time: first.occurredBar.time,
          position: first.direction === "HIGH" ? "aboveBar" : "belowBar",
          text: "待提交 " + (first.direction === "HIGH" ? "H" : "L") + " " + first.price.toFixed(2)
        }]
      };
      state.pendingClicks = [];
      renderPending();
      refreshMarkers();
      setStatus("已生成待提交 SwingPoint；确认无误后点击「保存草稿（DRAFT）」。");
    }
  }

  function handleAnchorClick(bar) {
    var frame = currentFrame();
    if (!frame) return;
    var swings = sectionSwings();
    if (!swings.length) {
      setStatus("本周期尚无已确认 SwingPoint，无法选择锚点");
      return;
    }
    // 选择时间上最接近该 Bar 的已确认摆动点。
    var best = null;
    var bestDelta = Infinity;
    swings.forEach(function (point) {
      var delta = Math.abs(point.time - bar.time);
      if (delta < bestDelta) { bestDelta = delta; best = point; }
    });
    if (!best) return;
    var exists = state.pendingClicks.some(function (item) { return item.id === best.id; });
    if (exists) {
      setStatus("该摆动点已在选择列表中");
      return;
    }
    if (state.tool === "zone" && state.pendingClicks.length) {
      if (state.pendingClicks[0].direction !== best.direction) {
        setStatus("Zone 锚点必须同为 SwingHigh 或同为 SwingLow（规格 6.1）");
        return;
      }
    }
    if (state.tool === "nstructure") {
      var verdict = checkNextNStructureAnchor(best);
      if (verdict) {
        setStatus(verdict);
        return;
      }
    }
    state.pendingClicks.push(best);
    updateAnchorPending();
  }

  function sectionSwings() {
    var section = currentSection();
    if (!section || !section.swingMarkers) return [];
    return section.swingMarkers.map(function (marker) {
      var text = String(marker.text || "");
      // 只有最近几个摆动点带价格文本；方向与价格必须优先读载荷字段，
      // 否则早期标记会被误判为 SwingLow（N 结构无法按 L1→H1→L2→H2 选择）。
      var direction = marker.direction || (text.charAt(0) === "H" ? "HIGH" : "LOW");
      var price = marker.price !== undefined && marker.price !== null
        ? Number(marker.price)
        : Number(text.split(" ").pop());
      return {
        id: marker.swingId,
        time: marker.time,
        price: price,
        direction: direction,
        confirmedTime: marker.confirmedTime
      };
    });
  }

  function renderAnnotationToolControls() {
    if (el.nStructureStatusBox) {
      el.nStructureStatusBox.className = state.tool === "nstructure"
        ? "field inline" : "field inline hidden";
    }
    if (el.protectedEventBox) {
      el.protectedEventBox.className = state.tool === "protected"
        ? "field inline" : "field inline hidden";
    }
    if (!el.stateIntervalBox) return;
    var options = STATE_OPTIONS[state.tf] || [];
    var active = state.tool === "state" && options.length > 0;
    el.stateIntervalBox.className = active ? "field inline" : "field inline hidden";
    if (!active) return;
    var current = el.stateIntervalState.value || state.intervalState;
    el.stateIntervalState.textContent = "";
    options.forEach(function (name) {
      var option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      el.stateIntervalState.appendChild(option);
    });
    if (options.indexOf(current) < 0) current = options[0];
    state.intervalState = current;
    el.stateIntervalState.value = current;
  }

  function renderAnchorPicker() {
    renderZoneModeControls();
    renderAnnotationToolControls();
    var needsAnchors = state.tool === "zone" || state.tool === "nstructure";
    if (!needsAnchors) {
      el.anchorPicker.className = "anchor-picker hidden";
      return;
    }
    el.anchorPicker.className = "anchor-picker";
    clear(el.anchorChips);
    var swings = sectionSwings();
    if (!swings.length) {
      el.anchorChips.appendChild(makeEl("span", "hint", "本周期暂无已确认摆动点。"));
      return;
    }
    var selectedIds = state.pendingClicks.map(function (item) { return item.id; });
    swings.slice(-40).forEach(function (item) {
      var position = selectedIds.indexOf(item.id);
      var chip = makeEl("button", position >= 0 ? "selected" : "",
        (item.direction === "HIGH" ? "H" : "L") + " " + fmt(item.price) +
        (position >= 0 ? " #" + (position + 1) : ""));
      chip.dataset.direction = item.direction;
      chip.dataset.swingId = item.id;
      chip.addEventListener("click", function () {
        toggleAnchor(item);
      });
      el.anchorChips.appendChild(chip);
    });
  }

  /* Zone 模式属于人工标注本身：ANCHOR_ONLY 只记录锚点，HUMAN_BOUNDARY 记录
   * 人工边界；两者都不能由程序输出反向覆盖。 */
  function renderZoneModeControls() {
    if (!el.zoneModeBox) return;
    if (state.tool !== "zone") {
      el.zoneModeBox.className = "zone-box hidden";
      return;
    }
    el.zoneModeBox.className = "zone-box";
    el.zoneMode.value = state.zoneMode;
    el.zoneHumanFields.className = state.zoneMode === "HUMAN_BOUNDARY"
      ? "zone-human-fields" : "zone-human-fields hidden";
  }

  function zoneHumanBoundary() {
    var lowerRaw = String(el.zoneHumanLower.value || "").trim();
    var upperRaw = String(el.zoneHumanUpper.value || "").trim();
    var centerRaw = String(el.zoneHumanCenter.value || "").trim();
    var lower = lowerRaw === "" ? NaN : Number(lowerRaw);
    var upper = upperRaw === "" ? NaN : Number(upperRaw);
    var center = centerRaw === ""
      ? (isFinite(lower) && isFinite(upper) ? (lower + upper) / 2 : NaN)
      : Number(centerRaw);
    return {
      lower: lower,
      upper: upper,
      center: center,
      valid: isFinite(lower) && isFinite(upper) && isFinite(center) &&
        lower < upper && center >= lower && center <= upper
    };
  }

  function toggleAnchor(item) {
    var index = -1;
    for (var i = 0; i < state.pendingClicks.length; i += 1) {
      if (state.pendingClicks[i].id === item.id) { index = i; break; }
    }
    if (index >= 0) {
      state.pendingClicks.splice(index, 1);
    } else {
      if (state.tool === "zone" && state.pendingClicks.length) {
        var first = state.pendingClicks[0];
        if (first.direction !== item.direction) {
          setStatus("Zone 锚点必须同为 SwingHigh 或同为 SwingLow（规格 6.1）");
          return;
        }
      }
      if (state.tool === "nstructure") {
        var verdict = checkNextNStructureAnchor(item);
        if (verdict) {
          setStatus(verdict);
          return;
        }
      }
      state.pendingClicks.push(item);
    }
    updateAnchorPending();
  }

  /* N 结构锚点只能按 L1 → H1 → L2 → H2 依次选择（规格 5.5）。 */
  var N_STRUCTURE_SEQUENCE = ["LOW", "HIGH", "LOW", "HIGH"];
  var N_STRUCTURE_LABELS = ["L1", "H1", "L2", "H2"];

  function checkNextNStructureAnchor(item) {
    var index = state.pendingClicks.length;
    if (index >= 4) return "N 结构最多四个锚点（L1 → H1 → L2 → H2）";
    var expected = N_STRUCTURE_SEQUENCE[index];
    if (item.direction !== expected) {
      return "第 " + (index + 1) + " 个锚点必须是 " + N_STRUCTURE_LABELS[index] +
        "（" + (expected === "LOW" ? "SwingLow" : "SwingHigh") + "）";
    }
    if (index > 0) {
      var previous = state.pendingClicks[index - 1];
      if (item.time <= previous.time) {
        return "锚点时间必须严格递增：当前锚点早于 " + N_STRUCTURE_LABELS[index - 1];
      }
    }
    return null;
  }

  function updateAnchorPending() {
    var tool = state.tool;
    var selected = state.pendingClicks;
    if (!selected.length) {
      state.pending = null;
      renderPending();
      refreshMarkers();
      return;
    }
    var markers = selected.map(function (item) {
      return {
        time: item.time,
        position: item.direction === "HIGH" ? "aboveBar" : "belowBar",
        text: "锚点 " + (item.direction === "HIGH" ? "H" : "L")
      };
    });
    if (tool === "zone") {
      var zoneMode = state.zoneMode;
      var payload = {
        annotation_mode: zoneMode,
        anchor_swing_ids: selected.map(function (item) { return item.id; })
      };
      var boundary = null;
      var boundaryProblem = null;
      if (zoneMode === "HUMAN_BOUNDARY") {
        boundary = zoneHumanBoundary();
        if (!boundary.valid) {
          boundaryProblem = "HUMAN_BOUNDARY 需要 Lower < Upper，且 Center 位于区间内";
        } else {
          payload.human_lower = String(boundary.lower);
          payload.human_upper = String(boundary.upper);
          payload.human_center = String(boundary.center);
        }
      }
      var zoneValid = selected.length >= 2 && !boundaryProblem;
      state.pending = {
        kind: "ZONE",
        payload: payload,
        summary: "Zone（" + zoneMode + "）锚点 " + selected.length + " 个：" +
          selected.map(function (item) { return item.direction + "@" + fmt(item.price); }).join(", "),
        markers: markers,
        valid: zoneValid,
        hint: boundaryProblem || (selected.length < 2
          ? "至少需要 2 个锚点"
          : zoneMode === "ANCHOR_ONLY"
            ? "边界将由后端按 V1.4.8 公式计算，程序边界与人工标注分开保存"
            : "人工边界与程序边界分别保存；HUMAN_BOUNDARY 不进入 ANCHOR_ONLY 主准确率")
      };
    } else {
      var nConfirmed = selected.length === 4 && selected[3].confirmedTime
        ? new Date(selected[3].confirmedTime * 1000).toISOString()
        : null;
      state.pending = {
        kind: "N_STRUCTURE",
        payload: {
          direction: "BULLISH",
          l1_swing_id: selected[0] ? selected[0].id : null,
          h1_swing_id: selected[1] ? selected[1].id : null,
          l2_swing_id: selected[2] ? selected[2].id : null,
          h2_swing_id: selected[3] ? selected[3].id : null,
          valid_from: nConfirmed,
          confirmed_at: nConfirmed,
          validation_status: "VALID",
          status: el.nStructureStatus.value,
          invalidated_at: null,
          invalidation_status: "SPEC_AMBIGUITY",
          annotated_at: new Date().toISOString()
        },
        summary: "N 结构锚点：" + selected.map(function (item, index) {
          return N_STRUCTURE_LABELS[index] + " " + item.direction.charAt(0) + "@" + fmt(item.price);
        }).join(" → "),
        markers: markers,
        valid: selected.length === 4,
        hint: selected.length === 4
          ? "需满足 L1→H1→L2→H2 顺序、L2>L1、H2>H1；失效 ATR 时点未定义，标记 SPEC_AMBIGUITY"
          : "需要依次选择 L1、H1、L2、H2 四个摆动点"
      };
    }
    renderPending();
    renderAnchorPicker();
    refreshMarkers();
  }

  /* -------------------------------------------------------------- 待提交面板 */

  function renderPending() {
    clear(el.pendingAnnotation);
    if (!state.pending) {
      el.pendingAnnotation.className = "pending hidden";
      return;
    }
    el.pendingAnnotation.className = "pending";
    var incomplete = state.pending.valid === false;
    el.pendingAnnotation.appendChild(
      makeEl("div", "row", state.pending.kind + (incomplete ? "（未完成）" : ""))
    );
    el.pendingAnnotation.appendChild(makeEl("div", "mono", state.pending.summary));
    if (state.pending.hint) {
      el.pendingAnnotation.appendChild(makeEl("div", "hint", state.pending.hint));
    }
    var ops = makeEl("div", "ops");
    var submit = makeEl("button", null, "保存草稿（DRAFT）");
    submit.disabled = state.pending.valid === false;
    submit.addEventListener("click", submitPending);
    var cancel = makeEl("button", "ghost", "取消");
    cancel.addEventListener("click", function () {
      state.pending = null;
      state.pendingClicks = [];
      renderPending();
      renderAnchorPicker();
      refreshMarkers();
      setStatus("已取消当前待提交标注", el.annotationStatus);
    });
    ops.appendChild(submit);
    ops.appendChild(cancel);
    el.pendingAnnotation.appendChild(ops);
  }

  function validateNStructure(payload) {
    var swings = sectionSwings();
    var lookup = {};
    swings.forEach(function (item) { lookup[item.id] = item; });
    var ids = [payload.l1_swing_id, payload.h1_swing_id, payload.l2_swing_id, payload.h2_swing_id];
    var points = ids.map(function (id) { return lookup[id]; });
    if (points.some(function (p) { return !p; })) return "锚点不存在";
    var order = points[0].time < points[1].time && points[1].time < points[2].time &&
      points[2].time < points[3].time;
    if (!order) return "必须满足 L1 → H1 → L2 → H2 的时间顺序";
    if (!(points[2].price > points[0].price)) return "必须满足 L2 > L1";
    if (!(points[3].price > points[1].price)) return "必须满足 H2 > H1";
    return null;
  }

  function submitPending() {
    if (!state.pending) return;
    var kind = state.pending.kind;
    var payload = Object.assign({}, state.pending.payload);

    if (kind === "N_STRUCTURE") {
      var problem = validateNStructure(payload);
      if (problem) {
        setStatus("N 结构校验失败：" + problem, el.annotationStatus);
        return;
      }
      payload.confirmed_at = new Date(
        sectionSwings().filter(function (item) { return item.id === payload.h2_swing_id; })[0]
          .confirmedTime * 1000
      ).toISOString();
      payload.valid_from = payload.confirmed_at;
    }

    setStatus("提交中…", el.annotationStatus);
    api("/api/v1/annotation-projects/" + state.project.project_id + "/annotations", {
      method: "POST",
      body: {
        entity_type: kind,
        timeframe: state.tf,
        payload: payload,
        actor: "web",
        label_source: "HUMAN_PRIMARY",
        status: "DRAFT"
      }
    }).then(function (annotation) {
      state.pending = null;
      state.pendingClicks = [];
      state.savedCount += 1;
      renderPending();
      renderAnchorPicker();
      refreshMarkers();
      var message = "已保存为 DRAFT · " + shortId(annotation.annotation_id) +
        "（本次会话 " + state.savedCount + " 条）";
      setStatus(state.continuous ? message + "，可继续标注下一个" : message,
        el.annotationStatus);
      if (!state.continuous) {
        var selectButton = document.querySelector('.tool[data-tool="select"]');
        if (selectButton) selectButton.click();
      }
      loadAnnotations();
      loadProjectSummary();
      loadAudit();
    }).catch(function (error) {
      setStatus("保存失败：" + error.message, el.annotationStatus);
    });
  }

  /* -------------------------------------------------------------- 标注列表 */

  function loadAnnotations() {
    if (!state.project) return Promise.resolve();
    return api("/api/v1/annotation-projects/" + state.project.project_id +
      "/annotations?timeframe=" + encodeURIComponent(state.tf))
      .then(function (data) {
        state.annotations = data.annotations || [];
        renderAnnotations();
        drawManualAnnotations();
        refreshMarkers();
      })
      .catch(function (error) {
        setStatus("标注加载失败：" + error.message, el.annotationStatus);
      });
  }

  function loadProjectSummary() {
    if (!state.project) return Promise.resolve();
    return api("/api/v1/annotation-projects/" + state.project.project_id + "/annotations")
      .then(function (data) {
        state.projectAnnotations = data.annotations || [];
        renderProjectSummary();
      })
      .catch(function (error) {
        setStatus("标注汇总加载失败：" + error.message, el.annotationStatus);
      });
  }

  function renderProjectSummary() {
    var counts = {};
    state.projectAnnotations.forEach(function (item) {
      counts[item.status] = (counts[item.status] || 0) + 1;
    });
    var groundTruth = (counts.APPROVED || 0) + (counts.FROZEN || 0);
    state.groundTruthCount = groundTruth;
    var names = ["DRAFT", "SUBMITTED", "REVIEWED", "APPROVED", "FROZEN",
      "REJECTED", "AMBIGUOUS"];
    var parts = names
      .filter(function (name) { return counts[name]; })
      .map(function (name) { return name + " " + counts[name]; });
    if (el.annotationSummary) {
      el.annotationSummary.textContent = "项目标注：" +
        (parts.length ? parts.join(" · ") : "尚无标注") +
        " · 可冻结 " + groundTruth;
    }
    var canFreeze = groundTruth > 0;
    [el.freezeGolden, el.freezeGolden2].forEach(function (button) {
      if (!button) return;
      button.disabled = !canFreeze;
      button.title = canFreeze
        ? "把 APPROVED/FROZEN 标注冻结为黄金样本"
        : "先保存草稿，并在标注列表中逐条提交审核、审核通过、批准，才能冻结";
    });
  }

  function payloadSummary(annotation) {
    var payload = annotation.payload || {};
    if (annotation.entity_type === "SWING_POINT") {
      return payload.direction + " " + payload.price + " · " + payload.occurred_at +
        " → " + payload.confirmed_at +
        " · " + (payload.confirmation_policy || "HUMAN_JUDGED");
    }
    if (annotation.entity_type === "N_STRUCTURE") {
      return "L1 " + shortId(payload.l1_swing_id) + " · H1 " + shortId(payload.h1_swing_id) +
        " · L2 " + shortId(payload.l2_swing_id) + " · H2 " + shortId(payload.h2_swing_id) +
        " · 失效 " + (payload.invalidation_status || "SPEC_AMBIGUITY");
    }
    if (annotation.entity_type === "STATE_INTERVAL") {
      return payload.state + " · " + payload.valid_from + " → " +
        (payload.valid_to || "—") + " · known " + (payload.known_at || "—");
    }
    if (annotation.entity_type === "PROTECTED_POINT") {
      return "Protected" + (payload.direction === "HIGH" ? "High" : "Low") +
        " " + payload.price + " · " + (payload.event_type || "INIT") +
        " · " + payload.valid_from;
    }
    if (annotation.entity_type === "ZONE") {
      var mode = payload.annotation_mode || "";
      var bounds = mode === "HUMAN_BOUNDARY"
        ? [payload.human_lower, payload.human_upper]
        : [payload.lower, payload.upper];
      return payload.zone_type + " · 锚点 " + (payload.anchor_swing_ids || []).length +
        " · [" + bounds[0] + ", " + bounds[1] + "]" +
        " · " + mode;
    }
    return JSON.stringify(payload).slice(0, 90);
  }

  function renderAnnotations() {
    clear(el.annotationList);
    if (!state.annotations.length) {
      el.annotationList.appendChild(makeEl("li", "empty", "本周期暂无标注。"));
      return;
    }
    state.annotations.slice().reverse().forEach(function (annotation) {
      var li = makeEl("li");
      var row = makeEl("div", "row");
      row.appendChild(makeEl("span", "mono", annotation.entity_type + " " + shortId(annotation.annotation_id)));
      row.appendChild(makeEl("span", "status-" + annotation.status, annotation.status));
      li.appendChild(row);

      li.appendChild(makeEl("div", "mono", payloadSummary(annotation)));

      var meta = makeEl("div", "row");
      meta.appendChild(makeEl("span", "badge-source", annotation.label_source));
      meta.appendChild(makeEl("span", "badge-source", "rev " + annotation.revision));
      meta.appendChild(makeEl("span", "badge-source", "v" + annotation.annotation_rule_version));
      var payload = annotation.payload || {};
      if (annotation.entity_type === "SWING_POINT") {
        meta.appendChild(makeEl("span", "badge-source",
          payload.confirmation_policy || "HUMAN_JUDGED"));
      }
      if (annotation.entity_type === "STATE_INTERVAL") {
      return payload.state + " · " + payload.valid_from + " → " +
        (payload.valid_to || "—") + " · known " + (payload.known_at || "—");
    }
    if (annotation.entity_type === "PROTECTED_POINT") {
      return "Protected" + (payload.direction === "HIGH" ? "High" : "Low") +
        " " + payload.price + " · " + (payload.event_type || "INIT") +
        " · " + payload.valid_from;
    }
    if (annotation.entity_type === "ZONE") {
        meta.appendChild(makeEl("span", "badge-source",
          payload.annotation_mode || "ANCHOR_ONLY"));
      }
      if (annotation.entity_type === "N_STRUCTURE") {
        meta.appendChild(makeEl("span", "badge-source",
          payload.invalidation_status || "SPEC_AMBIGUITY"));
      }
      li.appendChild(meta);

      var actions = makeEl("div", "actions");
      (STATUS_FLOW[annotation.status] || []).forEach(function (transition) {
        var button = makeEl("button", null, transition[1]);
        button.addEventListener("click", function () {
          changeStatus(annotation.annotation_id, transition[0]);
        });
        actions.appendChild(button);
      });
      var revisions = makeEl("button", "ghost", "修订历史");
      revisions.addEventListener("click", function () {
        showRevisions(annotation.annotation_id);
      });
      actions.appendChild(revisions);
      if (annotation.status !== "FROZEN") {
        var remove = makeEl("button", "ghost", "删除");
        remove.addEventListener("click", function () {
          deleteAnnotation(annotation.annotation_id);
        });
        actions.appendChild(remove);
      }
      li.appendChild(actions);

      el.annotationList.appendChild(li);
    });
  }

  function changeStatus(annotationId, status) {
    api("/api/v1/annotations/" + annotationId + "/status", {
      method: "POST",
      body: { status: status, actor: "web", reason: "workbench transition" }
    }).then(function (updated) {
      setStatus("状态已更新为 " + updated.status, el.annotationStatus);
      loadAnnotations();
      loadProjectSummary();
      loadAudit();
    }).catch(function (error) {
      setStatus("状态更新失败：" + error.message, el.annotationStatus);
    });
  }

  function deleteAnnotation(annotationId) {
    if (!window.confirm("确认删除该标注？软删除后仍可在审计日志中追溯。")) return;
    api("/api/v1/annotations/" + annotationId, {
      method: "DELETE",
      body: { actor: "web", reason: "deleted from workbench" }
    }).then(function () {
      setStatus("已删除标注 " + shortId(annotationId), el.annotationStatus);
      loadAnnotations();
      loadProjectSummary();
      loadAudit();
    }).catch(function (error) {
      setStatus("删除失败：" + error.message, el.annotationStatus);
    });
  }

  function showRevisions(annotationId) {
    api("/api/v1/annotations/" + annotationId + "/revisions").then(function (data) {
      var list = data.revisions || [];
      setStatus("修订 " + list.length + " 条：" + list.map(function (item) {
        return "r" + item.revision + "/" + item.status;
      }).join(" "), el.annotationStatus);
    }).catch(function (error) {
      setStatus("修订读取失败：" + error.message, el.annotationStatus);
    });
  }

  function updateComparisonControls() {
    var hasGolden = state.goldenDatasets.length > 0;
    [el.compareSwings, el.compareZones, el.compareNStructures,
      el.compareStateIntervals].forEach(function (button) {
      if (button) button.disabled = !hasGolden;
    });
    if (!hasGolden && el.comparisonStatus) {
      el.comparisonStatus.textContent = "尚未冻结黄金样本；DRAFT 标注不参与程序比较。";
    } else if (hasGolden && el.comparisonStatus &&
        el.comparisonStatus.textContent.indexOf("尚未冻结") >= 0) {
      el.comparisonStatus.textContent = "黄金样本已就绪，可运行 Ground Truth 差异比较。";
    }
  }

  function runComparison(entity) {
    if (!state.project) return;
    var golden = state.goldenDatasets[state.goldenDatasets.length - 1];
    if (!golden) {
      setStatus("需先冻结黄金样本，才能运行程序回放差异比较", el.comparisonStatus);
      return;
    }
    setStatus("运行 V1.4.8 程序回放差异比较…", el.comparisonStatus);
    var path = "/api/v1/annotation-projects/" + state.project.project_id +
      "/comparisons/" + entity + "?timeframe=" + encodeURIComponent(state.tf) +
      "&golden_dataset_id=" + encodeURIComponent(golden.golden_dataset_id);
    api(path, { method: "POST" }).then(function (report) {
      var items = report.results || report.matches || [];
      var counts = {};
      items.forEach(function (item) {
        var key = item.match || item.match_type || "UNKNOWN";
        counts[key] = (counts[key] || 0) + 1;
      });
      el.comparisonStatus.textContent =
        "Ground Truth " + (report.groundTruthCount || report.human_count || 0) +
        " 条 · 程序 " + (report.program_count || 0) +
        " · MATCHED " + (counts.MATCHED || 0) +
        " · HUMAN_ONLY " + (counts.HUMAN_ONLY || 0) +
        " · PROGRAM_ONLY " + (counts.PROGRAM_ONLY || 0) +
        " · AMBIGUOUS " + (counts.AMBIGUOUS_MATCH || counts.AMBIGUOUS || 0) +
        " · EXACT " + (counts.EXACT_MATCH || 0) +
        " · TIME_MISMATCH " + (counts.CONFIRMATION_TIME_MISMATCH || 0) +
        " · STATUS_MISMATCH " + (counts.STATUS_MISMATCH || 0) +
        " · " + state.tf;
      el.comparisonOutput.textContent = JSON.stringify({
        golden_dataset_id: report.goldenDatasetId,
        replay_run_id: report.replayRunId,
        config_hash: report.configHash,
        dataset_hash: report.datasetHash,
        ground_truth_count: report.groundTruthCount,
        included_statuses: report.includedStatuses,
        matcher_version: report.matcher_version,
        human_count: report.human_count,
        program_count: report.program_count,
        counts: counts,
        note: report.note,
        detail: items
      }, null, 2);
    }).catch(function (error) {
      setStatus("差异比较失败：" + error.message, el.comparisonStatus);
    });
  }

  /* -------------------------------------------------------------- 面板渲染 */

  function renderTimeframeButtons() {
    clear(el.timeframeButtons);
    var frames = (state.payload && state.payload.timeframes) || [];
    frames.forEach(function (frame) {
      var button = makeEl("button", frame.code === state.tf ? "active" : "");
      button.appendChild(makeEl("span", null, frame.label + " (" + frame.code + ")"));
      button.appendChild(makeEl("span", "tf-state " + stateClass(frame.state), frame.state || "—"));
      button.addEventListener("click", function () {
        if (state.tf === frame.code) return;
        selectTimeframe(frame.code);
      });
      el.timeframeButtons.appendChild(button);
    });
  }

  function renderStates() {
    clear(el.stateRows);
    var frames = (state.payload && state.payload.timeframes) || [];
    frames.forEach(function (frame) {
      var tr = makeEl("tr", frame.code === state.tf ? "current" : "");
      tr.appendChild(makeEl("td", null, frame.code));
      tr.appendChild(makeEl("td", "state " + stateClass(frame.state), frame.state || "—"));
      tr.appendChild(makeEl("td", "zdir",
        frame.zigzagDirection === "SEEK_HIGH" ? "↑ 找高"
          : frame.zigzagDirection === "SEEK_LOW" ? "↓ 找低" : "UNKNOWN"));
      tr.appendChild(makeEl("td", null, frame.bars ? frame.swings + " (" +
        frame.swingHighs + "/" + frame.swingLows + ")" : "—"));
      tr.appendChild(makeEl("td", null, frame.bars ? frame.structures + " / 活 " +
        frame.activeStructures : "—"));
      tr.appendChild(makeEl("td", null, frame.bars ? frame.openZones + " / " + frame.zones : "—"));
      el.stateRows.appendChild(tr);
    });
  }

  function renderLevels() {
    var frame = currentFrame();
    clear(el.levels);
    if (!frame) return;
    var rows = [
      ["周期", frame.label + " (" + frame.code + ")"],
      ["状态", frame.state || "—"],
      ["K 线根数", frame.bars],
      ["指标预热", frame.warm ? "完成" : "未完成"],
      ["收盘", fmt(frame.close)],
      ["SMA22", fmt(frame.sma)],
      ["ATR14", fmt(frame.atr, 3)],
      ["ATR_MA22", frame.atrMaStatus || "N/A / SPEC_AMBIGUITY"],
      ["ZigZag 方向", frame.zigzagDirection || "UNKNOWN"],
      ["候选价", fmt(frame.zigzagCandidatePrice)],
      ["候选冻结 ATR", fmt(frame.zigzagCandidateAtr, 3)],
      ["反转阈值", fmt(frame.zigzagReversalThreshold)],
      ["ProtectedLow", fmt(frame.protectedLow)],
      ["ProtectedHigh", fmt(frame.protectedHigh)],
      ["PullbackOrigin", fmt(frame.pullbackOriginHigh)],
      ["N 结构失效", frame.nStructureInvalidationStatus || "SPEC_AMBIGUITY"]
    ];
    rows.forEach(function (row) {
      el.levels.appendChild(makeEl("dt", null, row[0]));
      el.levels.appendChild(makeEl("dd", null, row[1] === undefined ? "—" : String(row[1])));
    });
  }

  function renderZones() {
    clear(el.zoneList);
    var zones = currentZones();
    if (!zones.length) {
      el.zoneList.appendChild(makeEl("li", "empty", "本周期未形成 Zone。"));
      return;
    }
    zones.slice().reverse().forEach(function (zone) {
      var li = makeEl("li");
      var row = makeEl("div", "row");
      row.appendChild(makeEl("span", "mono", shortId(zone.id)));
      row.appendChild(makeEl("span", "status-" + zone.status, zone.status));
      li.appendChild(row);

      var row2 = makeEl("div", "row mono");
      row2.appendChild(makeEl("span", null, zone.zoneType));
      row2.appendChild(makeEl("span", null,
        "锚点 " + zone.anchorCount + " · v" + zone.version + " · 测试 " + zone.testCount));
      li.appendChild(row2);

      var row3 = makeEl("div", "row mono");
      row3.appendChild(makeEl("span", null, "[" + fmt(zone.lower) + ", " + fmt(zone.upper) + "]"));
      row3.appendChild(makeEl("span", null, "中心 " + fmt(zone.center)));
      li.appendChild(row3);

      var row4 = makeEl("div", "row mono");
      row4.appendChild(makeEl("span", null, "半宽 " + fmt(zone.halfWidth, 3)));
      row4.appendChild(makeEl("span", null, "决定性项 " + zone.basis));
      li.appendChild(row4);

      el.zoneList.appendChild(li);
    });
  }

  function renderStructures() {
    clear(el.structureList);
    var structures = currentStructures();
    if (!structures.length) {
      el.structureList.appendChild(makeEl("li", "empty", "本周期未识别到 N 结构。"));
      return;
    }
    structures.slice().reverse().forEach(function (structure) {
      var li = makeEl("li");
      var row = makeEl("div", "row");
      row.appendChild(makeEl("span", "mono", shortId(structure.id)));
      row.appendChild(makeEl("span", "status-" + structure.status, structure.status));
      li.appendChild(row);

      var row2 = makeEl("div", "row mono");
      row2.appendChild(makeEl("span", null,
        "回撤 " + fmt(structure.retracement, 3) + " · " + structure.retracementClass));
      row2.appendChild(makeEl("span", null, "失效 " + structure.invalidationStatus));
      li.appendChild(row2);

      var row3 = makeEl("div", "row mono");
      row3.appendChild(makeEl("span", null, "H2 " + fmt(structure.breakoutPrice)));
      row3.appendChild(makeEl("span", null, "L2 " + fmt(structure.structuralStop)));
      li.appendChild(row3);

      el.structureList.appendChild(li);
    });
  }

  function renderMarket() {
    var market = (state.payload && state.payload.market) || {};
    el.canOpen.textContent = "CanOpen " + (market.canOpen ? "TRUE" : "FALSE");
    el.canOpen.className = "pill " + (market.canOpen ? "pill-on" : "pill-off");
    el.canHold.textContent = "CanHold " + (market.canHold ? "TRUE" : "FALSE");
    el.canHold.className = "pill " + (market.canHold ? "pill-on" : "pill-off");
    el.macroSummary.textContent =
      "1M " + (market.month || "—") +
      " · 1W " + (market.week || "—") +
      " · 1D " + (market.day || "—") +
      " · 4H " + (market.h4 || "—") +
      " · 1H " + (market.h1 || "—");
  }

  function selectTimeframe(code) {
    state.tf = code;
    state.pending = null;
    state.pendingClicks = [];
    // 切换周期重新加载整页视图后，向左加载的历史状态从零开始。
    state.history.exhausted[code] = false;
    state.history.loadedLeft[code] = 0;
    renderPending();
    renderAnchorPicker();
    renderTimeframeButtons();
    renderStates();
    renderLevels();
    renderZones();
    renderStructures();
    buildCharts();
    loadAnnotations();
    if (el.comparisonStatus) {
      el.comparisonOutput.textContent = "—";
      el.comparisonStatus.textContent = state.goldenDatasets.length
        ? "已切换周期；可重新运行 Ground Truth 差异比较。"
        : "尚未冻结黄金样本；DRAFT 标注不参与程序比较。";
      updateComparisonControls();
    }
    var frame = currentFrame();
    if (frame) {
      setStatus(frame.code + " · 状态 " + (frame.state || "—") +
        " · K 线 " + frame.bars + " · 摆动 " + frame.swings +
        " · N 结构 " + frame.structures + " · Zone " + frame.zones);
    }
  }

  /* -------------------------------------------------------------- 实时刷新 */

  /* 采集器与工作台是独立进程：采集器持续把已收盘 K 线写入 Parquet，服务端
   * 在本接口里检测变化并重建视图。前端按 refreshIntervalSecs 轮询，只追加新增
   * K 线与指标点；叠加层（摆动点 / N 结构 / Zone / 状态）整体替换。 */

  function liveCursor(payload) {
    var series = (payload && payload.series) || {};
    var since = null;
    Object.keys(series).forEach(function (code) {
      var candles = (series[code] && series[code].candles) || [];
      var last = candles.length ? candles[candles.length - 1] : null;
      if (!last || typeof last.closeTime !== "number") return;
      if (since === null || last.closeTime > since) since = last.closeTime;
    });
    return since;
  }

  function updateLiveStatus(extra) {
    if (!el.liveStatus) return;
    if (!state.live.enabled) {
      el.liveStatus.textContent = "实时刷新已暂停";
      el.liveStatus.className = "live paused";
      return;
    }
    if (state.live.error) {
      el.liveStatus.textContent = "实时刷新失败：" + state.live.error;
      el.liveStatus.className = "live error";
      return;
    }
    var info = state.live.info;
    var parts = ["实时"];
    if (state.live.appliedAt) {
      parts.push("上次更新 " + new Date(state.live.appliedAt).toISOString().slice(11, 19) + "Z");
    } else {
      parts.push("等待新数据");
    }
    if (extra) parts.push(extra);
    if (info && typeof info.refreshIntervalSecs === "number") {
      parts.push("每 " + info.refreshIntervalSecs + " 秒");
    }
    el.liveStatus.textContent = parts.join(" · ");
    el.liveStatus.className = "live ok";
    el.liveStatus.title = "逐周期自服务端读取新落盘的已收盘 K 线；点击暂停或恢复";
  }

  function bindLiveToggle() {
    if (!el.liveStatus) return;
    el.liveStatus.addEventListener("click", function () {
      state.live.enabled = !state.live.enabled;
      if (state.live.enabled) {
        pollLive();
      }
      updateLiveStatus();
    });
  }

  function scheduleLive(options) {
    if (state.live.timer) clearTimeout(state.live.timer);
    state.live.timer = null;
    if (!state.live.enabled) return;
    var intervalMs = (options && options.interval) || 5000;
    state.live.timer = setTimeout(pollLive, intervalMs);
  }

  function pollLive() {
    if (state.live.busy) return;
    if (!state.payload) return;
    if (!state.live.enabled) {
      updateLiveStatus();
      return;
    }
    state.live.busy = true;
    var since = state.live.since !== null ? state.live.since : liveCursor(state.payload);
    var url = "/api/v1/market/live" +
      (since !== null ? "?since_close_ns=" + encodeURIComponent(since) : "");
    api(url).then(function (data) {
      state.live.busy = false;
      state.live.error = null;
      state.live.info = data;
      if (data.changed) {
        applyLive(data);
      }
      scheduleLive({ interval: (data.refreshIntervalSecs || 5) * 1000 });
    }).catch(function (error) {
      state.live.busy = false;
      state.live.error = error.message;
      updateLiveStatus();
      scheduleLive({ interval: 15000 });
    });
  }

  function applyLive(data) {
    var needsReload = (data.timeframes || []).some(function (item) {
      return item.reload || item.bars.length > (data.maxLiveBars || 500);
    });
    if (needsReload) {
      state.live.appliedAt = Date.now();
      loadPayload({ keepSelection: true }).then(function () {
        state.live.since = liveCursor(state.payload);
        loadAnnotations();
        updateLiveStatus("整页重载（新增超过 " + (data.maxLiveBars || 500) + " 根）");
      });
      return;
    }

    var added = 0;
    (data.timeframes || []).forEach(function (item) {
      if (!item.changed) return;
      mergeLiveSection(item.timeframe, item.bars, item.series);
      added += item.added || item.bars.length;
    });
    if (!added) return;

    state.live.since = liveCursor(state.payload);
    state.live.appliedAt = Date.now();
    renderMarket();
    renderCoverage((state.payload && state.payload.coverage) || []);
    renderDatasetFacts();
    renderStates();
    renderLevels();
    renderTimeframes();
    updateLiveStatus("追加 " + added + " 根 K 线");
  }

  function mergeLiveSection(code, bars, overlay) {
    var section = (state.payload && state.payload.series && state.payload.series[code]) || null;
    if (!section) return;

    if (bars && bars.length) {
      var candles = section.candles.map(function (c) { return { time: c.time, value: c }; });
      var volumes = section.volume.map(function (v) { return { time: v.time, value: v }; });
      bars.forEach(function (bar) {
        var time = Math.floor(new Date(bar.openTime).getTime() / 1000);
        var closeTime = Math.floor(new Date(bar.closeTime).getTime() / 1000);
        candles.push({ time: time, value: {
          time: time, open: Number(bar.open), high: Number(bar.high),
          low: Number(bar.low), close: Number(bar.close),
          isClosed: true, closeTime: closeTime, barId: bar.barId
        } });
        volumes.push({ time: time, value: {
          time: time, value: Number(bar.volume),
          color: Number(bar.close) >= Number(bar.open)
            ? "rgba(38, 166, 154, 0.45)" : "rgba(239, 83, 80, 0.45)"
        } });
      });
      candles.sort(function (a, b) { return a.time - b.time; });
      volumes.sort(function (a, b) { return a.time - b.time; });
      section.candles = candles.map(function (c) { return c.value; });
      section.volume = volumes.map(function (v) { return v.value; });
    }

    if (overlay) {
      Object.keys(overlay).forEach(function (key) {
        section[key] = overlay[key];
      });
    } else {
      section.sma = [];
      section.atr = [];
      section.candidates = [];
    }
    if (!state.priceChart || !state.series.candles) return;

    state.series.candles.setData(uniqueAscending(section.candles));
    if (state.series.volume) state.series.volume.setData(uniqueAscending(section.volume));
    if (state.series.atr) state.series.atr.setData(uniqueAscending(section.atr || []));
    if (state.series.zigzag) state.series.zigzag.setData(uniqueAscending(section.zigzag || []));

    // SMA 逐 Bar 增量追加：整体 setData 会重算上千个点，而增量只有个位数。
    var smaSeries = state.series.sma;
    if (smaSeries && overlay) {
      var known = state.smaTimes || [];
      var lastKnown = known.length ? known[known.length - 1] : -Infinity;
      var added = uniqueAscending(section.sma || []).filter(function (point) {
        return point.time > lastKnown;
      });
      if (added.length) {
        smaSeries.update(added[added.length - 1]);
        state.smaTimes = known.concat(added.map(function (point) { return point.time; }));
      }
    } else if (smaSeries) {
      smaSeries.setData(uniqueAscending(section.sma || []));
      state.smaTimes = uniqueAscending(section.sma || []).map(function (point) { return point.time; });
    }

    if (code === state.tf) {
      redrawOverlays();
    }
  }

  /* 实时刷新时整体重绘叠加层：Zone / N 结构是独立 series，必须先清理再画，
   * 否则每 5 秒都会叠加一层重复的线。价格线同理。 */
  function redrawOverlays() {
    clearOverlays();
    clearPriceLines();
    if (state.toggles.zone) drawZones();
    if (state.toggles.structure) drawStructures();
    drawLevelLines();
    drawReversalThreshold();
    refreshMarkers();
  }

  function renderTimeframes() {
    var frames = (state.payload && state.payload.timeframes) || [];
    var target = null;
    frames.forEach(function (frame) { if (frame.code === state.tf) target = frame; });
    if (target) {
      setStatus(target.code + " · 状态 " + (target.state || "—") +
        " · K 线 " + target.bars + " · 摆动 " + target.swings +
        " · N 结构 " + target.structures + " · Zone " + target.zones);
    }
  }

  /* -------------------------------------------------------------- 初始化 */

  function loadMeta() {
    return api("/api/v1/meta").then(function (meta) {
      state.meta = meta;
      $("sacw-version").textContent = meta.sacwVersion;
      $("spec-version").textContent = meta.specVersion;
      $("instrument").textContent = meta.instrumentId;
      var source = meta.source + (meta.sessionOffsetHours ?
        " · 会话 UTC+" + meta.sessionOffsetHours : " · 会话 UTC");
      $("source-badge").textContent = source;
      $("dataset-badge").textContent = meta.dataset.datasetId +
        " · cfg " + String(meta.configHash).slice(0, 10);
      $("dataset-badge").title = "数据集 " + meta.dataset.datasetId +
        "\n数据哈希 " + meta.dataset.dataHash +
        "\n配置哈希 " + meta.configHash;
    });
  }

  function loadProjects() {
    return api("/api/v1/annotation-projects").then(function (data) {
      state.project = (data.projects && data.projects[0]) || null;
      if (state.project) {
        setStatus("项目：" + state.project.name + "（" + state.project.project_id + "）",
          el.annotationStatus);
      }
    });
  }

  function loadPayload(options) {
    var keepSelection = !!(options && options.keepSelection);
    return api("/api/v1/market/snapshot").then(function (payload) {
      var previous = state.tf;
      state.payload = payload;
      renderMarket();
      renderCoverage(payload.coverage || []);
      renderDatasetFacts();

      var frames = payload.timeframes || [];
      var available = frames.filter(function (frame) { return frame.bars > 0; });
      // 实时刷新会整页重载：此时必须保留用户当前选中的周期，否则滚轮缩放/盘口
      // 更新会把视图悄悄切到 4H。只有首次加载（或原周期已无数据）才重新选择。
      var target;
      if (keepSelection && available.some(function (frame) { return frame.code === previous; })) {
        target = previous;
      } else {
        target = available.some(function (frame) { return frame.code === "4H"; })
          ? "4H" : (available.length ? available[available.length - 1].code : "4H");
      }
      state.tf = target;
      selectTimeframe(target);
      if (payload.skippedBars) {
        setStatus(el.status.textContent + " · 跳过未对齐 " + payload.skippedBars);
      }
    });
  }

  function renderCoverage(coverage) {
    clear(el.coverageRows);
    coverage.forEach(function (row) {
      var tr = makeEl("tr");
      tr.appendChild(makeEl("td", null, row.timeframe));
      tr.appendChild(makeEl("td", null, row.bars));
      tr.appendChild(makeEl("td", row.gaps ? "bad" : "ok", row.gaps));
      tr.appendChild(makeEl("td", row.duplicates ? "bad" : "ok", row.duplicates));
      tr.appendChild(makeEl("td", row.outOfOrder ? "bad" : "ok", row.outOfOrder));
      tr.appendChild(makeEl("td", row.clean ? "ok" : "bad", row.clean ? "OK" : "问题"));
      tr.appendChild(makeEl("td", "mono", row.start || "—"));
      tr.appendChild(makeEl("td", "mono", row.end || "—"));
      el.coverageRows.appendChild(tr);
    });
  }

  function renderDatasetFacts() {
    var payload = state.payload || {};
    var meta = state.meta || {};
    clear(el.datasetFacts);
    var rows = [
      ["合约", payload.instrumentId],
      ["数据来源", payload.source],
      ["会话偏移", "UTC+" + payload.sessionOffsetHours],
      ["数据集", payload.datasetId],
      ["配置哈希", payload.configHash],
      ["规格版本", payload.specVersion],
      ["SACW 版本", payload.sacwVersion],
      ["ATR_MA22", payload.atrMaStatus],
      ["N 结构失效", meta.nStructureInvalidationStatus || "SPEC_AMBIGUITY"],
      ["每周期下发上限", payload.maxSeriesBars]
    ];
    rows.forEach(function (row) {
      el.datasetFacts.appendChild(makeEl("dt", null, row[0]));
      el.datasetFacts.appendChild(makeEl("dd", null, String(row[1] === undefined ? "—" : row[1])));
    });
  }

  /* -------------------------------------------------------------- 回归页 */

  function loadCases() {
    return api("/api/v1/regression-cases").then(function (data) {
      state.cases = data.cases || [];
      renderCaseList();
      if (data.problems && data.problems.length) {
        setStatus("回归样本自检问题：" + data.problems.join("; "), el.suiteMeta);
      }
    });
  }

  function caseStatus(caseItem) {
    if (state.suite) {
      var found = (state.suite.cases || []).filter(function (item) {
        return item.case_id === caseItem.case_id;
      });
      if (found.length) return found[0].status;
    }
    return caseItem.status;
  }

  function renderCaseList() {
    clear(el.caseList);
    var search = state.caseFilter.search.toLowerCase();
    var statusFilter = state.caseFilter.status;
    var shown = state.cases.filter(function (item) {
      var haystack = (item.case_id + " " + item.title + " " + (item.spec_section || "") +
        " " + (item.category || "")).toLowerCase();
      if (search && haystack.indexOf(search) < 0) return false;
      var status = caseStatus(item);
      if (statusFilter && status !== statusFilter) return false;
      return true;
    });

    if (!shown.length) {
      el.caseList.appendChild(makeEl("li", "empty", "没有匹配的样本。"));
      return;
    }
    shown.forEach(function (item) {
      var li = makeEl("li", state.selectedCase === item.case_id ? "active" : "");
      var row = makeEl("div", "row");
      row.appendChild(makeEl("span", "case-id", item.case_id));
      row.appendChild(makeEl("span", "status-" + caseStatus(item), caseStatus(item)));
      li.appendChild(row);
      li.appendChild(makeEl("div", "case-title", item.title));
      li.appendChild(makeEl("div", "case-cat",
        (item.category || "") + " · 规格 " + (item.spec_section || "") +
        " · " + (item.expected || "")));
      li.addEventListener("click", function () { selectCase(item.case_id); });
      el.caseList.appendChild(li);
    });
  }

  function selectCase(caseId) {
    state.selectedCase = caseId;
    var caseItem = state.cases.filter(function (item) { return item.case_id === caseId; })[0];
    if (!caseItem) return;
    renderCaseList();
    $("case-title").textContent = caseItem.case_id + " · " + caseItem.title;

    clear(el.caseFacts);
    var facts = [
      ["类别", caseItem.category],
      ["规格章节", caseItem.spec_section],
      ["预期结果", caseItem.expected],
      ["声明状态", caseItem.status],
      ["阻塞原因", caseItem.blocked_reason || "—"],
      ["审核状态", caseItem.review_status],
      ["样本版本", caseItem.case_version],
      ["数据集哈希", String(caseItem.dataset_hash || "—").slice(0, 16)]
    ];
    facts.forEach(function (row) {
      el.caseFacts.appendChild(makeEl("dt", null, row[0]));
      el.caseFacts.appendChild(makeEl("dd", null, String(row[1] === undefined || row[1] === null ? "—" : row[1])));
    });

    $("case-expected").textContent = JSON.stringify({
      expected: caseItem.expected,
      expected_events: caseItem.expected_events || [],
      expected_absent_events: caseItem.expected_absent_events || [],
      expected_absent_state_transitions: caseItem.expected_absent_state_transitions || [],
      negative_assertion_reason: caseItem.negative_assertion_reason || null
    }, null, 2);

    renderCaseAssertions();
  }

  function renderCaseAssertions() {
    clear(el.caseAssertions);
    if (!state.suite) {
      el.caseAssertions.appendChild(makeEl("li", "empty", "尚未运行回归，点击「运行全套」或样本级运行。"));
      return;
    }
    var outcome = (state.suite.cases || []).filter(function (item) {
      return item.case_id === state.selectedCase;
    })[0];
    if (!outcome) {
      el.caseAssertions.appendChild(makeEl("li", "empty", "本次运行未包含该样本。"));
      return;
    }
    if (outcome.blocked_reason) {
      el.caseAssertions.appendChild(
        makeEl("li", "empty", "阻塞：" + outcome.blocked_reason)
      );
    }
    (outcome.assertions || []).forEach(function (assertion) {
      var li = makeEl("li");
      li.dataset.result = assertion.result;
      var row = makeEl("div", "row");
      row.appendChild(makeEl("span", null, assertion.kind));
      row.appendChild(makeEl("span", "status-" + assertion.result, assertion.result));
      li.appendChild(row);
      li.appendChild(makeEl("div", "detail", assertion.target +
        (assertion.scope ? " · " + assertion.scope : "")));
      if (assertion.detail && Object.keys(assertion.detail).length) {
        li.appendChild(makeEl("div", "detail mono", JSON.stringify(assertion.detail).slice(0, 300)));
      }
      el.caseAssertions.appendChild(li);
    });
  }

  function runSuite() {
    setStatus("运行中…", el.suiteMeta);
    el.runSuite.disabled = true;
    api("/api/v1/regression-suites/v1-4-8/run", { method: "POST" })
      .then(function (summary) {
        state.suite = summary;
        el.suiteMeta.textContent = "run " + summary.run_id +
          " · 通过 " + summary.passed + " / 失败 " + summary.failed +
          " / 阻塞 " + summary.blocked + " · " + summary.duration_ms + " ms" +
          " · cfg " + String(summary.config_hash).slice(0, 10);
        $("suite-summary").textContent = JSON.stringify({
          run_id: summary.run_id,
          code_commit: summary.code_commit,
          config_hash: summary.config_hash,
          dataset_hash: summary.dataset_hash,
          expectation_revision: summary.expectation_revision,
          total: summary.total,
          passed: summary.passed,
          failed: summary.failed,
          blocked: summary.blocked,
          duration_ms: summary.duration_ms
        }, null, 2);
        renderCaseList();
        renderCaseAssertions();
      })
      .catch(function (error) {
        setStatus("运行失败：" + error.message, el.suiteMeta);
      })
      .then(function () { el.runSuite.disabled = false; });
  }

  /* -------------------------------------------------------------- 数据集页 */

  function buildSnapshot() {
    var timeframe = el.snapshotTimeframe.value;
    setStatus("生成快照中…", el.status);
    api("/api/v1/snapshots?timeframe=" + encodeURIComponent(timeframe))
      .then(function (snapshot) {
        el.snapshotOutput.textContent = JSON.stringify({
          status: snapshot.status,
          missing: snapshot.missing,
          snapshotHash: snapshot.snapshotHash,
          payload: {
            timeframe: snapshot.payload.timeframe,
            as_of_ns: snapshot.payload.as_of_ns,
            config_hash: snapshot.payload.config_hash,
            zone_parameters: snapshot.payload.zone_parameters,
            indicators: snapshot.payload.indicators,
            zigzag: snapshot.payload.zigzag,
            swings: (snapshot.payload.swing_points || []).length,
            n_structures: (snapshot.payload.n_structures || []).length,
            zones: (snapshot.payload.zones || []).length,
            state_machines: snapshot.payload.state_machines,
            notes: snapshot.payload.notes
          }
        }, null, 2);
      })
      .catch(function (error) {
        el.snapshotOutput.textContent = "快照失败：" + error.message;
      });
  }

  function freezeGolden() {
    if (!state.project) return;
    if (!state.groundTruthCount) {
      var hint = "没有 APPROVED/FROZEN 标注，不能冻结黄金样本。" +
        "请先在标注列表中完成：保存草稿 → 提交审核 → 审核通过 → 批准。";
      setStatus(hint, el.annotationStatus);
      setStatus(hint, el.groundTruthHash);
      return;
    }
    var split = el.goldenSplit.value;
    api("/api/v1/golden-datasets", {
      method: "POST",
      body: { project_id: state.project.project_id, split: split, actor: "web" }
    }).then(function (golden) {
      var message = "已冻结 " + golden.golden_dataset_id + "（" + golden.annotation_count +
        " 条标注，baseline replay " + shortId(golden.baseline_replay_run_id || "—") + "）";
      setStatus(message, el.groundTruthHash);
      setStatus(message, el.annotationStatus);
      // 冻结会把 APPROVED 同步转为 FROZEN，必须刷新标注列表才能看到新状态。
      loadAnnotations();
      loadProjectSummary();
      loadGolden();
      loadAudit();
    }).catch(function (error) {
      setStatus("冻结失败：" + error.message, el.groundTruthHash);
      setStatus("冻结失败：" + error.message, el.annotationStatus);
    });
  }

  function loadGolden() {
    if (!state.project) return Promise.resolve();
    return Promise.all([
      api("/api/v1/golden-datasets"),
      api("/api/v1/annotation-projects/" + state.project.project_id + "/ground-truth-hash")
    ]).then(function (results) {
      var goldenList = (results[0].goldenDatasets || []).filter(function (item) {
        return item.project_id === state.project.project_id;
      });
      state.goldenDatasets = goldenList;
      var hash = results[1];
      el.groundTruthHash.textContent = "Ground Truth 标注哈希 " +
        String(hash.annotationHash).slice(0, 16) + " · 可用标注 " + hash.annotationCount;
      clear(el.goldenList);
      if (!goldenList.length) {
        el.goldenList.appendChild(makeEl("li", "empty", "尚未冻结黄金样本。"));
        updateComparisonControls();
        return;
      }
      goldenList.forEach(function (item) {
        var li = makeEl("li");
        var row = makeEl("div", "row");
        row.appendChild(makeEl("span", "mono", shortId(item.golden_dataset_id)));
        row.appendChild(makeEl("span", null, item.split));
        li.appendChild(row);
        li.appendChild(makeEl("div", "mono",
          "标注 " + item.annotation_count + " · 数据 " +
          String(item.data_hash).slice(0, 12) + " · 标注哈希 " +
          String(item.annotation_hash).slice(0, 12)));
        li.appendChild(makeEl("div", "mono",
          "baseline replay " + shortId(item.baseline_replay_run_id || "—") +
          " · 配置 " + String(item.baseline_config_hash || "—").slice(0, 10)));
        li.appendChild(makeEl("div", "mono", "冻结于 " + item.frozen_at));
        el.goldenList.appendChild(li);
      });
      updateComparisonControls();
    });
  }

  function exportAnnotations() {
    if (!state.project) return;
    api("/api/v1/annotation-projects/" + state.project.project_id + "/annotations")
      .then(function (data) {
        var payload = {
          project_id: state.project.project_id,
          spec_version: (state.meta && state.meta.specVersion) || "V1.4.8",
          sacw_version: (state.meta && state.meta.sacwVersion) || "V1.1.2",
          config_hash: state.meta && state.meta.configHash,
          dataset_id: state.meta && state.meta.dataset && state.meta.dataset.datasetId,
          exported_at: new Date().toISOString(),
          annotation_count: data.count || 0,
          annotations: data.annotations || []
        };
        var blob = new Blob([JSON.stringify(payload, null, 2)], {
          type: "application/json"
        });
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = "sacw-annotations-" + state.project.project_id + ".json";
        document.body.appendChild(link);
        link.click();
        window.setTimeout(function () {
          URL.revokeObjectURL(link.href);
          link.remove();
        }, 0);
        setStatus("已导出 " + (data.count || 0) + " 条标注 JSON", el.annotationStatus);
      })
      .catch(function (error) {
        setStatus("导出失败：" + error.message, el.annotationStatus);
      });
  }

  function latestGolden() {
    return state.goldenDatasets.length
      ? state.goldenDatasets[state.goldenDatasets.length - 1] : null;
  }

  function runReplay() {
    if (!state.project) return;
    var golden = latestGolden();
    if (!golden) {
      setStatus("需先冻结黄金样本，才能运行程序回放", el.replayStatus);
      return;
    }
    setStatus("运行程序回放…", el.replayStatus);
    api("/api/v1/replay-runs", {
      method: "POST",
      body: {
        project_id: state.project.project_id,
        golden_dataset_id: golden.golden_dataset_id,
        timeframes: ["1M", "1W", "1D", "4H", "1H", "15M", "3M"],
        mode: "BATCH_DETERMINISTIC"
      }
    }).then(function (run) {
      el.replayStatus.textContent = "回放 " + run.run_id + " · " + run.status +
        " · 事件 " + run.eventCount + " · baseline " + shortId(run.baselineReplayRunId);
      el.replayOutput.textContent = JSON.stringify({
        run_id: run.run_id,
        status: run.status,
        golden_dataset_id: run.goldenDatasetId,
        baseline_replay_run_id: run.baselineReplayRunId,
        config_hash: run.config_hash,
        dataset_hash: run.dataset_hash,
        event_counts: run.eventCounts,
        event_count: run.eventCount
      }, null, 2);
      loadReplayRuns();
    }).catch(function (error) {
      setStatus("回放失败：" + error.message, el.replayStatus);
    });
  }

  function loadReplayRuns() {
    return api("/api/v1/replay-runs").then(function (data) {
      var runs = data.runs || [];
      if (el.replayStatus && !el.replayStatus.textContent.startsWith("回放 ")) {
        el.replayStatus.textContent = "已有 " + runs.length + " 次回放";
      }
      return runs;
    }).catch(function (error) {
      setStatus("回放列表加载失败：" + error.message, el.replayStatus);
    });
  }

  function saveSnapshotArtifact() {
    var timeframe = el.snapshotTimeframe.value;
    api("/api/v1/snapshots/artifacts", {
      method: "POST",
      body: { timeframe: timeframe }
    }).then(function (artifact) {
      el.snapshotOutput.textContent = JSON.stringify(artifact, null, 2).slice(0, 4000);
      loadSnapshotArtifacts();
    }).catch(function (error) {
      el.snapshotOutput.textContent = "保存快照失败：" + error.message;
    });
  }

  function loadSnapshotArtifacts() {
    if (!el.snapshotArtifacts) return Promise.resolve();
    return api("/api/v1/snapshots/artifacts").then(function (data) {
      clear(el.snapshotArtifacts);
      var items = data.snapshots || [];
      if (!items.length) {
        el.snapshotArtifacts.appendChild(makeEl("li", "empty", "尚未保存快照。"));
        return;
      }
      items.slice().reverse().forEach(function (item) {
        var li = makeEl("li");
        var row = makeEl("div", "row");
        row.appendChild(makeEl("span", "mono", shortId(item.snapshot_id)));
        row.appendChild(makeEl("span", "status-" + item.status, item.status));
        li.appendChild(row);
        li.appendChild(makeEl("div", "mono",
          (item.detail && item.detail.timeframe ? item.detail.timeframe : "—") +
          " · " + String(item.snapshot_hash || "").slice(0, 12) +
          " · " + item.created_at));
        el.snapshotArtifacts.appendChild(li);
      });
    }).catch(function (error) {
      setStatus("快照列表加载失败：" + error.message);
    });
  }

  function runSelectedCase() {
    if (!state.selectedCase) {
      setStatus("请先选择一个 PB 样本", el.suiteMeta);
      return;
    }
    setStatus("运行 " + state.selectedCase + "…", el.suiteMeta);
    api("/api/v1/regression-cases/" + state.selectedCase + "/runs", {
      method: "POST"
    }).then(function (summary) {
      state.suite = summary;
      el.suiteMeta.textContent = "run " + summary.run_id + " · 通过 " +
        summary.passed + " / 失败 " + summary.failed + " / 阻塞 " + summary.blocked;
      renderCaseList();
      renderCaseAssertions();
      loadAudit();
    }).catch(function (error) {
      setStatus("样本运行失败：" + error.message, el.suiteMeta);
    });
  }

  function loadAudit() {
    return api("/api/v1/audit-logs?limit=60").then(function (data) {
      clear(el.auditList);
      (data.logs || []).slice().reverse().forEach(function (log) {
        var li = makeEl("li");
        li.appendChild(makeEl("span", "action", log.action));
        li.appendChild(makeEl("span", "mono", (log.entity_type || "") + " " +
          shortId(log.entity_id || "")));
        li.appendChild(makeEl("span", "mono", String(log.at)));
        el.auditList.appendChild(li);
      });
    });
  }

  /* -------------------------------------------------------------- 事件绑定 */

  function bindTabs() {
    var tabs = document.querySelectorAll(".tab");
    Array.prototype.forEach.call(tabs, function (tab) {
      tab.addEventListener("click", function () {
        Array.prototype.forEach.call(tabs, function (other) {
          other.classList.remove("active");
        });
        tab.classList.add("active");
        ["annotate", "regression", "dataset"].forEach(function (name) {
          var view = $("view-" + name);
          if (view) view.classList.toggle("active", name === tab.dataset.tab);
        });
        if (tab.dataset.tab === "annotate") {
          setTimeout(function () {
            resizeCharts();
            if (state.priceChart) state.priceChart.timeScale().fitContent();
            if (state.atrChart) state.atrChart.timeScale().fitContent();
          }, 30);
        }
        if (tab.dataset.tab === "regression" && !state.cases.length) loadCases();
        if (tab.dataset.tab === "dataset") {
          loadGolden(); loadAudit(); loadSnapshotArtifacts(); loadReplayRuns();
        }
      });
    });
  }

  function bindPanelTabs() {
    var tabs = document.querySelectorAll(".panel-tab");
    Array.prototype.forEach.call(tabs, function (tab) {
      tab.addEventListener("click", function () {
        Array.prototype.forEach.call(tabs, function (other) {
          other.classList.remove("active");
        });
        tab.classList.add("active");
        ["annotate", "structure", "compare"].forEach(function (name) {
          var view = $("panel-" + name);
          if (view) view.classList.toggle("active", name === tab.dataset.panel);
        });
      });
    });
  }

  function bindTools() {
    var tools = document.querySelectorAll(".tool");
    Array.prototype.forEach.call(tools, function (button) {
      button.addEventListener("click", function () {
        Array.prototype.forEach.call(tools, function (other) {
          other.classList.remove("active");
        });
        button.classList.add("active");
        state.tool = button.dataset.tool;
        if (el.currentTool) {
          var labels = {
            select: "选择", swing: "Swing", nstructure: "N 结构", zone: "Zone",
            protected: "保护点", state: "状态区间"
          };
          el.currentTool.textContent = "当前：" + (labels[state.tool] || state.tool);
        }
        state.pending = null;
        state.pendingClicks = [];
        renderPending();
        renderAnchorPicker();
        refreshMarkers();
        var hints = {
          select: "选择模式：点击 Bar 查看该 Bar 的指标与快照位置。",
          swing: "Swing 工具：第一次点击选择发生 Bar，第二次点击选择确认 Bar。",
          nstructure: "N 结构工具：依次点击 L1、H1、L2、H2 四个已确认摆动点。",
          zone: "Zone 工具：点击至少两个同向已确认摆动点，边界由后端计算。",
          protected: "保护点工具：点击一根 Bar 记录 ProtectedLow/ProtectedHigh 事件；15M 独立保护点会被拒绝。",
          state: "状态区间工具：先选择状态，再点击开始 Bar 和结束 Bar。"
        };
        el.toolHint.textContent = hints[state.tool] || "";
      });
    });
  }

  function bindControls() {
    el.toggleSma.addEventListener("change", function (event) {
      state.toggles.sma = event.target.checked; applyToggles();
    });
    el.toggleAtr.addEventListener("change", function (event) {
      state.toggles.atr = event.target.checked; applyToggles();
    });
    el.toggleZigzag.addEventListener("change", function (event) {
      state.toggles.zigzag = event.target.checked; applyToggles();
    });
    el.toggleCandidate.addEventListener("change", function (event) {
      state.toggles.candidate = event.target.checked; applyToggles();
    });
    el.toggleSwing.addEventListener("change", function (event) {
      state.toggles.swing = event.target.checked; refreshMarkers();
    });
    el.toggleZone.addEventListener("change", function (event) {
      state.toggles.zone = event.target.checked; applyToggles();
    });
    el.toggleStructure.addEventListener("change", function (event) {
      state.toggles.structure = event.target.checked; applyToggles();
    });
    el.toggleLevels.addEventListener("change", function (event) {
      state.toggles.levels = event.target.checked; applyToggles();
    });
    el.toggleManual.addEventListener("change", function (event) {
      state.toggles.manual = event.target.checked; applyToggles();
    });
    if (el.viewReset) el.viewReset.addEventListener("click", resetViewport);
    if (el.viewFit) el.viewFit.addEventListener("click", fitAll);
    document.addEventListener("keydown", function (event) {
      var tag = (event.target && event.target.tagName) || "";
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if (event.key === "r" || event.key === "R") resetViewport();
    });
    el.clearAnchors.addEventListener("click", function () {
      state.pendingClicks = [];
      updateAnchorPending();
    });
    el.zoneMode.addEventListener("change", function (event) {
      state.zoneMode = event.target.value;
      renderZoneModeControls();
      updateAnchorPending();
    });
    [el.zoneHumanLower, el.zoneHumanUpper, el.zoneHumanCenter].forEach(function (input) {
      input.addEventListener("input", function () {
        if (state.tool === "zone") updateAnchorPending();
      });
    });
    el.protectedEventType.addEventListener("change", function (event) {
      state.protectedEventType = event.target.value;
    });
    el.stateIntervalState.addEventListener("change", function (event) {
      state.intervalState = event.target.value;
    });
    el.continuousAnnotation.addEventListener("change", function (event) {
      state.continuous = event.target.checked;
      setStatus(state.continuous
        ? "连续标注已开启：保存草稿后保持当前工具"
        : "连续标注已关闭：保存草稿后回到选择模式", el.annotationStatus);
    });
    el.refreshAnnotations.addEventListener("click", function () {
      loadAnnotations(); loadAudit();
    });
    el.freezeGolden.addEventListener("click", freezeGolden);
    el.freezeGolden2.addEventListener("click", freezeGolden);
    el.compareSwings.addEventListener("click", function () { runComparison("swings"); });
    el.compareZones.addEventListener("click", function () { runComparison("zones"); });
    el.compareNStructures.addEventListener("click", function () {
      runComparison("n-structures");
    });
    el.compareStateIntervals.addEventListener("click", function () {
      runComparison("state-intervals");
    });
    el.exportAnnotations.addEventListener("click", exportAnnotations);
    el.runReplay.addEventListener("click", runReplay);
    el.refreshReplay.addEventListener("click", loadReplayRuns);
    el.saveSnapshot.addEventListener("click", saveSnapshotArtifact);
    el.runCase.addEventListener("click", runSelectedCase);
    el.atrSnapshotField.addEventListener("change", function () {
      updateAtrSnapshotInspector(state.selectedBar, null, null);
    });

    el.caseSearch.addEventListener("input", function (event) {
      state.caseFilter.search = event.target.value;
      renderCaseList();
    });
    el.caseStatusFilter.addEventListener("change", function (event) {
      state.caseFilter.status = event.target.value;
      renderCaseList();
    });
    el.runSuite.addEventListener("click", runSuite);
    el.buildSnapshot.addEventListener("click", buildSnapshot);
  }

  function bindResizeOnce() {
    if (typeof ResizeObserver === "undefined") return;
    var observer = new ResizeObserver(function () {
      if (state.priceChart) resizeCharts();
    });
    observer.observe(el.priceChart);
    observer.observe(el.atrChart);
    state.resizeObserver = observer;
  }

  function boot() {
    el = {
      priceChart: $("price-chart"),
      atrChart: $("atr-chart"),
      timeframeButtons: $("timeframe-buttons"),
      stateRows: $("state-rows"),
      levels: $("levels"),
      zoneList: $("zone-list"),
      structureList: $("structure-list"),
      annotationList: $("annotation-list"),
      pendingAnnotation: $("pending-annotation"),
      anchorPicker: $("anchor-picker"),
      anchorChips: $("anchor-chips"),
      clearAnchors: $("clear-anchors"),
      continuousAnnotation: $("continuous-annotation"),
      zoneModeBox: $("zone-mode-box"),
      zoneMode: $("zone-mode"),
      zoneHumanFields: $("zone-human-fields"),
      zoneHumanLower: $("zone-human-lower"),
      zoneHumanUpper: $("zone-human-upper"),
      zoneHumanCenter: $("zone-human-center"),
      nStructureStatusBox: $("n-structure-status-box"),
      nStructureStatus: $("n-structure-status"),
      protectedEventBox: $("protected-event-box"),
      protectedEventType: $("protected-event-type"),
      stateIntervalBox: $("state-interval-box"),
      stateIntervalState: $("state-interval-state"),
      compareNStructures: $("compare-n-structures"),
      compareStateIntervals: $("compare-state-intervals"),
      exportAnnotations: $("export-annotations"),
      replayStatus: $("replay-status"),
      replayOutput: $("replay-output"),
      runReplay: $("run-replay"),
      refreshReplay: $("refresh-replay"),
      saveSnapshot: $("save-snapshot"),
      snapshotArtifacts: $("snapshot-artifacts"),
      runCase: $("run-case"),
      comparisonStatus: $("comparison-status"),
      comparisonOutput: $("comparison-output"),
      compareSwings: $("compare-swings"),
      compareZones: $("compare-zones"),
      annotationStatus: $("annotation-status"),
      annotationSummary: $("annotation-summary"),
      auditList: $("audit-list"),
      goldenList: $("golden-list"),
      goldenSplit: $("golden-split"),
      groundTruthHash: $("ground-truth-hash"),
      legendOhlc: $("legend-ohlc"),
      legendInd: $("legend-ind"),
      legendZigzag: $("legend-zigzag"),
      legendAtr: $("legend-atr"),
      status: $("status-line"),
      liveStatus: $("live-status"),
      canOpen: $("can-open"),
      canHold: $("can-hold"),
      macroSummary: $("macro-summary"),
      toolHint: $("tool-hint"),
      currentTool: $("current-tool"),
      nInvalidationNotice: $("n-invalidation-notice"),
      atrSnapshotField: $("atr-snapshot-field"),
      atrSnapshot: $("atr-snapshot"),
      coverageRows: $("coverage-rows"),
      datasetFacts: $("dataset-facts"),
      snapshotTimeframe: $("snapshot-timeframe"),
      snapshotOutput: $("snapshot-output"),
      caseList: $("case-list"),
      caseSearch: $("case-search"),
      caseStatusFilter: $("case-status-filter"),
      caseTitle: $("case-title"),
      caseFacts: $("case-facts"),
      caseExpected: $("case-expected"),
      caseAssertions: $("case-assertions"),
      suiteMeta: $("suite-meta"),
      suiteSummary: $("suite-summary"),
      runSuite: $("run-suite"),
      toggleSma: $("toggle-sma"),
      toggleAtr: $("toggle-atr"),
      toggleZigzag: $("toggle-zigzag"),
      toggleCandidate: $("toggle-candidate"),
      toggleSwing: $("toggle-swing"),
      toggleZone: $("toggle-zone"),
      toggleStructure: $("toggle-structure"),
      toggleLevels: $("toggle-levels"),
      viewReset: $("view-reset"),
      viewFit: $("view-fit"),
      toggleManual: $("toggle-manual"),
      refreshAnnotations: $("refresh-annotations"),
      freezeGolden: $("freeze-golden"),
      freezeGolden2: $("freeze-golden-2"),
      buildSnapshot: $("build-snapshot")
    };

    if (!LWC) {
      setStatus("未能加载 Lightweight Charts：缺少 /vendor/lightweight-charts.standalone.production.js");
      return;
    }

    // 时间轴选择器填充
    Object.keys({ "1M": 1, "1W": 1, "1D": 1, "4H": 1, "1H": 1, "15M": 1, "3M": 1 }).forEach(function (code) {
      var option = document.createElement("option");
      option.value = code;
      option.textContent = code;
      el.snapshotTimeframe.appendChild(option);
    });
    el.snapshotTimeframe.value = "4H";

    bindTabs();
    bindPanelTabs();
    bindTools();
    bindControls();
    bindResizeOnce();
    bindLiveToggle();

    loadMeta()
      .then(loadProjects)
      // 显式调用：直接传函数会把上一步返回值当作 options 传入。
      .then(function () { return loadPayload(); })
      .then(function () {
        state.live.since = liveCursor(state.payload);
        updateLiveStatus();
        scheduleLive();
        loadCases();
        loadProjectSummary();
        loadGolden();
        loadSnapshotArtifacts();
        loadReplayRuns();
        loadAudit();
      })
      .catch(function (error) {
        setStatus("加载失败：" + error.message);
      });
  }

  /* 只读调试钩子：供自动化校验读取内部状态，不提供任何写操作。 */
  window.SACW_DEBUG = {
    snapshot: function () {
      return {
        tf: state.tf,
        tool: state.tool,
        pending: state.pending ? { kind: state.pending.kind, valid: state.pending.valid } : null,
        pendingClicks: state.pendingClicks.length,
        annotations: state.annotations.length,
        suite: state.suite ? state.suite.run_id : null,
        priceLines: state.priceLines.length,
        overlays: state.overlays.length,
        candles: (currentSection() && currentSection().candles || []).length,
        candleTimes: (currentSection() && currentSection().candles || []).map(
          function (item) { return item.time; }
        ),
        visibleRange: state.priceChart
          ? state.priceChart.timeScale().getVisibleLogicalRange()
          : null
      };
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
