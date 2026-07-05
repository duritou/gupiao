"use strict";
/**
 * Chart Runtime v3.1 — Unified orchestration layer.
 *
 * Architecture:
 *   ChartRuntime
 *     ├── DataFeed        → getVisibleRange(start, end)
 *     ├── IndicatorRegistry → enable("macd") / disable("rsi")
 *     ├── OverlayManager  → add(overlay) / hitTest(x, y)
 *     └── ChartEngine     → Canvas layout + crosshair + zoom/pan
 *
 * Chart knows NOTHING about where data comes from, which indicators
 * are enabled, or what overlays exist. It just orchestrates.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.CHART_RUNTIME_JS = void 0;
exports.CHART_RUNTIME_JS = `
// ============================================================
// Design Tokens
// ============================================================
const C = {
    bg:        '#0B1220',
    panelBg:   '#111827',
    border:    '#1F2937',
    gridLine:  'rgba(31,41,55,0.5)',
    text:      '#9CA3AF',
    textBright:'#F3F4F6',
    textMuted: '#6B7280',
    up:        '#22C55E',
    down:      '#EF4444',
    wick:      '#9CA3AF',
    crosshair: 'rgba(156,163,175,0.25)',
    aiPurple:  '#7C3AED',
    aiBg:      '#1A1030',
    overlayBuy:'rgba(34,197,94,0.9)',
    overlaySell:'rgba(239,68,68,0.9)',
    overlaySupport:'rgba(249,115,22,0.8)',
    overlayResist:'rgba(59,130,246,0.8)',
};

// ============================================================
// 1. DataFeed — Chart never knows where data comes from
// ============================================================
class DataFeed {
    /** Return bars in [startIdx, endIdx] */
    getVisibleRange(startIdx, endIdx) { return []; }
    /** Total bar count */
    get length() { return 0; }
    /** Called when new data arrives (live feed) */
    onUpdate(callback) {}
    /** Latest bar */
    get latest() { return null; }
}

class StaticFeed extends DataFeed {
    constructor(data) {
        super();
        this._data = data || [];
    }
    get length() { return this._data.length; }
    getVisibleRange(startIdx, endIdx) {
        return this._data.slice(Math.max(0, startIdx), Math.min(this._data.length, endIdx + 1));
    }
    get latest() { return this._data[this._data.length - 1]; }
}

// ============================================================
// 2. Indicator — compute + create panel
// ============================================================
class Indicator {
    constructor(id, name) {
        this.id = id;
        this.name = name;
        this.enabled = false;
    }
    /** Compute indicator values from raw data */
    calculate(data) { return {}; }
    /** Create a ChartPanel that renders this indicator */
    createPanel(computed, data) { return null; }
    /** Legend HTML shown in chart header */
    getLegend() { return ''; }
}

// ============================================================
// 3. IndicatorRegistry
// ============================================================
class IndicatorRegistry {
    constructor() {
        this._indicators = new Map();
    }
    register(indicator) {
        this._indicators.set(indicator.id, indicator);
    }
    enable(id) {
        const ind = this._indicators.get(id);
        if (ind) { ind.enabled = true; return true; }
        return false;
    }
    disable(id) {
        const ind = this._indicators.get(id);
        if (ind) { ind.enabled = false; return true; }
        return false;
    }
    toggle(id) {
        const ind = this._indicators.get(id);
        if (ind) { ind.enabled = !ind.enabled; return ind.enabled; }
        return null;
    }
    isEnabled(id) {
        const ind = this._indicators.get(id);
        return ind ? ind.enabled : false;
    }
    getEnabled() {
        return [...this._indicators.values()].filter(i => i.enabled);
    }
    getAll() {
        return [...this._indicators.values()];
    }
    /** Compute all enabled indicators and return their panels */
    computeAndGetPanels(data) {
        const panels = [];
        for (const ind of this.getEnabled()) {
            const computed = ind.calculate(data);
            const panel = ind.createPanel(computed, data);
            if (panel) {
                panel.indicatorId = ind.id;
                panel.indicatorName = ind.name;
                panels.push(panel);
            }
        }
        return panels;
    }
}

