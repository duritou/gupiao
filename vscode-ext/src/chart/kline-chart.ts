/**
 * K-Line Chart v2.0 — TradingView-style Canvas candlestick chart.
 *
 * Pure JavaScript that runs INSIDE the webview (not the extension host).
 * No external dependencies. Self-contained.
 *
 * Features:
 *   - Candlestick (green up, red down)
 *   - MA5/MA10/MA20/MA60 overlay
 *   - Volume sub-chart
 *   - Crosshair cursor with OHLC tooltip
 *   - Mouse wheel zoom (horizontal)
 *   - Drag to pan
 *   - Period switcher (日K/周K/月K)
 */

export const KLINE_CHART_JS = `
// ============================================================
// K-Line Chart Engine
// ============================================================

class KLineChart {
    constructor(containerId, data, options = {}) {
        this.container = document.getElementById(containerId);
        if (!this.container) return;

        this.data = data || [];
        this.ma5 = [];
        this.ma10 = [];
        this.ma20 = [];
        this.ma60 = [];
        this.volumeData = [];

        // Colors — matching Design Tokens v2.0
        this.colors = {
            bg: '#0B1220',
            panelBg: '#111827',
            border: '#1F2937',
            text: '#9CA3AF',
            textBright: '#F3F4F6',
            up: '#22C55E',
            down: '#EF4444',
            ma5: '#F59E0B',
            ma10: '#3B82F6',
            ma20: '#A78BFA',
            ma60: '#F97316',
            volumeUp: 'rgba(34,197,94,0.4)',
            volumeDown: 'rgba(239,68,68,0.4)',
            crosshair: 'rgba(156,163,175,0.3)',
            gridLine: 'rgba(31,41,55,0.6)',
            wick: '#9CA3AF',
        };

        // Dimensions
        this.chartRatio = 0.65;  // Main chart takes 65% height, volume 15%, gap 5%, padding 15%
        this.minCandleWidth = 3;
        this.maxCandleWidth = 20;
        this.candleWidth = 8;
        this.candleGap = 1;
        this.padding = { top: 20, right: 60, bottom: 20, left: 10 };

        // View state
        this.visibleStart = Math.max(0, this.data.length - 80);
        this.visibleEnd = this.data.length - 1;
        this.offsetX = 0;

        // Interaction state
        this.mouseX = -1;
        this.mouseY = -1;
        this.isDragging = false;
        this.dragStartX = 0;
        this.dragStartOffset = 0;
        this.crosshairIndex = -1;
        this.tooltipVisible = false;

        // Compute MAs
        this.computeMA();
        this.computeVolume();

        // Build DOM
        this.buildDOM();

        // Bind events
        this.bindEvents();

        // Initial render
        this.resize();
        this.render();
    }

    computeMA() {
        const closes = this.data.map(d => d.close);
        this.ma5 = this.calcMA(closes, 5);
        this.ma10 = this.calcMA(closes, 10);
        this.ma20 = this.calcMA(closes, 20);
        this.ma60 = this.calcMA(closes, 60);
    }

    calcMA(data, period) {
        const result = new Array(data.length).fill(null);
        let sum = 0;
        for (let i = 0; i < data.length; i++) {
            sum += data[i];
            if (i >= period) sum -= data[i - period];
            if (i >= period - 1) result[i] = sum / period;
        }
        return result;
    }

    computeVolume() {
        this.volumeData = this.data.map(d => d.volume);
        this.maxVolume = Math.max(...this.volumeData, 1);
    }

    buildDOM() {
        this.container.innerHTML = '';
        this.container.style.cssText = 'position:relative;background:' + this.colors.bg + ';border:1px solid ' + this.colors.border + ';border-radius:6px;overflow:hidden;';

        // Canvas
        this.canvas = document.createElement('canvas');
        this.canvas.style.cssText = 'display:block;width:100%;height:100%;cursor:crosshair;';
        this.container.appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d');

        // Tooltip
        this.tooltip = document.createElement('div');
        this.tooltip.style.cssText = 'position:absolute;top:8px;left:8px;background:' + this.colors.panelBg + ';border:1px solid ' + this.colors.border + ';border-radius:6px;padding:10px 14px;font-size:12px;color:' + this.colors.textBright + ';pointer-events:none;display:none;z-index:10;font-family:JetBrains Mono,Consolas,monospace;min-width:160px;box-shadow:0 4px 12px rgba(0,0,0,0.4);';
        this.container.appendChild(this.tooltip);

        // Legend
        this.legend = document.createElement('div');
        this.legend.style.cssText = 'position:absolute;top:6px;left:50%;transform:translateX(-50%);display:flex;gap:14px;font-size:11px;font-family:JetBrains Mono,monospace;z-index:5;pointer-events:none;';
        this.legend.innerHTML = \`
            <span style="color:\${this.colors.ma5}">MA5</span>
            <span style="color:\${this.colors.ma10}">MA10</span>
            <span style="color:\${this.colors.ma20}">MA20</span>
            <span style="color:\${this.colors.ma60}">MA60</span>
        \`;
        this.container.appendChild(this.legend);
    }

    bindEvents() {
        this.canvas.addEventListener('mousedown', (e) => this.onMouseDown(e));
        this.canvas.addEventListener('mousemove', (e) => this.onMouseMove(e));
        this.canvas.addEventListener('mouseup', () => this.onMouseUp());
        this.canvas.addEventListener('mouseleave', () => {
            this.tooltipVisible = false;
            this.tooltip.style.display = 'none';
            this.crosshairIndex = -1;
            this.render();
        });
        this.canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            this.onWheel(e);
        });
        this.canvas.addEventListener('dblclick', () => this.resetView());
        window.addEventListener('resize', () => { this.resize(); this.render(); });
    }

    onMouseDown(e) {
        this.isDragging = true;
        this.dragStartX = e.clientX;
        this.dragStartOffset = this.visibleStart;
    }

    onMouseMove(e) {
        const rect = this.canvas.getBoundingClientRect();
        this.mouseX = e.clientX - rect.left;
        this.mouseY = e.clientY - rect.top;

        if (this.isDragging) {
            const dx = e.clientX - this.dragStartX;
            const candleCount = this.visibleEnd - this.visibleStart + 1;
            const totalWidth = candleCount * (this.candleWidth + this.candleGap);
            const pixelsPerCandle = totalWidth / candleCount;
            const shift = Math.round(-dx / pixelsPerCandle);
            const newStart = Math.max(0, this.dragStartOffset + shift);
            const range = this.visibleEnd - this.visibleStart;
            this.visibleStart = Math.max(0, Math.min(newStart, this.data.length - range - 1));
            this.visibleEnd = Math.min(this.data.length - 1, this.visibleStart + range);
            this.render();
            return;
        }

        // Update crosshair
        const candleCount = this.visibleEnd - this.visibleStart + 1;
        const chartWidth = this.canvas.width - this.padding.left - this.padding.right;
        const candleSpace = chartWidth / candleCount;
        const relX = this.mouseX - this.padding.left;
        const idx = Math.floor(relX / candleSpace) + this.visibleStart;
        if (idx >= 0 && idx < this.data.length && idx >= this.visibleStart && idx <= this.visibleEnd) {
            this.crosshairIndex = idx;
            this.tooltipVisible = true;
            this.updateTooltip(idx);
        } else {
            this.tooltipVisible = false;
            this.tooltip.style.display = 'none';
        }
        this.render();
    }

    onMouseUp() {
        this.isDragging = false;
    }

    onWheel(e) {
        const candleCount = this.visibleEnd - this.visibleStart + 1;
        const zoomFactor = e.deltaY > 0 ? 1.15 : 0.87;
        const newCount = Math.round(candleCount * zoomFactor);
        const clamped = Math.max(10, Math.min(this.data.length - 1, newCount));

        // Zoom toward mouse position
        const rect = this.canvas.getBoundingClientRect();
        const mouseRelX = (this.mouseX - this.padding.left) / (this.canvas.width - this.padding.left - this.padding.right);
        const centerIdx = this.visibleStart + Math.round(candleCount * mouseRelX);

        this.visibleStart = Math.max(0, Math.round(centerIdx - clamped * mouseRelX));
        this.visibleEnd = Math.min(this.data.length - 1, this.visibleStart + clamped);
        this.visibleStart = Math.max(0, Math.min(this.visibleStart, this.data.length - clamped - 1));

        this.candleWidth = Math.max(this.minCandleWidth, Math.min(this.maxCandleWidth,
            (this.canvas.width - this.padding.left - this.padding.right) / clamped - this.candleGap
        ));

        this.render();
    }

    updateTooltip(idx) {
        const d = this.data[idx];
        const change = d.close - d.open;
        const changePct = d.open > 0 ? ((change / d.open) * 100).toFixed(2) : '0.00';
        const sign = change >= 0 ? '+' : '';
        const color = change >= 0 ? this.colors.up : this.colors.down;

        this.tooltip.innerHTML = \`
            <div style="color:\${this.colors.text};margin-bottom:4px;font-size:11px">\${d.date}</div>
            <div style="font-size:14px;font-weight:700;color:\${color};margin-bottom:4px">\${sign}\${changePct}%</div>
            <div style="display:grid;grid-template-columns:40px 1fr;gap:2px 8px;font-size:11px">
                <span style="color:\${this.colors.text}">开</span><span>\${d.open.toFixed(2)}</span>
                <span style="color:\${this.colors.text}">高</span><span style="color:\${this.colors.up}">\${d.high.toFixed(2)}</span>
                <span style="color:\${this.colors.text}">低</span><span style="color:\${this.colors.down}">\${d.low.toFixed(2)}</span>
                <span style="color:\${this.colors.text}">收</span><span style="color:\${color}">\${d.close.toFixed(2)}</span>
                <span style="color:\${this.colors.text}">量</span><span>\${this.formatVolume(d.volume)}</span>
            </div>
            <div style="margin-top:6px;font-size:10px">
                <span style="color:\${this.colors.ma5}">MA5 \${this.ma5[idx] ? this.ma5[idx].toFixed(2) : '-'}</span>
                &nbsp;<span style="color:\${this.colors.ma20}">MA20 \${this.ma20[idx] ? this.ma20[idx].toFixed(2) : '-'}</span>
            </div>
        \`;
        this.tooltip.style.display = 'block';
    }

    formatVolume(v) {
        if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
        if (v >= 1e4) return (v / 1e4).toFixed(1) + '万';
        return v.toString();
    }

    resetView() {
        this.visibleStart = Math.max(0, this.data.length - 80);
        this.visibleEnd = this.data.length - 1;
        this.candleWidth = 8;
        this.resize();
        this.render();
    }

    resize() {
        const rect = this.container.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.canvas.style.width = rect.width + 'px';
        this.canvas.style.height = rect.height + 'px';
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        this.displayWidth = rect.width;
        this.displayHeight = rect.height;
    }

    // ==========================================================
    // RENDER
    // ==========================================================
    render() {
        const ctx = this.ctx;
        const W = this.displayWidth;
        const H = this.displayHeight;
        const pad = this.padding;

        // Clear
        ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Background
        ctx.fillStyle = this.colors.bg;
        ctx.fillRect(0, 0, W, H);

        const chartTop = pad.top;
        const chartBottom = H * this.chartRatio;
        const chartHeight = chartBottom - chartTop;
        const volumeTop = chartBottom + 20;
        const volumeBottom = H - pad.bottom;
        const volumeHeight = volumeBottom - volumeTop;

        const visibleData = this.data.slice(this.visibleStart, this.visibleEnd + 1);
        const candleCount = visibleData.length;
        const candleSpace = (W - pad.left - pad.right) / candleCount;
        this.candleWidth = Math.max(this.minCandleWidth, Math.min(this.maxCandleWidth, candleSpace - this.candleGap));

        // Price range
        let minPrice = Infinity, maxPrice = -Infinity;
        for (let i = this.visibleStart; i <= this.visibleEnd; i++) {
            const d = this.data[i];
            minPrice = Math.min(minPrice, d.low);
            maxPrice = Math.max(maxPrice, d.high);
            // Include MAs in range
            if (this.ma5[i] != null) { minPrice = Math.min(minPrice, this.ma5[i]); maxPrice = Math.max(maxPrice, this.ma5[i]); }
            if (this.ma10[i] != null) { minPrice = Math.min(minPrice, this.ma10[i]); maxPrice = Math.max(maxPrice, this.ma10[i]); }
            if (this.ma20[i] != null) { minPrice = Math.min(minPrice, this.ma20[i]); maxPrice = Math.max(maxPrice, this.ma20[i]); }
            if (this.ma60[i] != null) { minPrice = Math.min(minPrice, this.ma60[i]); maxPrice = Math.max(maxPrice, this.ma60[i]); }
        }
        const priceRange = maxPrice - minPrice || 1;
        const priceToY = (price) => chartBottom - ((price - minPrice) / priceRange) * chartHeight;

        // Grid lines (price)
        ctx.strokeStyle = this.colors.gridLine;
        ctx.lineWidth = 0.5;
        const gridLines = 5;
        for (let i = 0; i <= gridLines; i++) {
            const y = chartTop + (chartHeight / gridLines) * i;
            const price = maxPrice - (priceRange / gridLines) * i;
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(W - pad.right, y);
            ctx.stroke();
            // Price label
            ctx.fillStyle = this.colors.text;
            ctx.font = '10px JetBrains Mono, monospace';
            ctx.textAlign = 'right';
            ctx.fillText(price.toFixed(2), W - 4, y + 3);
        }

        // ===== DRAW CANDLES =====
        for (let i = 0; i < candleCount; i++) {
            const dataIdx = this.visibleStart + i;
            const d = this.data[dataIdx];
            const x = pad.left + i * candleSpace + candleSpace / 2;
            const w = this.candleWidth;

            const openY = priceToY(d.open);
            const closeY = priceToY(d.close);
            const highY = priceToY(d.high);
            const lowY = priceToY(d.low);

            const isUp = d.close >= d.open;
            const color = isUp ? this.colors.up : this.colors.down;

            // Wick
            ctx.strokeStyle = this.colors.wick;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(x, highY);
            ctx.lineTo(x, lowY);
            ctx.stroke();

            // Body
            const bodyTop = Math.min(openY, closeY);
            const bodyHeight = Math.max(1, Math.abs(closeY - openY));
            ctx.fillStyle = color;
            ctx.fillRect(x - w / 2, bodyTop, w, bodyHeight);

            // Border for very small bodies
            if (bodyHeight < 1.5) {
                ctx.strokeStyle = color;
                ctx.lineWidth = 1;
                ctx.strokeRect(x - w / 2, bodyTop, w, Math.max(1, bodyHeight));
            }
        }

        // ===== DRAW MAs =====
        const drawMA = (maData, color, lineWidth) => {
            ctx.strokeStyle = color;
            ctx.lineWidth = lineWidth;
            ctx.beginPath();
            let started = false;
            for (let i = 0; i < candleCount; i++) {
                const dataIdx = this.visibleStart + i;
                const val = maData[dataIdx];
                if (val == null) continue;
                const x = pad.left + i * candleSpace + candleSpace / 2;
                const y = priceToY(val);
                if (!started) { ctx.moveTo(x, y); started = true; }
                else { ctx.lineTo(x, y); }
            }
            ctx.stroke();
        };

        drawMA(this.ma5, this.colors.ma5, 1);
        drawMA(this.ma10, this.colors.ma10, 1);
        drawMA(this.ma20, this.colors.ma20, 1.5);
        drawMA(this.ma60, this.colors.ma60, 1);

        // ===== DRAW VOLUME =====
        const maxVol = Math.max(...this.volumeData.slice(this.visibleStart, this.visibleEnd + 1), 1);
        for (let i = 0; i < candleCount; i++) {
            const dataIdx = this.visibleStart + i;
            const d = this.data[dataIdx];
            const vol = this.volumeData[dataIdx];
            const x = pad.left + i * candleSpace + candleSpace / 2;
            const barWidth = Math.max(1, this.candleWidth);

            const barHeight = (vol / maxVol) * volumeHeight;
            const y = volumeBottom - barHeight;

            const isUp = d.close >= d.open;
            ctx.fillStyle = isUp ? this.colors.volumeUp : this.colors.volumeDown;
            ctx.fillRect(x - barWidth / 2, y, barWidth, barHeight);
        }

        // Volume grid
        ctx.strokeStyle = this.colors.gridLine;
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        ctx.moveTo(pad.left, volumeTop);
        ctx.lineTo(W - pad.right, volumeTop);
        ctx.stroke();
        ctx.fillStyle = this.colors.text;
        ctx.font = '10px JetBrains Mono, monospace';
        ctx.textAlign = 'right';
        ctx.fillText(this.formatVolume(maxVol), W - 4, volumeTop + 12);

        // Separator line between chart and volume
        ctx.strokeStyle = this.colors.border;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pad.left, chartBottom + 10);
        ctx.lineTo(W - pad.right, chartBottom + 10);
        ctx.stroke();

        // ===== DATE AXIS =====
        ctx.fillStyle = this.colors.text;
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        const dateStep = Math.max(1, Math.floor(candleCount / 6));
        for (let i = 0; i < candleCount; i += dateStep) {
            const dataIdx = this.visibleStart + i;
            const d = this.data[dataIdx];
            const x = pad.left + i * candleSpace + candleSpace / 2;
            // Show MM-DD
            const dateStr = d.date.length >= 10 ? d.date.slice(5) : d.date;
            ctx.fillText(dateStr, x, H - 4);
        }

        // ===== CROSSHAIR =====
        if (this.crosshairIndex >= this.visibleStart && this.crosshairIndex <= this.visibleEnd) {
            const i = this.crosshairIndex - this.visibleStart;
            const x = pad.left + i * candleSpace + candleSpace / 2;

            ctx.strokeStyle = this.colors.crosshair;
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(x, chartTop);
            ctx.lineTo(x, chartBottom);
            ctx.moveTo(x, volumeTop);
            ctx.lineTo(x, volumeBottom);
            ctx.stroke();
            ctx.setLineDash([]);

            // Crosshair dot
            const d = this.data[this.crosshairIndex];
            const cy = priceToY(d.close);
            ctx.fillStyle = d.close >= d.open ? this.colors.up : this.colors.down;
            ctx.beginPath();
            ctx.arc(x, cy, 3, 0, Math.PI * 2);
            ctx.fill();
        }
    }
}

// Export to window for use in webview
window.KLineChart = KLineChart;
`;
