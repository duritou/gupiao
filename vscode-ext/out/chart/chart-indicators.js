"use strict";
/**
 * Default indicators for Chart Runtime.
 * Each implements: calculate(data) → createPanel(computed) → getLegend()
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.INDICATORS_JS = void 0;
exports.INDICATORS_JS = `
// ============================================================
// Math helpers
// ============================================================
function _ma(data, period) {
    const r = new Array(data.length).fill(null);
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
        sum += data[i];
        if (i >= period) sum -= data[i - period];
        if (i >= period - 1) r[i] = sum / period;
    }
    return r;
}
function _ema(data, period) {
    const r = new Array(data.length).fill(null);
    const k = 2 / (period + 1);
    let sum = 0;
    for (let i = 0; i < period && i < data.length; i++) sum += data[i];
    if (data.length >= period) {
        r[period - 1] = sum / period;
        for (let i = period; i < data.length; i++) r[i] = data[i] * k + r[i - 1] * (1 - k);
    }
    return r;
}
function _macd(data) {
    const closes = data.map(d => d.close);
    const emaFast = _ema(closes, 12);
    const emaSlow = _ema(closes, 26);
    const dif = closes.map((_, i) => (emaFast[i] != null && emaSlow[i] != null) ? emaFast[i] - emaSlow[i] : null);
    const valid = []; const idxs = [];
    for (let i = 0; i < dif.length; i++) { if (dif[i] != null) { valid.push(dif[i]); idxs.push(i); } }
    const deaRaw = _ema(valid, 9);
    const dea = new Array(closes.length).fill(null);
    for (let i = 0; i < idxs.length; i++) { if (deaRaw[i] != null) dea[idxs[i]] = deaRaw[i]; }
    const hist = closes.map((_, i) => (dif[i] != null && dea[i] != null) ? dif[i] - dea[i] : null);
    return { dif, dea, hist };
}
function _rsi(data, period) {
    const closes = data.map(d => d.close);
    const r = new Array(closes.length).fill(null);
    let avgG = 0, avgL = 0;
    for (let i = 1; i < closes.length; i++) {
        const ch = closes[i] - closes[i-1];
        const g = ch > 0 ? ch : 0;
        const l = ch < 0 ? -ch : 0;
        if (i < period) { avgG += g; avgL += l; }
        if (i === period - 1) { avgG /= period; avgL /= period; r[i] = avgL === 0 ? 100 : 100 - 100/(1+avgG/avgL); }
        if (i >= period) { avgG = (avgG*(period-1)+g)/period; avgL = (avgL*(period-1)+l)/period; r[i] = avgL === 0 ? 100 : 100 - 100/(1+avgG/avgL); }
    }
    return r;
}
function _kdj(data) {
    const h = data.map(d => d.high), l = data.map(d => d.low), c = data.map(d => d.close);
    const k = new Array(data.length).fill(null), d = new Array(data.length).fill(null), j = new Array(data.length).fill(null);
    let pk = 50, pd = 50;
    for (let i = 8; i < data.length; i++) {
        const hh = Math.max(...h.slice(i-8,i+1)), ll = Math.min(...l.slice(i-8,i+1));
        const rsv = hh === ll ? 50 : ((c[i]-ll)/(hh-ll))*100;
        const nk = (2/3)*pk + (1/3)*rsv;
        const nd = (2/3)*pd + (1/3)*nk;
        const nj = 3*nk - 2*nd;
        k[i]=nk; d[i]=nd; j[i]=nj; pk=nk; pd=nd;
    }
    return { k, d, j };
}

// ============================================================
// 1. MainIndicator — Candlestick + MA overlay
// ============================================================
class MainIndicator extends Indicator {
    constructor() { super('main', 'K线'); this.enabled = true; }

    calculate(data) {
        const closes = data.map(d => d.close);
        return {
            ma5: _ma(closes, 5), ma10: _ma(closes, 10),
            ma20: _ma(closes, 20), ma60: _ma(closes, 60),
        };
    }

    createPanel(computed, data) {
        const self = this;
        return new (class extends ChartPanel {
            constructor() { super('main', 0.45); }
            getYRange(visibleData) {
                let min = Infinity, max = -Infinity;
                for (const d of visibleData) { if (d.low < min) min = d.low; if (d.high > max) max = d.high; }
                for (const arr of [computed.ma5, computed.ma10, computed.ma20, computed.ma60]) {
                    for (const v of arr) { if (v != null) { if (v < min) min = v; if (v > max) max = v; } }
                }
                const range = max - min || 1;
                return [min - range * 0.02, max + range * 0.02, v => v.toFixed(2)];
            }
            render(ctx, chart, x, y, w, h, data, start, end, cross) {
                const count = end - start + 1;
                if (count <= 0) return;
                const [minY, maxY, fmt] = this.getYRange(data.slice(start, end + 1));
                const range = maxY - minY || 1;
                const toY = v => y + h - ((v - minY) / range) * h;
                const cs = w / count, cw = Math.max(1, Math.min(15, cs * 0.7));
                chart.drawGrid(ctx, x, y, h, w, minY, maxY, fmt, 5);
                for (let i = 0; i < count; i++) {
                    const d = data[start + i];
                    const cx = x + i * cs + cs / 2;
                    const [oy, cy, hy, ly] = [toY(d.open), toY(d.close), toY(d.high), toY(d.low)];
                    ctx.strokeStyle = C.wick; ctx.lineWidth = 0.5;
                    ctx.beginPath(); ctx.moveTo(cx, hy); ctx.lineTo(cx, ly); ctx.stroke();
                    const bodyTop = Math.min(oy, cy), bodyH = Math.max(1, Math.abs(cy - oy));
                    ctx.fillStyle = d.close >= d.open ? C.up : C.down;
                    ctx.fillRect(cx - cw/2, bodyTop, cw, bodyH);
                    if (bodyH < 1.5) { ctx.strokeStyle = d.close >= d.open ? C.up : C.down; ctx.lineWidth = 1; ctx.strokeRect(cx - cw/2, bodyTop, cw, 1); }
                }
                [[computed.ma5,C.ma5,1],[computed.ma10,C.ma10,1],[computed.ma20,C.ma20,1.5],[computed.ma60,C.ma60,1]].forEach(([arr,color,lw]) => {
                    ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.beginPath();
                    let s = false;
                    for (let i = 0; i < count; i++) { const v = arr[start+i]; if (v==null) continue; const cx = x + i*cs + cs/2; if(!s){ctx.moveTo(cx,toY(v));s=true;} else ctx.lineTo(cx,toY(v)); }
                    ctx.stroke();
                });
                if (cross >= start && cross <= end) {
                    const cx = x + (cross-start)*cs + cs/2;
                    chart.drawCrosshair(ctx, cx, y, h);
                    const d = data[cross];
                    ctx.fillStyle = d.close >= d.open ? C.up : C.down;
                    ctx.beginPath(); ctx.arc(cx, toY(d.close), 3, 0, Math.PI*2); ctx.fill();
                }
            }
            getTooltipHTML(data, idx) { return ''; }
        })();
    }

    getLegend() {
        return '<span style="color:#F59E0B">MA5</span> <span style="color:#3B82F6">MA10</span> <span style="color:#A78BFA">MA20</span> <span style="color:#F97316">MA60</span>';
    }
}

// ============================================================
// 2. VolumeIndicator
// ============================================================
class VolumeIndicator extends Indicator {
    constructor() { super('volume', 'VOL'); this.enabled = true; }

    calculate(data) { return {}; }

    createPanel(computed, data) {
        return new (class extends ChartPanel {
            constructor() { super('volume', 0.11); }
            getYRange(visibleData) { const max = Math.max(...visibleData.map(d=>d.volume), 1); return [0, max, v => v>=1e8?(v/1e8).toFixed(1)+'亿':(v/1e4).toFixed(0)+'万']; }
            render(ctx, chart, x, y, w, h, data, start, end, cross) {
                const count = end - start + 1;
                if (count <= 0) return;
                const [_, maxVol, fmt] = this.getYRange(data.slice(start, end + 1));
                const cs = w / count, bw = Math.max(1, cs * 0.7);
                ctx.strokeStyle = C.border; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + w, y); ctx.stroke();
                chart.drawGrid(ctx, x, y, h, w, 0, maxVol, fmt, 2);
                for (let i = 0; i < count; i++) {
                    const d = data[start+i], cx = x + i*cs + cs/2, bh = (d.volume/maxVol)*h;
                    ctx.fillStyle = d.close >= d.open ? 'rgba(34,197,94,0.45)' : 'rgba(239,68,68,0.45)';
                    ctx.fillRect(cx - bw/2, y + h - bh, bw, bh);
                }
                if (cross >= start && cross <= end) chart.drawCrosshair(ctx, x + (cross-start)*cs + cs/2, y, h);
            }
            getTooltipHTML(data, idx) {
                const v = data[idx].volume;
                return '<span style="color:#9CA3AF">VOL</span> <span style="color:#F3F4F6">' + (v>=1e8?(v/1e8).toFixed(2)+'亿':(v/1e4).toFixed(1)+'万') + '</span>';
            }
        })();
    }

    getLegend() { return '<span style="color:#9CA3AF">VOL</span>'; }
}

// ============================================================
// 3. MACDIndicator
// ============================================================
class MACDIndicator extends Indicator {
    constructor() { super('macd', 'MACD'); this.enabled = true; }

    calculate(data) { return _macd(data); }

    createPanel(computed, data) {
        const { dif, dea, hist } = computed;
        return new (class extends ChartPanel {
            constructor() { super('macd', 0.13); }
            getYRange(visibleData, data, start, end) {
                let min = Infinity, max = -Infinity;
                for (let i = start; i <= end; i++) {
                    if (dif[i]!=null) { if(dif[i]<min)min=dif[i]; if(dif[i]>max)max=dif[i]; }
                    if (dea[i]!=null) { if(dea[i]<min)min=dea[i]; if(dea[i]>max)max=dea[i]; }
                    if (hist[i]!=null) { if(hist[i]<min)min=hist[i]; if(hist[i]>max)max=hist[i]; }
                }
                if (!isFinite(min)) { min=-1; max=1; }
                const range = max - min || 1;
                return [min - range*0.1, max + range*0.1, v=>v.toFixed(3)];
            }
            render(ctx, chart, x, y, w, h, data, start, end, cross) {
                const count = end - start + 1;
                if (count <= 0) return;
                const [minY, maxY, fmt] = this.getYRange(null, data, start, end);
                const range = maxY - minY || 1, toY = v => y + h - ((v-minY)/range)*h;
                const cs = w/count, bw = Math.max(1, cs*0.6);
                ctx.strokeStyle = C.border; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x+w, y); ctx.stroke();
                const zy = toY(0);
                ctx.strokeStyle = C.gridLine; ctx.lineWidth = 0.5; ctx.beginPath(); ctx.moveTo(x, zy); ctx.lineTo(x+w, zy); ctx.stroke();
                ctx.fillStyle = C.textMuted; ctx.font = '9px monospace'; ctx.textAlign = 'left'; ctx.fillText('0', x+2, zy-2);
                for (let i = 0; i < count; i++) {
                    const idx = start+i;
                    if (hist[idx] != null) {
                        const cx = x + i*cs + cs/2;
                        const top = toY(Math.max(0, hist[idx])), bot = toY(Math.min(0, hist[idx]));
                        ctx.fillStyle = hist[idx] >= 0 ? 'rgba(34,197,94,0.7)' : 'rgba(239,68,68,0.7)';
                        ctx.fillRect(cx - bw/2, top, bw, Math.max(1, bot-top));
                    }
                }
                [[dif, '#3B82F6',1],[dea, '#F59E0B',1]].forEach(([arr,color,lw]) => {
                    ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.beginPath();
                    let s = false;
                    for (let i = 0; i < count; i++) { const v = arr[start+i]; if (v==null) continue; const cx = x + i*cs + cs/2; if(!s){ctx.moveTo(cx,toY(v));s=true;} else ctx.lineTo(cx,toY(v)); }
                    ctx.stroke();
                });
                chart.drawGrid(ctx, x, y, h, w, minY, maxY, fmt, 3);
                if (cross >= start && cross <= end) chart.drawCrosshair(ctx, x + (cross-start)*cs + cs/2, y, h);
            }
            getTooltipHTML(data, idx) {
                return '<span style="color:#3B82F6">DIF ' + (dif[idx]!=null?dif[idx].toFixed(4):'-') + '</span> <span style="color:#F59E0B">DEA ' + (dea[idx]!=null?dea[idx].toFixed(4):'-') + '</span> <span style="color:' + ((hist[idx]||0)>=0?C.up:C.down) + '">' + (hist[idx]!=null?hist[idx].toFixed(4):'-') + '</span>';
            }
        })();
    }

    getLegend() { return '<span style="color:#3B82F6">DIF</span> <span style="color:#F59E0B">DEA</span>'; }
}

// ============================================================
// 4. RSIIndicator
// ============================================================
class RSIIndicator extends Indicator {
    constructor() { super('rsi', 'RSI'); this.enabled = true; }

    calculate(data) { return { rsi6: _rsi(data, 6), rsi12: _rsi(data, 12), rsi24: _rsi(data, 24) }; }

    createPanel(computed, data) {
        const { rsi6, rsi12, rsi24 } = computed;
        return new (class extends ChartPanel {
            constructor() { super('rsi', 0.13); }
            getYRange() { return [0, 100, v=>v.toFixed(1)]; }
            render(ctx, chart, x, y, w, h, data, start, end, cross) {
                const count = end - start + 1;
                if (count <= 0) return;
                const toY = v => y + h - (v/100)*h, cs = w/count;
                ctx.strokeStyle = C.border; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x+w, y); ctx.stroke();
                ctx.fillStyle = 'rgba(239,68,68,0.15)'; ctx.fillRect(x, y, w, toY(70)-y);
                ctx.fillStyle = 'rgba(34,197,94,0.15)'; ctx.fillRect(x, toY(30), w, y+h-toY(30));
                [70,50,30].forEach(lv => {
                    const ly = toY(lv);
                    ctx.strokeStyle = 'rgba(156,163,175,' + (lv===50?'0.2':'0.15') + ')'; ctx.lineWidth = 0.5;
                    ctx.setLineDash(lv===50 ? [3,5] : [2,6]);
                    ctx.beginPath(); ctx.moveTo(x, ly); ctx.lineTo(x+w, ly); ctx.stroke(); ctx.setLineDash([]);
                    ctx.fillStyle = C.textMuted; ctx.font = '9px monospace'; ctx.textAlign = 'left'; ctx.fillText(lv, x+2, ly-2);
                });
                [[rsi6,'#A78BFA',1],[rsi12,'#60A5FA',1.5],[rsi24,'#818CF8',1]].forEach(([arr,color,lw]) => {
                    ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.beginPath();
                    let s = false;
                    for (let i = 0; i < count; i++) { const v = arr[start+i]; if (v==null) continue; const cx = x + i*cs + cs/2; if(!s){ctx.moveTo(cx,toY(v));s=true;} else ctx.lineTo(cx,toY(v)); }
                    ctx.stroke();
                });
                if (cross >= start && cross <= end) chart.drawCrosshair(ctx, x + (cross-start)*cs + cs/2, y, h);
            }
            getTooltipHTML(data, idx) {
                return '<span style="color:#A78BFA">RSI6 ' + (rsi6[idx]!=null?rsi6[idx].toFixed(1):'-') + '</span> <span style="color:#60A5FA">RSI12 ' + (rsi12[idx]!=null?rsi12[idx].toFixed(1):'-') + '</span> <span style="color:#818CF8">RSI24 ' + (rsi24[idx]!=null?rsi24[idx].toFixed(1):'-') + '</span>';
            }
        })();
    }

    getLegend() { return '<span style="color:#A78BFA">RSI6</span> <span style="color:#60A5FA">RSI12</span> <span style="color:#818CF8">RSI24</span>'; }
}

// ============================================================
// 5. KDJIndicator
// ============================================================
class KDJIndicator extends Indicator {
    constructor() { super('kdj', 'KDJ'); this.enabled = true; }

    calculate(data) { return _kdj(data); }

    createPanel(computed, data) {
        const { k, d, j } = computed;
        return new (class extends ChartPanel {
            constructor() { super('kdj', 0.13); }
            getYRange() { return [0, 100, v=>v.toFixed(1)]; }
            render(ctx, chart, x, y, w, h, data, start, end, cross) {
                const count = end - start + 1;
                if (count <= 0) return;
                const toY = v => y + h - (v/100)*h, cs = w/count;
                ctx.strokeStyle = C.border; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x+w, y); ctx.stroke();
                [80,50,20].forEach(lv => {
                    const ly = toY(lv);
                    ctx.strokeStyle = 'rgba(156,163,175,' + (lv===50?'0.2':'0.15') + ')'; ctx.lineWidth = 0.5;
                    ctx.setLineDash(lv===50 ? [3,5] : [2,6]);
                    ctx.beginPath(); ctx.moveTo(x, ly); ctx.lineTo(x+w, ly); ctx.stroke(); ctx.setLineDash([]);
                    ctx.fillStyle = C.textMuted; ctx.font = '9px monospace'; ctx.textAlign = 'left'; ctx.fillText(lv, x+2, ly-2);
                });
                [[k,'#3B82F6',1],[d,'#F59E0B',1],[j,'#A78BFA',0.8]].forEach(([arr,color,lw]) => {
                    ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.beginPath();
                    let s = false;
                    for (let i = 0; i < count; i++) { const v = arr[start+i]; if (v==null) continue; const cx = x + i*cs + cs/2; if(!s){ctx.moveTo(cx,toY(v));s=true;} else ctx.lineTo(cx,toY(v)); }
                    ctx.stroke();
                });
                if (cross >= start && cross <= end) chart.drawCrosshair(ctx, x + (cross-start)*cs + cs/2, y, h);
            }
            getTooltipHTML(data, idx) {
                return '<span style="color:#3B82F6">K ' + (k[idx]!=null?k[idx].toFixed(1):'-') + '</span> <span style="color:#F59E0B">D ' + (d[idx]!=null?d[idx].toFixed(1):'-') + '</span> <span style="color:#A78BFA">J ' + (j[idx]!=null?j[idx].toFixed(1):'-') + '</span>';
            }
        })();
    }

    getLegend() { return '<span style="color:#3B82F6">K</span> <span style="color:#F59E0B">D</span> <span style="color:#A78BFA">J</span>'; }
}

// Register with window for ChartRuntime
window.MainIndicator = MainIndicator;
window.VolumeIndicator = VolumeIndicator;
window.MACDIndicator = MACDIndicator;
window.RSIIndicator = RSIIndicator;
window.KDJIndicator = KDJIndicator;
`;
//# sourceMappingURL=chart-indicators.js.map