// ============================================================
// 4. Overlay — rendered ON TOP of the main chart
// ============================================================
// Priority layers
const PRIORITY = {
    BACKGROUND: 20,
    PATTERN: 30,
    NEWS: 40,
    BACKTEST: 50,
    SUPPORT: 60,
    BUY_SELL: 70,
    AI_REC: 80,
    TOOLTIP: 90,
    CROSSHAIR: 100,
};

class Overlay {
    constructor(id, label, priority = 50) {
        this.id = id;
        this.label = label;
        this.visible = true;
        this.priority = priority;
        this.opacity = 1.0;
        this.interactive = true;
    }
    /** Render overlay on main chart area */
    render(ctx, chart, data, startIdx, endIdx, xScale, yScale, chartX, chartY, chartW, chartH) {}
    /** Hit test: return {overlay, data} or null */
    hitTest(mx, my, chart, data, startIdx, endIdx, xScale, yScale) { return null; }
    /** Tooltip HTML when hovered */
    getTooltip(hitData) { return ''; }
}

class OverlayManager {
    constructor() {
        this._overlays = [];
    }
    add(overlay) {
        this._overlays.push(overlay);
    }
    remove(id) {
        this._overlays = this._overlays.filter(o => o.id !== id);
    }
    clear() {
        this._overlays = [];
    }
    getAll() { return [...this._overlays]; }
    getVisible() { return this._overlays.filter(o => o.visible); }
    /** Render all visible overlays, sorted by priority (lowest = behind) */
    render(ctx, chart, data, startIdx, endIdx, xScale, yScale, chartX, chartY, chartW, chartH) {
        const sorted = this.getVisible().sort((a, b) => a.priority - b.priority);
        for (const o of sorted) {
            ctx.globalAlpha = o.opacity;
            o.render(ctx, chart, data, startIdx, endIdx, xScale, yScale, chartX, chartY, chartW, chartH);
            ctx.globalAlpha = 1.0;
        }
    }
    /** Hit test all overlays (highest priority first), skip non-interactive */
    hitTest(mx, my, chart, data, startIdx, endIdx, xScale, yScale) {
        const sorted = this.getVisible().sort((a, b) => b.priority - a.priority);
        for (const o of sorted) {
            if (!o.interactive) continue;
            const hit = o.hitTest(mx, my, chart, data, startIdx, endIdx, xScale, yScale);
            if (hit) return hit;
        }
        return null;
    }
}

// ============================================================
// 5. Evidence — any system can emit, Chart renders via Overlay
// ============================================================
class Evidence {
    constructor(opts = {}) {
        this.id = opts.id || ('ev_' + Math.random().toString(36).slice(2, 8));
        this.type = opts.type || 'event';        // 'buy_signal','sell_signal','support','resistance','news','earnings','backtest','ai_rec'
        this.date = opts.date || '';             // ISO date matching bar data
        this.price = opts.price || 0;
        this.score = opts.score || 0;            // 0-100 relevance
        this.confidence = opts.confidence || 0;  // 0-1
        this.title = opts.title || '';
        this.description = opts.description || '';
        this.source = opts.source || [];         // ['signal:macd', 'knowledge:semiconductor', 'ai:analyst']
        this.detail = opts.detail || {};         // Extra structured data
    }

