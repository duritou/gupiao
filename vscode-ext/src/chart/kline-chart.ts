/**
 * K-Line Chart v3.0 — Panel-based architecture.
 *
 * Architecture:
 *   Chart → Panels[] → Indicators[]
 *
 * Adding a new indicator = new ChartPanel subclass + chart.addPanel()
 * All panels share: X axis, crosshair, zoom, pan
 * Each panel has: independent Y axis + rendering + tooltip data
 */

export const KLINE_CHART_JS = `
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
    ma5:       '#F59E0B',
    ma10:      '#3B82F6',
    ma20:      '#A78BFA',
    ma60:      '#F97316',
    macdDif:   '#3B82F6',
    macdDea:   '#F59E0B',
    macdHistUp:'rgba(34,197,94,0.7)',
    macdHistDn:'rgba(239,68,68,0.7)',
    rsi6:      '#A78BFA',
    rsi12:     '#60A5FA',
    rsi24:     '#818CF8',
    kdjK:      '#3B82F6',
    kdjD:      '#F59E0B',
    kdjJ:      '#A78BFA',
    volumeUp:  'rgba(34,197,94,0.45)',
    volumeDn:  'rgba(239,68,68,0.45)',
    crosshair: 'rgba(156,163,175,0.25)',
    wick:      '#9CA3AF',
    overbought:'rgba(239,68,68,0.2)',
    oversold:  'rgba(34,197,94,0.2)',
};

// ============================================================
// Indicator computation helpers
// ============================================================
function calcMA(data, period) {
    const r = new Array(data.length).fill(null);
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
        sum += data[i];
        if (i >= period) sum -= data[i - period];
        if (i >= period - 1) r[i] = sum / period;
    }
    return r;
}

function calcEMA(data, period) {
    const r = new Array(data.length).fill(null);
    const k = 2 / (period + 1);
    // Seed with SMA for first value
    let sum = 0;
    for (let i = 0; i < period && i < data.length; i++) sum += data[i];
    if (data.length >= period) {
        r[period - 1] = sum / period;
        for (let i = period; i < data.length; i++) {
            r[i] = data[i] * k + r[i - 1] * (1 - k);
        }
    }
    return r;
}

function calcMACD(data, fast=12, slow=26, signal=9) {
    const closes = data.map(d => d.close);
    const emaFast = calcEMA(closes, fast);
    const emaSlow = calcEMA(closes, slow);
    const dif = closes.map((_, i) => (emaFast[i] != null && emaSlow[i] != null) ? emaFast[i] - emaSlow[i] : null);
    const dea = calcEMA(dif.filter(v => v != null), signal);
    // Align DEA with original indices
    const deaAligned = new Array(closes.length).fill(null);
    let deaIdx = 0;
    for (let i = 0; i < closes.length; i++) {
        if (dif[i] != null && deaIdx < dea.length) {
            deaAligned[i] = dea[deaIdx++];
        }
    }
    const histogram = closes.map((_, i) => (dif[i] != null && deaAligned[i] != null) ? dif[i] - deaAligned[i] : null);
    // Fix: recompute DEA aligned with DIF properly
    const validDif = [];
    const validIdx = [];
    for (let i = 0; i < dif.length; i++) {
        if (dif[i] != null) { validDif.push(dif[i]); validIdx.push(i); }
    }
    const validDea = calcEMA(validDif, signal);
    const dea2 = new Array(closes.length).fill(null);
    for (let i = 0; i < validIdx.length; i++) {
        if (validDea[i] != null) dea2[validIdx[i]] = validDea[i];
    }
    const hist = closes.map((_, i) => (dif[i] != null && dea2[i] != null) ? dif[i] - dea2[i] : null);
    return { dif, dea: dea2, histogram: hist };
}

function calcRSI(data, period=14) {
    const closes = data.map(d => d.close);
    const r = new Array(closes.length).fill(null);
    let avgGain = 0, avgLoss = 0;
    for (let i = 1; i < closes.length; i++) {
        const change = closes[i] - closes[i - 1];
        const gain = change > 0 ? change : 0;
        const loss = change < 0 ? -change : 0;
        if (i < period) {
            avgGain += gain;
            avgLoss += loss;
            if (i === period - 1) {
                avgGain /= period;
                avgLoss /= period;
                r[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
            }
        } else {
            avgGain = (avgGain * (period - 1) + gain) / period;
            avgLoss = (avgLoss * (period - 1) + loss) / period;
            r[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
        }
    }
    return r;
}

function calcKDJ(data, period=9, m1=3, m2=3) {
    const highs = data.map(d => d.high);
    const lows = data.map(d => d.low);
    const closes = data.map(d => d.close);
    const k = new Array(data.length).fill(null);
    const d = new Array(data.length).fill(null);
    const j = new Array(data.length).fill(null);
    let prevK = 50, prevD = 50;
    for (let i = period - 1; i < data.length; i++) {
        const hh = Math.max(...highs.slice(i - period + 1, i + 1));
        const ll = Math.min(...lows.slice(i - period + 1, i + 1));
        const rsv = hh === ll ? 50 : ((closes[i] - ll) / (hh - ll)) * 100;
        const newK = (2 / 3) * prevK + (1 / 3) * rsv;
        const newD = (2 / 3) * prevD + (1 / 3) * newK;
        const newJ = 3 * newK - 2 * newD;
        k[i] = newK; d[i] = newD; j[i] = newJ;
        prevK = newK; prevD = newD;
    }
    return { k, d, j };
}

function calcBOLL(data, period=20, multiplier=2) {
    const closes = data.map(d => d.close);
    const middle = calcMA(closes, period);
    const upper = new Array(data.length).fill(null);
    const lower = new Array(data.length).fill(null);
    for (let i = period - 1; i < data.length; i++) {
        const slice = closes.slice(i - period + 1, i + 1);
        const mean = middle[i];
        const variance = slice.reduce((sum, v) => sum + (v - mean) ** 2, 0) / period;
        const std = Math.sqrt(variance);
        upper[i] = mean + multiplier * std;
        lower[i] = mean - multiplier * std;
    }
    return { upper, middle, lower };
}

// ============================================================
// ChartPanel — base class for all indicator panels
// ============================================================
class ChartPanel {
    constructor(id, label, ratio) {
        this.id = id;
        this.label = label;
        this.ratio = ratio;  // Height ratio within chart
        this.visible = true;
    }

    /** Override: return [minY, maxY, formatter] for the visible data slice */
    getYRange(visibleData, data, startIdx, endIdx) { return [0, 100, v => v.toFixed(1)]; }

    /** Override: render this panel */
    render(ctx, chart, x, y, w, h, data, startIdx, endIdx, crosshairIdx) {}

    /** Override: return tooltip HTML for given data index */
    getTooltipHTML(data, idx) { return ''; }

    /** Override: panel label shown in legend */
    getLegendHTML() { return ''; }
}

// ============================================================
// MainPanel — Candlestick + MA overlay
// ============================================================
class MainPanel extends ChartPanel {
    constructor() { super('main', 'K线', 0.45); }

    getYRange(visibleData) {
        let min = Infinity, max = -Infinity;
        for (const d of visibleData) {
            if (d.low < min) min = d.low;
            if (d.high > max) max = d.high;
        }
        // Include MAs
        const mas = [this._ma5, this._ma10, this._ma20, this._ma60];
        for (const ma of mas) {
            if (!ma) continue;
            for (const v of ma) { if (v != null) { if (v < min) min = v; if (v > max) max = v; } }
        }
        const range = max - min || 1;
        return [min - range * 0.02, max + range * 0.02, v => v.toFixed(2)];
    }

    render(ctx, chart, x, y, w, h, data, startIdx, endIdx, crosshairIdx) {
        const count = endIdx - startIdx + 1;
        if (count <= 0) return;

        const [minY, maxY, fmt] = this.getYRange(data.slice(startIdx, endIdx + 1), data, startIdx, endIdx);
        const range = maxY - minY || 1;
        const toY = (v) => y + h - ((v - minY) / range) * h;
        const candleSpace = w / count;
        const cw = Math.max(1, Math.min(15, candleSpace * 0.7));
        const pad = chart.pad;

        // Grid
        chart.drawGrid(ctx, x, y, w, h, minY, maxY, fmt, 5);

        // Candles
        for (let i = 0; i < count; i++) {
            const d = data[startIdx + i];
            const cx = x + i * candleSpace + candleSpace / 2;
            const openY = toY(d.open), closeY = toY(d.close);
            const highY = toY(d.high), lowY = toY(d.low);
            const isUp = d.close >= d.open;
            const color = isUp ? C.up : C.down;

            // Wick
            ctx.strokeStyle = C.wick;
            ctx.lineWidth = 0.5;
            ctx.beginPath(); ctx.moveTo(cx, highY); ctx.lineTo(cx, lowY); ctx.stroke();

            // Body
            const bodyTop = Math.min(openY, closeY);
            const bodyH = Math.max(1, Math.abs(closeY - openY));
            ctx.fillStyle = color;
            ctx.fillRect(cx - cw / 2, bodyTop, cw, bodyH);
            if (bodyH < 1.5) { ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.strokeRect(cx - cw / 2, bodyTop, cw, Math.max(1, bodyH)); }
        }

        // MAs
        const drawMA = (maData, color, lw) => {
            if (!maData) return;
            ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.beginPath();
            let started = false;
            for (let i = 0; i < count; i++) {
                const v = maData[startIdx + i];
                if (v == null) continue;
                const cx = x + i * candleSpace + candleSpace / 2;
                const cy = toY(v);
                if (!started) { ctx.moveTo(cx, cy); started = true; }
                else ctx.lineTo(cx, cy);
            }
            ctx.stroke();
        };
        drawMA(this._ma5, C.ma5, 1);
        drawMA(this._ma10, C.ma10, 1);
        drawMA(this._ma20, C.ma20, 1.5);
        drawMA(this._ma60, C.ma60, 1);

        // Crosshair
        if (crosshairIdx >= startIdx && crosshairIdx <= endIdx) {
            const i = crosshairIdx - startIdx;
            const cx = x + i * candleSpace + candleSpace / 2;
            chart.drawCrosshair(ctx, cx, y, h);
            const d = data[crosshairIdx];
            const cy = toY(d.close);
            ctx.fillStyle = d.close >= d.open ? C.up : C.down;
            ctx.beginPath(); ctx.arc(cx, cy, 3, 0, Math.PI * 2); ctx.fill();
        }
    }

    getTooltipHTML(data, idx) {
        const d = data[idx];
        const change = d.close - d.open;
        const pct = d.open > 0 ? ((change / d.open) * 100).toFixed(2) : '0.00';
        const color = change >= 0 ? C.up : C.down;
        return \`
            <div style="font-size:10px;color:\${C.textMuted};margin-bottom:3px">\${d.date}</div>
            <div style="font-size:15px;font-weight:700;color:\${color};margin-bottom:4px">\${change>=0?'+':''}\${pct}%</div>
            <div style="display:grid;grid-template-columns:36px 1fr;gap:1px 6px;font-size:10px">
                <span style="color:\${C.text}">开</span><span>\${d.open.toFixed(2)}</span>
                <span style="color:\${C.text}">高</span><span style="color:\${C.up}">\${d.high.toFixed(2)}</span>
                <span style="color:\${C.text}">低</span><span style="color:\${C.down}">\${d.low.toFixed(2)}</span>
                <span style="color:\${C.text}">收</span><span style="color:\${color}">\${d.close.toFixed(2)}</span>
                <span style="color:\${C.text}">量</span><span>\${chart.formatVolume(d.volume)}</span>
            </div>
            <div style="margin-top:4px;font-size:9px">
                <span style="color:\${C.ma5}">MA5 \${this._ma5&&this._ma5[idx]?this._ma5[idx].toFixed(2):'-'}</span>
                <span style="color:\${C.ma20};margin-left:8px">MA20 \${this._ma20&&this._ma20[idx]?this._ma20[idx].toFixed(2):'-'}</span>
            </div>
        \`;
    }

    getLegendHTML() {
        return \`<span style="color:\${C.ma5}">MA5</span> <span style="color:\${C.ma10}">MA10</span> <span style="color:\${C.ma20}">MA20</span> <span style="color:\${C.ma60}">MA60</span>\`;
    }
}

// ============================================================
// VolumePanel
// ============================================================
class VolumePanel extends ChartPanel {
    constructor() { super('volume', 'VOL', 0.11); }

    getYRange(visibleData) {
        const max = Math.max(...visibleData.map(d => d.volume), 1);
        return [0, max, v => v >= 1e8 ? (v/1e8).toFixed(1)+'亿' : (v/1e4).toFixed(0)+'万'];
    }

    render(ctx, chart, x, y, w, h, data, startIdx, endIdx, crosshairIdx) {
        const count = endIdx - startIdx + 1;
        if (count <= 0) return;
        const [_, maxVol, fmt] = this.getYRange(data.slice(startIdx, endIdx + 1));
        const candleSpace = w / count;
        const bw = Math.max(1, candleSpace * 0.7);

        // Top border line
        ctx.strokeStyle = C.border; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + w, y); ctx.stroke();

        // Grid
        chart.drawGrid(ctx, x, y, h, w, 0, maxVol, fmt, 2, false);

        for (let i = 0; i < count; i++) {
            const d = data[startIdx + i];
            const cx = x + i * candleSpace + candleSpace / 2;
            const bh = (d.volume / maxVol) * h;
            ctx.fillStyle = d.close >= d.open ? C.volumeUp : C.volumeDn;
            ctx.fillRect(cx - bw / 2, y + h - bh, bw, bh);
        }

        if (crosshairIdx >= startIdx && crosshairIdx <= endIdx) {
            const i = crosshairIdx - startIdx;
            const cx = x + i * candleSpace + candleSpace / 2;
            chart.drawCrosshair(ctx, cx, y, h);
        }
    }

    getTooltipHTML(data, idx) {
        const v = data[idx].volume;
        return \`<span style="color:\${C.text}">VOL</span> <span style="color:\${C.textBright}">\${v>=1e8?(v/1e8).toFixed(2)+'亿':(v/1e4).toFixed(1)+'万'}</span>\`;
    }
}

// ============================================================
// MACD Panel
// ============================================================
class MACDPanel extends ChartPanel {
    constructor() { super('macd', 'MACD', 0.14); }

    getYRange(visibleData, data, startIdx, endIdx) {
        let min = Infinity, max = -Infinity;
        const { dif, dea, histogram } = this._macd || {};
        for (let i = startIdx; i <= endIdx; i++) {
            if (dif && dif[i] != null) { if (dif[i] < min) min = dif[i]; if (dif[i] > max) max = dif[i]; }
            if (dea && dea[i] != null) { if (dea[i] < min) min = dea[i]; if (dea[i] > max) max = dea[i]; }
            if (histogram && histogram[i] != null) { if (histogram[i] < min) min = histogram[i]; if (histogram[i] > max) max = histogram[i]; }
        }
        if (!isFinite(min)) { min = -1; max = 1; }
        const range = max - min || 1;
        return [min - range * 0.1, max + range * 0.1, v => v.toFixed(3)];
    }

    render(ctx, chart, x, y, w, h, data, startIdx, endIdx, crosshairIdx) {
        const { dif, dea, histogram } = this._macd || {};
        if (!dif) return;
        const count = endIdx - startIdx + 1;
        if (count <= 0) return;
        const [minY, maxY, fmt] = this.getYRange(null, data, startIdx, endIdx);
        const range = maxY - minY || 1;
        const toY = (v) => y + h - ((v - minY) / range) * h;
        const candleSpace = w / count;
        const bw = Math.max(1, candleSpace * 0.6);

        // Border
        ctx.strokeStyle = C.border; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + w, y); ctx.stroke();

        // Zero line
        const zeroY = toY(0);
        ctx.strokeStyle = C.gridLine; ctx.lineWidth = 0.5;
        ctx.beginPath(); ctx.moveTo(x, zeroY); ctx.lineTo(x + w, zeroY); ctx.stroke();
        ctx.fillStyle = C.textMuted; ctx.font = '9px monospace'; ctx.textAlign = 'left';
        ctx.fillText('0', x + 2, zeroY - 2);

        // Histogram
        for (let i = 0; i < count; i++) {
            const idx = startIdx + i;
            if (histogram && histogram[idx] != null) {
                const cx = x + i * candleSpace + candleSpace / 2;
                const hVal = histogram[idx];
                const barTop = toY(Math.max(0, hVal));
                const barBot = toY(Math.min(0, hVal));
                const barH = Math.max(1, barBot - barTop);
                ctx.fillStyle = hVal >= 0 ? C.macdHistUp : C.macdHistDn;
                ctx.fillRect(cx - bw / 2, barTop, bw, barH);
            }
        }

        // DIF & DEA lines
        const drawLine = (arr, color, lw) => {
            if (!arr) return;
            ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.beginPath();
            let started = false;
            for (let i = 0; i < count; i++) {
                const v = arr[startIdx + i];
                if (v == null) continue;
                const cx = x + i * candleSpace + candleSpace / 2;
                const cy = toY(v);
                if (!started) { ctx.moveTo(cx, cy); started = true; }
                else ctx.lineTo(cx, cy);
            }
            ctx.stroke();
        };
        drawLine(dif, C.macdDif, 1);
        drawLine(dea, C.macdDea, 1);

        // Crosshair
        if (crosshairIdx >= startIdx && crosshairIdx <= endIdx) {
            const i = crosshairIdx - startIdx;
            const cx = x + i * candleSpace + candleSpace / 2;
            chart.drawCrosshair(ctx, cx, y, h);
        }

        // Grid
        chart.drawGrid(ctx, x, y, h, w, minY, maxY, fmt, 3);
    }

    getTooltipHTML(data, idx) {
        const { dif, dea, histogram } = this._macd || {};
        return \`
            <span style="color:\${C.macdDif}">DIF \${dif&&dif[idx]!=null?dif[idx].toFixed(4):'-'}</span>
            <span style="color:\${C.macdDea};margin-left:8px">DEA \${dea&&dea[idx]!=null?dea[idx].toFixed(4):'-'}</span>
            <span style="color:\${(histogram&&histogram[idx]||0)>=0?C.up:C.down};margin-left:8px">MACD \${histogram&&histogram[idx]!=null?histogram[idx].toFixed(4):'-'}</span>
        \`;
    }

    getLegendHTML() {
        return \`<span style="color:\${C.macdDif}">DIF</span> <span style="color:\${C.macdDea}">DEA</span>\`;
    }
}

// ============================================================
// RSI Panel
// ============================================================
class RSIPanel extends ChartPanel {
    constructor() { super('rsi', 'RSI', 0.14); }

    getYRange() { return [0, 100, v => v.toFixed(1)]; }

    render(ctx, chart, x, y, w, h, data, startIdx, endIdx, crosshairIdx) {
        const count = endIdx - startIdx + 1;
        if (count <= 0) return;
        const toY = (v) => y + h - ((v - 0) / 100) * h;
        const candleSpace = w / count;

        // Border
        ctx.strokeStyle = C.border; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + w, y); ctx.stroke();

        // Overbought/Oversold zones
        ctx.fillStyle = C.overbought;
        ctx.fillRect(x, y, w, toY(70) - y);
        ctx.fillStyle = C.oversold;
        ctx.fillRect(x, toY(30), w, y + h - toY(30));

        // Reference lines
        [70, 50, 30].forEach(level => {
            const ly = toY(level);
            ctx.strokeStyle = level === 50 ? 'rgba(156,163,175,0.2)' : 'rgba(156,163,175,0.15)';
            ctx.lineWidth = 0.5;
            ctx.setLineDash(level === 50 ? [3, 5] : [2, 6]);
            ctx.beginPath(); ctx.moveTo(x, ly); ctx.lineTo(x + w, ly); ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = C.textMuted; ctx.font = '9px monospace'; ctx.textAlign = 'left';
            ctx.fillText(level, x + 2, ly - 2);
        });

        // RSI lines
        const drawRSI = (arr, color, lw) => {
            if (!arr) return;
            ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.beginPath();
            let started = false;
            for (let i = 0; i < count; i++) {
                const v = arr[startIdx + i];
                if (v == null) continue;
                const cx = x + i * candleSpace + candleSpace / 2;
                const cy = toY(v);
                if (!started) { ctx.moveTo(cx, cy); started = true; }
                else ctx.lineTo(cx, cy);
            }
            ctx.stroke();
        };
        drawRSI(this._rsi6, C.rsi6, 1);
        drawRSI(this._rsi12, C.rsi12, 1.5);
        drawRSI(this._rsi24, C.rsi24, 1);

        if (crosshairIdx >= startIdx && crosshairIdx <= endIdx) {
            const i = crosshairIdx - startIdx;
            const cx = x + i * candleSpace + candleSpace / 2;
            chart.drawCrosshair(ctx, cx, y, h);
        }
    }

    getTooltipHTML(data, idx) {
        return \`
            <span style="color:\${C.rsi6}">RSI6 \${this._rsi6&&this._rsi6[idx]!=null?this._rsi6[idx].toFixed(1):'-'}</span>
            <span style="color:\${C.rsi12};margin-left:8px">RSI12 \${this._rsi12&&this._rsi12[idx]!=null?this._rsi12[idx].toFixed(1):'-'}</span>
            <span style="color:\${C.rsi24};margin-left:8px">RSI24 \${this._rsi24&&this._rsi24[idx]!=null?this._rsi24[idx].toFixed(1):'-'}</span>
        \`;
    }

    getLegendHTML() {
        return \`<span style="color:\${C.rsi6}">RSI6</span> <span style="color:\${C.rsi12}">RSI12</span> <span style="color:\${C.rsi24}">RSI24</span>\`;
    }
}

// ============================================================
// KDJ Panel
// ============================================================
class KDJPanel extends ChartPanel {
    constructor() { super('kdj', 'KDJ', 0.14); }

    getYRange() { return [0, 100, v => v.toFixed(1)]; }

    render(ctx, chart, x, y, w, h, data, startIdx, endIdx, crosshairIdx) {
        const count = endIdx - startIdx + 1;
        if (count <= 0) return;
        const toY = (v) => y + h - ((v - 0) / 100) * h;
        const candleSpace = w / count;

        // Border
        ctx.strokeStyle = C.border; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + w, y); ctx.stroke();

        // Reference lines at 80, 50, 20
        [80, 50, 20].forEach(level => {
            const ly = toY(level);
            ctx.strokeStyle = level === 50 ? 'rgba(156,163,175,0.2)' : 'rgba(156,163,175,0.15)';
            ctx.lineWidth = 0.5;
            ctx.setLineDash(level === 50 ? [3, 5] : [2, 6]);
            ctx.beginPath(); ctx.moveTo(x, ly); ctx.lineTo(x + w, ly); ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = C.textMuted; ctx.font = '9px monospace'; ctx.textAlign = 'left';
            ctx.fillText(level, x + 2, ly - 2);
        });

        // K/D/J lines
        const drawLine = (arr, color, lw) => {
            if (!arr) return;
            ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.beginPath();
            let started = false;
            for (let i = 0; i < count; i++) {
                const v = arr[startIdx + i];
                if (v == null) continue;
                const cx = x + i * candleSpace + candleSpace / 2;
                const cy = toY(v);
                if (!started) { ctx.moveTo(cx, cy); started = true; }
                else ctx.lineTo(cx, cy);
            }
            ctx.stroke();
        };
        drawLine(this._kdjK, C.kdjK, 1);
        drawLine(this._kdjD, C.kdjD, 1);
        drawLine(this._kdjJ, C.kdjJ, 0.8);

        if (crosshairIdx >= startIdx && crosshairIdx <= endIdx) {
            const i = crosshairIdx - startIdx;
            const cx = x + i * candleSpace + candleSpace / 2;
            chart.drawCrosshair(ctx, cx, y, h);
        }
    }

    getTooltipHTML(data, idx) {
        return \`
            <span style="color:\${C.kdjK}">K \${this._kdjK&&this._kdjK[idx]!=null?this._kdjK[idx].toFixed(1):'-'}</span>
            <span style="color:\${C.kdjD};margin-left:8px">D \${this._kdjD&&this._kdjD[idx]!=null?this._kdjD[idx].toFixed(1):'-'}</span>
            <span style="color:\${C.kdjJ};margin-left:8px">J \${this._kdjJ&&this._kdjJ[idx]!=null?this._kdjJ[idx].toFixed(1):'-'}</span>
        \`;
    }

    getLegendHTML() {
        return \`<span style="color:\${C.kdjK}">K</span> <span style="color:\${C.kdjD}">D</span> <span style="color:\${C.kdjJ}">J</span>\`;
    }
}

// ============================================================
// KLineChart v3 — Panel-based architecture
// ============================================================
class KLineChart {
    constructor(containerId, data, options = {}) {
        this.container = document.getElementById(containerId);
        if (!this.container) return;

        this.data = data || [];
        this.pad = { top: 4, right: 56, bottom: 20, left: 4 };
        this.gap = 0;  // Gap between panels

        // View state (shared across all panels)
        this.visibleStart = Math.max(0, this.data.length - 80);
        this.visibleEnd = this.data.length - 1;
        this.crosshairIndex = -1;
        this.tooltipVisible = false;

        // Interaction
        this.mouseX = -1; this.mouseY = -1;
        this.isDragging = false;
        this.dragStartX = 0; this.dragStartOffset = 0;

        // Create panels
        this.panels = [
            new MainPanel(),
            new VolumePanel(),
            new MACDPanel(),
            new RSIPanel(),
            new KDJPanel(),
        ];

        // Compute indicators
        this.computeIndicators();

        // Build DOM
        this.buildDOM();
        this.bindEvents();

        // Render
        this.resize();
        this.render();
    }

    computeIndicators() {
        const closes = this.data.map(d => d.close);
        // MAs (shared)
        const ma5 = calcMA(closes, 5);
        const ma10 = calcMA(closes, 10);
        const ma20 = calcMA(closes, 20);
        const ma60 = calcMA(closes, 60);
        this.panels[0]._ma5 = ma5;
        this.panels[0]._ma10 = ma10;
        this.panels[0]._ma20 = ma20;
        this.panels[0]._ma60 = ma60;

        // MACD
        const macd = calcMACD(this.data);
        this.panels[2]._macd = macd;

        // RSI
        this.panels[3]._rsi6 = calcRSI(this.data, 6);
        this.panels[3]._rsi12 = calcRSI(this.data, 12);
        this.panels[3]._rsi24 = calcRSI(this.data, 24);

        // KDJ
        const kdj = calcKDJ(this.data);
        this.panels[4]._kdjK = kdj.k;
        this.panels[4]._kdjD = kdj.d;
        this.panels[4]._kdjJ = kdj.j;
    }

    buildDOM() {
        this.container.innerHTML = '';
        this.container.style.cssText = 'position:relative;background:' + C.bg + ';border:1px solid ' + C.border + ';border-radius:6px;overflow:hidden;';

        // Canvas
        this.canvas = document.createElement('canvas');
        this.canvas.style.cssText = 'display:block;width:100%;height:100%;cursor:crosshair;';
        this.container.appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d');

        // Tooltip
        this.tooltip = document.createElement('div');
        this.tooltip.id = 'kl-tooltip';
        this.tooltip.style.cssText = 'position:absolute;top:8px;left:8px;background:' + C.panelBg + ';border:1px solid ' + C.border + ';border-radius:6px;padding:10px 14px;font-size:11px;color:' + C.textBright + ';pointer-events:none;display:none;z-index:20;font-family:JetBrains Mono,Consolas,monospace;min-width:170px;box-shadow:0 4px 12px rgba(0,0,0,0.5);';
        this.container.appendChild(this.tooltip);

        // Legend (top-left of each panel)
        this.legend = document.createElement('div');
        this.legend.id = 'kl-legend';
        this.legend.style.cssText = 'position:absolute;top:4px;left:6px;right:60px;display:flex;justify-content:space-between;font-size:10px;font-family:JetBrains Mono,monospace;z-index:5;pointer-events:none;flex-wrap:wrap;gap:4px 12px;';
        this.updateLegend();
        this.container.appendChild(this.legend);
    }

    updateLegend() {
        const visiblePanels = this.panels.filter(p => p.visible);
        this.legend.innerHTML = visiblePanels.map(p => p.getLegendHTML()).join(' <span style="color:' + C.border + '">|</span> ');
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
        this.canvas.addEventListener('wheel', (e) => { e.preventDefault(); this.onWheel(e); });
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
            const count = this.visibleEnd - this.visibleStart + 1;
            const totalW = this.displayWidth - this.pad.left - this.pad.right;
            const pxPerCandle = totalW / count;
            const shift = Math.round(-dx / pxPerCandle);
            const newStart = Math.max(0, this.dragStartOffset + shift);
            const range = this.visibleEnd - this.visibleStart;
            this.visibleStart = Math.max(0, Math.min(newStart, this.data.length - range - 1));
            this.visibleEnd = Math.min(this.data.length - 1, this.visibleStart + range);
            this.render();
            return;
        }

        // Crosshair
        const count = this.visibleEnd - this.visibleStart + 1;
        const chartW = this.displayWidth - this.pad.left - this.pad.right;
        const idx = Math.floor((this.mouseX - this.pad.left) / (chartW / count)) + this.visibleStart;
        if (idx >= this.visibleStart && idx <= this.visibleEnd && idx >= 0 && idx < this.data.length) {
            this.crosshairIndex = idx;
            this.tooltipVisible = true;
            this.updateTooltip(idx);
        } else {
            this.tooltipVisible = false;
            this.tooltip.style.display = 'none';
        }
        this.render();
    }

    onMouseUp() { this.isDragging = false; }

    onWheel(e) {
        const count = this.visibleEnd - this.visibleStart + 1;
        const zoomFactor = e.deltaY > 0 ? 1.15 : 0.87;
        const newCount = Math.round(count * zoomFactor);
        const clamped = Math.max(10, Math.min(this.data.length - 1, newCount));
        const chartW = this.displayWidth - this.pad.left - this.pad.right;
        const mouseRelX = this.mouseX > 0 ? (this.mouseX - this.pad.left) / chartW : 0.5;
        const centerIdx = this.visibleStart + Math.round(count * mouseRelX);
        this.visibleStart = Math.max(0, Math.round(centerIdx - clamped * mouseRelX));
        this.visibleEnd = Math.min(this.data.length - 1, this.visibleStart + clamped);
        this.visibleStart = Math.max(0, Math.min(this.visibleStart, this.data.length - clamped - 1));
        this.render();
    }

    updateTooltip(idx) {
        const d = this.data[idx];
        const visiblePanels = this.panels.filter(p => p.visible);
        const sections = visiblePanels.map(p => p.getTooltipHTML(this.data, idx)).filter(s => s);
        this.tooltip.innerHTML = sections.join('<div style="margin:3px 0;border-top:1px solid ' + C.border + '"></div>');
        this.tooltip.style.display = 'block';
    }

    resetView() {
        this.visibleStart = Math.max(0, this.data.length - 80);
        this.visibleEnd = this.data.length - 1;
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

    drawGrid(ctx, x, y, h, w, minY, maxY, fmt, lines, labelLeft = false) {
        ctx.strokeStyle = C.gridLine;
        ctx.lineWidth = 0.5;
        for (let i = 0; i <= lines; i++) {
            const py = y + (h / lines) * i;
            const val = maxY - ((maxY - minY) / lines) * i;
            ctx.beginPath();
            ctx.moveTo(x, py);
            ctx.lineTo(x + w, py);
            ctx.stroke();
            ctx.fillStyle = C.text;
            ctx.font = '9px JetBrains Mono, monospace';
            if (labelLeft) {
                ctx.textAlign = 'left';
                ctx.fillText(fmt(val), x + 3, py + 9);
            } else {
                ctx.textAlign = 'right';
                ctx.fillText(fmt(val), x + w - 3, py + 9);
            }
        }
    }

    drawCrosshair(ctx, cx, panelY, panelH) {
        ctx.strokeStyle = C.crosshair;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(cx, panelY);
        ctx.lineTo(cx, panelY + panelH);
        ctx.stroke();
        ctx.setLineDash([]);
    }

    formatVolume(v) {
        if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
        if (v >= 1e4) return (v / 1e4).toFixed(1) + '万';
        return v.toString();
    }

    // ==========================================================
    // RENDER — panel layout orchestrator
    // ==========================================================
    render() {
        const ctx = this.ctx;
        const W = this.displayWidth;
        const H = this.displayHeight;
        const pad = this.pad;

        // Clear
        ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        ctx.fillStyle = C.bg;
        ctx.fillRect(0, 0, W, H);

        const visiblePanels = this.panels.filter(p => p.visible);
        if (visiblePanels.length === 0) return;

        // Calculate total ratio
        const totalRatio = visiblePanels.reduce((s, p) => s + p.ratio, 0);
        const availableH = H - pad.top - pad.bottom - this.gap * (visiblePanels.length - 1);

        let currentY = pad.top;
        for (const panel of visiblePanels) {
            const panelH = (panel.ratio / totalRatio) * availableH;
            panel.render(ctx, this, pad.left, currentY, W - pad.left - pad.right, panelH, this.data, this.visibleStart, this.visibleEnd, this.crosshairIndex);
            currentY += panelH + this.gap;
        }

        // Date axis at bottom
        const count = this.visibleEnd - this.visibleStart + 1;
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

        this.updateLegend();
    }

    // Public API
    addPanel(panel) {
        this.panels.push(panel);
        this.render();
    }

    removePanel(id) {
        this.panels = this.panels.filter(p => p.id !== id);
        this.render();
    }

    togglePanel(id) {
        const p = this.panels.find(p => p.id === id);
        if (p) { p.visible = !p.visible; this.render(); }
    }

    setPeriod(days) {
        this.visibleStart = Math.max(0, this.data.length - days);
        this.visibleEnd = this.data.length - 1;
        this.render();
    }

    /** Focus to a specific date range */
    focusRange(startDate, endDate) {
        const si = this.data.findIndex(d => d.date >= startDate);
        const ei = this.data.findIndex(d => d.date > endDate);
        if (si >= 0) {
            this.visibleStart = si;
            this.visibleEnd = ei > si ? ei - 1 : Math.min(this.data.length - 1, si + 60);
            this.render();
        }
    }
}

window.KLineChart = KLineChart;
`;