    /** Convert to overlay based on type */
    toOverlay() {
        switch (this.type) {
            case 'buy_signal':
                return new BuySignalOverlay([{
                    date: this.date, price: this.price, score: this.score,
                    evidence: this._buildEvidence(),
                }]);
            case 'sell_signal':
                return new SellSignalOverlay([{
                    date: this.date, price: this.price, score: this.score,
                }]);
            case 'support':
                return new SupportLineOverlay([{
                    price: this.price, label: this.title || 'S',
                    confidence: this.confidence, reason: this.description,
                }]);
            case 'resistance':
                return new SupportLineOverlay([{
                    price: this.price, label: this.title || 'R',
                    confidence: this.confidence, reason: this.description,
                }]);
            case 'ai_rec':
                return new AIRecommendationOverlay([{
                    date: this.date, score: this.score,
                    direction: this.score >= 60 ? 'buy' : 'sell',
                    reason: this.description,
                }]);
            case 'backtest':
                return new BacktestTradeOverlay([{
                    entryDate: this.detail.entryDate, entryPrice: this.detail.entryPrice,
                    exitDate: this.detail.exitDate, exitPrice: this.detail.exitPrice,
                    profitPct: this.detail.profitPct, holdingDays: this.detail.holdingDays,
                }]);
            default:
                return null;
        }
    }

    _buildEvidence() {
        return this.source.map(s => {
            const [src, name] = s.split(':');
            return { icon: src === 'signal' ? 'check' : 'star', title: name,
                     credibility: this.confidence, source: s };
        });
    }
}

/** EvidenceBus: any system (AI, backtest, scanner) emits Evidence here */
class EvidenceBus {
    constructor() {
        this._evidence = [];
        this._listeners = [];
    }

    /** Emit new evidence */
    emit(evidence) {
        this._evidence.push(evidence);
        this._notify('add', evidence);
    }

    /** Emit batch */
    emitBatch(evidenceList) {
        for (const e of evidenceList) this._evidence.push(e);
        this._notify('batch', evidenceList);
    }

    /** Get all evidence in date range */
    getRange(startDate, endDate) {
        return this._evidence.filter(e => e.date >= startDate && e.date <= endDate);
    }

    /** Get evidence for a specific date */
    getByDate(date) {
        return this._evidence.filter(e => e.date === date);
    }

    /** Get all evidence sorted by date */
    getAll() { return [...this._evidence].sort((a, b) => a.date.localeCompare(b.date)); }

    /** Get evidence count by type */
    getTypeCounts() {
        const counts = {};
        for (const e of this._evidence) { counts[e.type] = (counts[e.type] || 0) + 1; }
        return counts;
    }

    /** Subscribe to evidence events */
    on(event, callback) { this._listeners.push({event, callback}); }
    _notify(event, data) {
        for (const l of this._listeners) { if (l.event === event) l.callback(data); }
    }

    clear() { this._evidence = []; }
    get length() { return this._evidence.length; }
}

// ============================================================
// 6. ChartPanel
// ============================================================
class ChartPanel {
    constructor(id, ratio) {
        this.id = id;
        this.ratio = ratio || 0.1;
        this.indicatorId = '';
        this.indicatorName = '';
    }
    getYRange(data, startIdx, endIdx) { return [0, 100, v => v.toFixed(1)]; }
    render(ctx, chart, x, y, w, h, data, startIdx, endIdx, crosshairIdx) {}
    getTooltipHTML(data, idx) { return ''; }
}

// ============================================================
// 6. ChartEngine — Canvas layout, crosshair, zoom, pan
// ============================================================
class ChartEngine {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        if (!this.container) return;

        this.data = [];
        this.panels = [];
        this.pad = { top: 4, right: 56, bottom: 20, left: 4 };
        this.gap = 0;

        // Viewport (shared across all panels)
        this.visibleStart = 0;
        this.visibleEnd = 0;
        this.crosshairIndex = -1;

        // Interaction state
        this.isDragging = false;
        this.dragStartX = 0;
        this.dragStartOffset = 0;
        this.mouseX = -1;
        this.mouseY = -1;

        // Callbacks
        this.onCrosshairChange = null;
        this.onOverlayHit = null;
        this._needsResize = true;

        this.buildDOM();
        this.bindEvents();
    }

    buildDOM() {
        this.container.innerHTML = '';
        this.container.style.cssText = 'position:relative;background:' + C.bg + ';border:1px solid ' + C.border + ';border-radius:6px;overflow:hidden;';
        this.canvas = document.createElement('canvas');
        this.canvas.style.cssText = 'display:block;width:100%;height:100%;cursor:crosshair;';
        this.container.appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d');

        this.tooltip = document.createElement('div');
        this.tooltip.id = 'kl-tooltip';
        this.tooltip.style.cssText = 'position:absolute;top:8px;left:8px;background:' + C.panelBg + ';border:1px solid ' + C.border + ';border-radius:6px;padding:10px 14px;font-size:11px;color:' + C.textBright + ';pointer-events:none;display:none;z-index:20;font-family:JetBrains Mono,Consolas,monospace;min-width:170px;box-shadow:0 4px 12px rgba(0,0,0,0.5);';
        this.container.appendChild(this.tooltip);
    }

    bindEvents() {
        this.canvas.addEventListener('mousedown', (e) => this._onMouseDown(e));
        this.canvas.addEventListener('mousemove', (e) => this._onMouseMove(e));
        this.canvas.addEventListener('mouseup', () => { this.isDragging = false; });
        this.canvas.addEventListener('mouseleave', () => {
            this.crosshairIndex = -1;
            this.tooltip.style.display = 'none';
            this.render();
        });
        this.canvas.addEventListener('wheel', (e) => { e.preventDefault(); this._onWheel(e); });
        this.canvas.addEventListener('dblclick', () => this.resetView());
        window.addEventListener('resize', () => { this._needsResize = true; this.render(); });
    }

    _onMouseDown(e) {
        this.isDragging = true;
        this.dragStartX = e.clientX;
        this.dragStartOffset = this.visibleStart;
    }

    _onMouseMove(e) {
        const rect = this.canvas.getBoundingClientRect();
        this.mouseX = e.clientX - rect.left;
        this.mouseY = e.clientY - rect.top;

        if (this.isDragging) {
            const dx = e.clientX - this.dragStartX;
            const count = this.visibleEnd - this.visibleStart + 1;
            const totalW = this._displayW - this.pad.left - this.pad.right;
            const pxPerCandle = totalW / count;
            const shift = Math.round(-dx / pxPerCandle);
            const newStart = Math.max(0, this.dragStartOffset + shift);
            const range = this.visibleEnd - this.visibleStart;
            this.visibleStart = Math.max(0, Math.min(newStart, this.data.length - range - 1));
            this.visibleEnd = Math.min(this.data.length - 1, this.visibleStart + range);
            this.render();
            return;
        }

        const count = this.visibleEnd - this.visibleStart + 1;
        const chartW = this._displayW - this.pad.left - this.pad.right;
        const idx = Math.floor((this.mouseX - this.pad.left) / (chartW / count)) + this.visibleStart;
        if (idx >= this.visibleStart && idx <= this.visibleEnd && idx >= 0 && idx < this.data.length) {
            this.crosshairIndex = idx;
            this._updateTooltip(idx);
            if (this.onCrosshairChange) this.onCrosshairChange(idx);
        } else {
            this.crosshairIndex = -1;
            this.tooltip.style.display = 'none';
        }
        this.render();
    }

    _onWheel(e) {
        const count = this.visibleEnd - this.visibleStart + 1;
        const zoomFactor = e.deltaY > 0 ? 1.15 : 0.87;
        const newCount = Math.round(count * zoomFactor);
        const clamped = Math.max(10, Math.min(this.data.length - 1, newCount));
        const chartW = this._displayW - this.pad.left - this.pad.right;
        const mouseRelX = this.mouseX > 0 ? (this.mouseX - this.pad.left) / chartW : 0.5;
        const centerIdx = this.visibleStart + Math.round(count * mouseRelX);
        this.visibleStart = Math.max(0, Math.round(centerIdx - clamped * mouseRelX));
        this.visibleEnd = Math.min(this.data.length - 1, this.visibleStart + clamped);
        this.visibleStart = Math.max(0, Math.min(this.visibleStart, this.data.length - clamped - 1));
        this.render();
    }

    _updateTooltip(idx) {
        const d = this.data[idx];
        const change = d.close - d.open;
        const pct = d.open > 0 ? ((change / d.open) * 100).toFixed(2) : '0.00';
        const color = change >= 0 ? C.up : C.down;
        const now = new Date().toLocaleTimeString('zh-CN');

        let html = '<div style="font-size:10px;color:' + C.textMuted + ';margin-bottom:3px">' + d.date + '</div>';
        html += '<div style="font-size:15px;font-weight:700;color:' + color + ';margin-bottom:4px">' + (change>=0?'+':'') + pct + '%</div>';
        html += '<div style="display:grid;grid-template-columns:36px 1fr;gap:1px 6px;font-size:10px">';
        html += '<span style="color:' + C.text + '">开</span><span>' + d.open.toFixed(2) + '</span>';
        html += '<span style="color:' + C.text + '">高</span><span style="color:' + C.up + '">' + d.high.toFixed(2) + '</span>';
        html += '<span style="color:' + C.text + '">低</span><span style="color:' + C.down + '">' + d.low.toFixed(2) + '</span>';
        html += '<span style="color:' + C.text + '">收</span><span style="color:' + color + '">' + d.close.toFixed(2) + '</span>';
        html += '</div>';

        // Panel tooltips
        for (const panel of this.panels) {
            const tip = panel.getTooltipHTML(this.data, idx);
            if (tip) {
                html += '<div style="margin:3px 0;border-top:1px solid ' + C.border + ';padding-top:3px;font-size:10px">' + tip + '</div>';
            }
        }

        this.tooltip.innerHTML = html;
        this.tooltip.style.display = 'block';
    }

    resetView() {
        if (this.data.length > 0) {
            this.visibleStart = Math.max(0, this.data.length - 80);
            this.visibleEnd = this.data.length - 1;
        }
        this.render();
    }

    setPeriod(days) {
        this.visibleStart = Math.max(0, this.data.length - days);
        this.visibleEnd = this.data.length - 1;
        this.render();
    }

    setData(data) {
        this.data = data || [];
        if (this.data.length > 0) {
            this.visibleStart = Math.max(0, this.data.length - 80);
            this.visibleEnd = this.data.length - 1;
        }
        this._needsResize = true;
    }

    setPanels(panels) {
        this.panels = panels || [];
    }

    // =========== RENDER ===========
    render(overlaysData = null) {
        const ctx = this.ctx;
        const rect = this.container.getBoundingClientRect();
        if (this._needsResize || rect.width !== this._lastW || rect.height !== this._lastH) {
            this._needsResize = false;
            this._lastW = rect.width;
            this._lastH = rect.height;
            const dpr = window.devicePixelRatio || 1;
            this.canvas.width = rect.width * dpr;
            this.canvas.height = rect.height * dpr;
            this.canvas.style.width = rect.width + 'px';
            this.canvas.style.height = rect.height + 'px';
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        }
        const W = this._lastW;
        const H = this._lastH;
        this._displayW = W;
        this._displayH = H;
        const pad = this.pad;

        // Clear
        ctx.clearRect(0, 0, W * 2, H * 2);
        ctx.fillStyle = C.bg;
        ctx.fillRect(0, 0, W, H);

        if (this.data.length === 0 || this.panels.length === 0) return;

        // Layout panels
        const visiblePanels = this.panels.filter(p => p.ratio > 0);
        if (visiblePanels.length === 0) return;

        const totalRatio = visiblePanels.reduce((s, p) => s + p.ratio, 0);
        const availH = H - pad.top - pad.bottom - this.gap * (visiblePanels.length - 1);

        let currentY = pad.top;
        // Find main panel (candlestick) for overlay rendering
        let mainPanel = null;
        let mainPanelY = 0, mainPanelH = 0;

        for (const panel of visiblePanels) {
            const pH = (panel.ratio / totalRatio) * availH;
            panel.render(ctx, this, pad.left, currentY, W - pad.left - pad.right, pH, this.data, this.visibleStart, this.visibleEnd, this.crosshairIndex);
            if (panel.id === 'main') {
                mainPanel = panel;
                mainPanelY = currentY;
                mainPanelH = pH;
            }
            currentY += pH + this.gap;
        }

        // Render overlays on main panel
        if (overlaysData && mainPanel) {
            const count = this.visibleEnd - this.visibleStart + 1;
            const chartW = W - pad.left - pad.right;
            const candleSpace = count > 0 ? chartW / count : 1;

            // Build scale functions
            const visibleData = this.data.slice(this.visibleStart, this.visibleEnd + 1);
            const [minY, maxY] = mainPanel.getYRange(visibleData, this.data, this.visibleStart, this.visibleEnd);
            const range = maxY - minY || 1;
            const xScale = (i) => pad.left + (i - this.visibleStart) * candleSpace + candleSpace / 2;
            const yScale = (price) => mainPanelY + mainPanelH - ((price - minY) / range) * mainPanelH;

            if (typeof overlaysData === 'object' && overlaysData.render) {
                overlaysData.render(ctx, this, this.data, this.visibleStart, this.visibleEnd, xScale, yScale, pad.left, mainPanelY, chartW, mainPanelH);
            }
        }

        // Date axis
        const count = this.visibleEnd - this.visibleStart + 1;
        if (count > 0) {
            const candleSpace = (W - pad.left - pad.right) / count;
            ctx.fillStyle = C.text;
            ctx.font = '10px sans-serif';
            ctx.textAlign = 'center';
            const dateStep = Math.max(1, Math.floor(count / 6));
            for (let i = 0; i < count; i += dateStep) {
                const d = this.data[this.visibleStart + i];
                const cx = pad.left + i * candleSpace + candleSpace / 2;
                const ds = d.date.length >= 10 ? d.date.slice(5) : d.date;
                ctx.fillText(ds, cx, H - 4);
            }
        }
    }

    // =========== HELPERS ===========
    drawGrid(ctx, x, y, h, w, minY, maxY, fmt, lines) {
        ctx.strokeStyle = C.gridLine; ctx.lineWidth = 0.5;
        for (let i = 0; i <= lines; i++) {
            const py = y + (h / lines) * i;
            const val = maxY - ((maxY - minY) / lines) * i;
            ctx.beginPath(); ctx.moveTo(x, py); ctx.lineTo(x + w, py); ctx.stroke();
            ctx.fillStyle = C.text; ctx.font = '9px JetBrains Mono, monospace';
            ctx.textAlign = 'right'; ctx.fillText(fmt(val), x + w - 3, py + 9);
        }
    }
    drawCrosshair(ctx, cx, py, ph) {
        ctx.strokeStyle = C.crosshair; ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(cx, py); ctx.lineTo(cx, py + ph); ctx.stroke();
        ctx.setLineDash([]);
    }
    formatVolume(v) {
        if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
        if (v >= 1e4) return (v / 1e4).toFixed(1) + '万';
        return v.toString();
    }
}

// ============================================================
// 7. ChartRuntime — top-level orchestrator
// ============================================================
class ChartRuntime {
    constructor(containerId, options = {}) {
        this.engine = new ChartEngine(containerId);
        this.feed = options.dataFeed || new StaticFeed([]);
        this.indicators = new IndicatorRegistry();
        this.overlays = new OverlayManager();
        this.evidence = options.evidenceBus || new EvidenceBus();
        this._legendEl = null;
    }

    /** Initialize: register default indicators, load data, render */
    async init() {
        // Build legend DOM
        if (this.engine.container) {
            this._legendEl = document.createElement('div');
            this._legendEl.style.cssText = 'position:absolute;top:4px;left:6px;right:60px;display:flex;font-size:10px;font-family:JetBrains Mono,monospace;z-index:5;pointer-events:none;flex-wrap:wrap;gap:4px 12px;';
            this.engine.container.appendChild(this._legendEl);
        }

        // Set initial data
        this.engine.setData(this.feed._data || []);

        // Compute panels from enabled indicators
        this._recomputePanels();

        // Initial render
        this.engine.render(this.overlays);

        // Setup resize observer
        if (window.ResizeObserver && this.engine.container) {
            new ResizeObserver(() => {
                this.engine._needsResize = true;
                this.engine.render(this.overlays);
            }).observe(this.engine.container);
        }

        // Wire crosshair → overlay hit test
        this.engine.onCrosshairChange = (idx) => {
            // Overlay hit test happens on render
        };

        return this;
    }

    _recomputePanels() {
        const panels = this.indicators.computeAndGetPanels(this.engine.data);
        this.engine.setPanels(panels);
        this._updateLegend();
    }

    _updateLegend() {
        if (!this._legendEl) return;
        const enabled = this.indicators.getEnabled();
        this._legendEl.innerHTML = enabled.map(i => i.getLegend()).join(' <span style="color:' + C.border + '">|</span> ');
    }

    // ---- Public API ----

    /** Enable an indicator by id */
    enable(id) {
        if (this.indicators.enable(id)) {
            this._recomputePanels();
            this.engine.render(this.overlays);
        }
    }

    /** Disable an indicator by id */
    disable(id) {
        if (this.indicators.disable(id)) {
            this._recomputePanels();
            this.engine.render(this.overlays);
        }
    }

    /** Toggle an indicator */
    toggle(id) {
        const state = this.indicators.toggle(id);
        if (state !== null) {
            this._recomputePanels();
            this.engine.render(this.overlays);
        }
        return state;
    }

    /** Register a new indicator */
    registerIndicator(indicator) {
        this.indicators.register(indicator);
    }

    /** Add an overlay */
    addOverlay(overlay) {
        this.overlays.add(overlay);
        this.engine.render(this.overlays);
    }

    /** Remove an overlay */
    removeOverlay(id) {
        this.overlays.remove(id);
        this.engine.render(this.overlays);
    }

    /** Set visible period */
    setPeriod(days) {
        this.engine.setPeriod(days);
    }

    /** Replace data feed */
    setFeed(feed) {
        this.feed = feed;
        this.engine.setData(feed._data || []);
        this._recomputePanels();
        this.engine.render(this.overlays);
    }

    /** Refresh everything */
    refresh() {
        this.engine.setData(this.feed._data || []);
        this._recomputePanels();
        this.engine.render(this.overlays);
    }

    /** Emit evidence and auto-render as overlay */
    emitEvidence(ev) {
        this.evidence.emit(ev);
        const overlay = ev.toOverlay();
        if (overlay) { this.overlays.add(overlay); this.engine.render(this.overlays); }
    }

    /** Emit batch evidence → overlays */
    emitEvidenceBatch(evidenceList) {
        this.evidence.emitBatch(evidenceList);
        for (const ev of evidenceList) {
            const overlay = ev.toOverlay();
            if (overlay) this.overlays.add(overlay);
        }
        this.engine.render(this.overlays);
    }

    /** Sync: rebuild overlays from all evidence */
    syncOverlaysFromEvidence() {
        this.overlays.clear();
        for (const ev of this.evidence.getAll()) {
            const overlay = ev.toOverlay();
            if (overlay) this.overlays.add(overlay);
        }
        this.engine.render(this.overlays);
    }
}

// Export
window.C = C;
window.PRIORITY = PRIORITY;
window.DataFeed = DataFeed;
window.StaticFeed = StaticFeed;
window.Indicator = Indicator;
window.IndicatorRegistry = IndicatorRegistry;
window.Overlay = Overlay;
window.OverlayManager = OverlayManager;
window.Evidence = Evidence;
window.EvidenceBus = EvidenceBus;
window.ChartPanel = ChartPanel;
window.ChartEngine = ChartEngine;
window.ChartRuntime = ChartRuntime;
`;
//# sourceMappingURL=chart-runtime.js.map