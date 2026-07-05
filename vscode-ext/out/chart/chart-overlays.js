"use strict";
/**
 * Overlay system — AI signals rendered directly on the chart.
 *
 * Each overlay is a visual layer on top of the main candlestick panel.
 * Overlays can be: AI buy/sell markers, support/resistance lines,
 * backtest trade arrows, AI recommendation badges, trend lines.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.OVERLAYS_JS = void 0;
exports.OVERLAYS_JS = `
// ============================================================
// 1. BuySignalOverlay — green up-arrow at AI buy signal
// ============================================================
class BuySignalOverlay extends Overlay {
    constructor(signals) {
        super('buysignals', 'AI Buy Signals', PRIORITY.BUY_SELL);
        this.signals = signals || [];  // [{date, price, score, evidence:[]}]
    }

    render(ctx, chart, data, startIdx, endIdx, xScale, yScale, chartX, chartY, chartW, chartH) {
        for (const s of this.signals) {
            const idx = data.findIndex(d => d.date >= s.date);
            if (idx < startIdx || idx > endIdx) continue;
            const x = xScale(idx);
            const y = yScale(s.price || data[idx].low);

            // Arrow body
            ctx.fillStyle = C.overlayBuy;
            ctx.beginPath();
            ctx.moveTo(x, y - 14);
            ctx.lineTo(x + 7, y - 4);
            ctx.lineTo(x - 7, y - 4);
            ctx.closePath();
            ctx.fill();

            // Score badge
            ctx.fillStyle = C.panelBg;
            ctx.strokeStyle = C.up;
            ctx.lineWidth = 1;
            const badgeW = 32, badgeH = 14;
            ctx.beginPath();
            ctx.roundRect(x - badgeW/2, y - 32, badgeW, badgeH, 4);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = C.up;
            ctx.font = 'bold 9px JetBrains Mono, monospace';
            ctx.textAlign = 'center';
            ctx.fillText((s.score || 0).toFixed(0), x, y - 21);
        }
    }

    hitTest(mx, my, chart, data, startIdx, endIdx, xScale, yScale) {
        for (const s of this.signals) {
            const idx = data.findIndex(d => d.date >= s.date);
            if (idx < startIdx || idx > endIdx) continue;
            const x = xScale(idx);
            const y = yScale(s.price || data[idx].low);
            if (Math.abs(mx - x) < 14 && Math.abs(my - (y - 20)) < 20) {
                return { overlay: this, signal: s, index: idx };
            }
        }
        return null;
    }

    getTooltip(hit) {
        const s = hit.signal;
        let html = '<div style="font-size:12px;font-weight:700;color:#22C55E">AI Buy Signal</div>';
        html += '<div style="font-size:10px;color:#9CA3AF;margin-top:2px">Score ' + (s.score||0).toFixed(0) + '</div>';
        if (s.evidence && s.evidence.length > 0) {
            html += '<div style="margin-top:6px;border-top:1px solid #1F2937;padding-top:4px">';
            for (const e of s.evidence.slice(0, 3)) {
                html += '<div style="font-size:10px;padding:2px 0">' + (e.icon==='check'?'✓':'•') + ' ' + e.title + ' <span style="color:#22C55E">' + (e.credibility*100).toFixed(0) + '%</span></div>';
            }
            html += '</div>';
        }
        return html;
    }
}

// ============================================================
// 2. SellSignalOverlay — red down-arrow at sell signal
// ============================================================
class SellSignalOverlay extends Overlay {
    constructor(signals) {
        super('sellsignals', 'AI Sell Signals', PRIORITY.BUY_SELL);
        this.signals = signals || [];
    }

    render(ctx, chart, data, startIdx, endIdx, xScale, yScale, chartX, chartY, chartW, chartH) {
        for (const s of this.signals) {
            const idx = data.findIndex(d => d.date >= s.date);
            if (idx < startIdx || idx > endIdx) continue;
            const x = xScale(idx);
            const y = yScale(s.price || data[idx].high);

            ctx.fillStyle = C.overlaySell;
            ctx.beginPath();
            ctx.moveTo(x, y + 14);
            ctx.lineTo(x + 7, y + 4);
            ctx.lineTo(x - 7, y + 4);
            ctx.closePath();
            ctx.fill();

            ctx.fillStyle = C.panelBg;
            ctx.strokeStyle = C.down;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.roundRect(x - 16, y + 18, 32, 14, 4);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = C.down;
            ctx.font = 'bold 9px JetBrains Mono';
            ctx.textAlign = 'center';
            ctx.fillText((s.score || 0).toFixed(0), x, y + 29);
        }
    }

    hitTest(mx, my, chart, data, startIdx, endIdx, xScale, yScale) {
        for (const s of this.signals) {
            const idx = data.findIndex(d => d.date >= s.date);
            if (idx < startIdx || idx > endIdx) continue;
            const x = xScale(idx), y = yScale(s.price || data[idx].high);
            if (Math.abs(mx - x) < 14 && Math.abs(my - (y + 20)) < 20) {
                return { overlay: this, signal: s, index: idx };
            }
        }
        return null;
    }

    getTooltip(hit) {
        const s = hit.signal;
        let html = '<div style="font-size:12px;font-weight:700;color:#EF4444">Sell Signal</div>';
        html += '<div style="font-size:10px;color:#9CA3AF">Score ' + (s.score||0).toFixed(0) + '</div>';
        return html;
    }
}

// ============================================================
// 3. SupportLineOverlay — horizontal dashed line at support
// ============================================================
class SupportLineOverlay extends Overlay {
    constructor(lines) {
        super('supportlines', 'Support Lines', PRIORITY.SUPPORT);
        this.lines = lines || [];  // [{price, label, confidence, reason}]
    }

    render(ctx, chart, data, startIdx, endIdx, xScale, yScale, chartX, chartY, chartW, chartH) {
        for (const l of this.lines) {
            const y = yScale(l.price);
            ctx.strokeStyle = C.overlaySupport;
            ctx.lineWidth = 1.5;
            ctx.setLineDash([6, 4]);
            ctx.beginPath();
            ctx.moveTo(chartX, y);
            ctx.lineTo(chartX + chartW, y);
            ctx.stroke();
            ctx.setLineDash([]);

            // Label
            ctx.fillStyle = C.overlaySupport;
            ctx.font = 'bold 10px sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(l.label || 'S', chartX + 4, y - 4);

            // Price
            ctx.fillStyle = C.panelBg;
            ctx.fillRect(chartX + chartW - 56, y - 9, 52, 16);
            ctx.fillStyle = C.overlaySupport;
            ctx.font = '10px JetBrains Mono';
            ctx.textAlign = 'right';
            ctx.fillText(l.price.toFixed(2), chartX + chartW - 6, y + 3);
        }
    }

    hitTest(mx, my, chart, data, startIdx, endIdx, xScale, yScale) {
        for (const l of this.lines) {
            const y = yScale(l.price);
            if (Math.abs(my - y) < 8) {
                return { overlay: this, line: l };
            }
        }
        return null;
    }

    getTooltip(hit) {
        const l = hit.line;
        return '<div style="font-size:12px;font-weight:700;color:#F97316">Support ' + l.price.toFixed(2) + '</div>' +
               '<div style="font-size:10px;color:#9CA3AF;margin-top:2px">' + (l.reason || '') + '</div>' +
               '<div style="font-size:10px;color:#9CA3AF">Confidence ' + ((l.confidence||0)*100).toFixed(0) + '%</div>';
    }
}

// ============================================================
// 4. AIRecommendationOverlay — star badge + label
// ============================================================
class AIRecommendationOverlay extends Overlay {
    constructor(recommendations) {
        super('airec', 'AI Recommendations', PRIORITY.AI_REC);
        this.recommendations = recommendations || [];  // [{date, score, direction, reason}]
    }

    render(ctx, chart, data, startIdx, endIdx, xScale, yScale, chartX, chartY, chartW, chartH) {
        for (const rec of this.recommendations) {
            const idx = data.findIndex(d => d.date >= rec.date);
            if (idx < startIdx || idx > endIdx) continue;
            const x = xScale(idx);
            const y = yScale(data[idx].high);

            // Star
            ctx.fillStyle = C.aiPurple;
            ctx.font = '16px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('★', x, y - 20);

            // Glow
            ctx.fillStyle = C.aiBg;
            ctx.beginPath();
            ctx.arc(x, y - 20, 12, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = C.aiPurple;
            ctx.font = '16px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('★', x, y - 20);
        }
    }

    hitTest(mx, my, chart, data, startIdx, endIdx, xScale, yScale) {
        for (const rec of this.recommendations) {
            const idx = data.findIndex(d => d.date >= rec.date);
            if (idx < startIdx || idx > endIdx) continue;
            const x = xScale(idx), y = yScale(data[idx].high);
            if (Math.abs(mx - x) < 14 && Math.abs(my - (y - 20)) < 14) {
                return { overlay: this, rec, index: idx };
            }
        }
        return null;
    }

    getTooltip(hit) {
        const r = hit.rec;
        return '<div style="font-size:12px;font-weight:700;color:#7C3AED">★ AI Recommendation</div>' +
               '<div style="font-size:14px;font-weight:700;color:' + (r.direction==='buy'?C.up:C.down) + ';margin-top:4px">' + (r.score||0).toFixed(0) + ' · ' + (r.direction||'neutral').toUpperCase() + '</div>' +
               '<div style="font-size:10px;color:#9CA3AF;margin-top:4px">' + (r.reason || '') + '</div>';
    }
}

// ============================================================
// 5. BacktestTradeOverlay — buy/sell arrows with P&L
// ============================================================
class BacktestTradeOverlay extends Overlay {
    constructor(trades) {
        super('backtest', 'Backtest Trades', PRIORITY.BACKTEST);
        this.trades = trades || [];  // [{entryDate, entryPrice, exitDate, exitPrice, profitPct, holdingDays}]
    }

    render(ctx, chart, data, startIdx, endIdx, xScale, yScale, chartX, chartY, chartW, chartH) {
        for (const t of this.trades) {
            const entryIdx = data.findIndex(d => d.date >= t.entryDate);
            const exitIdx = data.findIndex(d => d.date >= t.exitDate);
            const isWin = (t.profitPct || 0) >= 0;

            // Entry marker
            if (entryIdx >= startIdx && entryIdx <= endIdx) {
                const x = xScale(entryIdx);
                const y = yScale(t.entryPrice || data[entryIdx].low);
                ctx.fillStyle = isWin ? C.up : C.down;
                ctx.beginPath();
                ctx.moveTo(x, y + 10);
                ctx.lineTo(x + 6, y + 2);
                ctx.lineTo(x - 6, y + 2);
                ctx.closePath();
                ctx.fill();
                ctx.fillStyle = isWin ? C.up : C.down;
                ctx.font = 'bold 8px JetBrains Mono';
                ctx.textAlign = 'center';
                ctx.fillText('B', x, y + 22);
            }

            // Exit marker
            if (exitIdx >= startIdx && exitIdx <= endIdx) {
                const x = xScale(exitIdx);
                const y = yScale(t.exitPrice || data[exitIdx].high);
                ctx.fillStyle = isWin ? C.up : C.down;
                ctx.beginPath();
                ctx.moveTo(x, y - 10);
                ctx.lineTo(x + 6, y - 2);
                ctx.lineTo(x - 6, y - 2);
                ctx.closePath();
                ctx.fill();
                ctx.fillStyle = isWin ? C.up : C.down;
                ctx.font = 'bold 8px JetBrains Mono';
                ctx.textAlign = 'center';
                ctx.fillText('S', x, y - 14);
            }

            // Connecting line and P&L label if both visible
            if (entryIdx >= startIdx && exitIdx <= endIdx) {
                const x1 = xScale(entryIdx), x2 = xScale(exitIdx);
                const y1 = yScale(t.entryPrice || data[entryIdx].low);
                const midX = (x1 + x2) / 2;

                ctx.strokeStyle = isWin ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)';
                ctx.lineWidth = 1;
                ctx.setLineDash([2, 4]);
                ctx.beginPath();
                ctx.moveTo(x1, y1 + 10);
                ctx.lineTo(midX, y1 + 10);
                ctx.lineTo(midX, y1 - 20);
                ctx.stroke();
                ctx.setLineDash([]);

                ctx.fillStyle = C.panelBg;
                ctx.fillRect(midX - 40, y1 - 32, 80, 18);
                ctx.fillStyle = isWin ? C.up : C.down;
                ctx.font = 'bold 10px JetBrains Mono';
                ctx.textAlign = 'center';
                ctx.fillText((isWin ? '+' : '') + (t.profitPct||0).toFixed(1) + '% · ' + (t.holdingDays||0) + 'd', midX, y1 - 18);
            }
        }
    }

    hitTest(mx, my, chart, data, startIdx, endIdx, xScale, yScale) {
        for (const t of this.trades) {
            const idx = data.findIndex(d => d.date >= t.entryDate);
            if (idx < startIdx || idx > endIdx) continue;
            const x = xScale(idx), y = yScale(t.entryPrice || data[idx].low);
            if (Math.abs(mx - x) < 20 && Math.abs(my - y) < 30) {
                return { overlay: this, trade: t };
            }
        }
        return null;
    }

    getTooltip(hit) {
        const t = hit.trade;
        return '<div style="font-size:12px;font-weight:700;color:' + ((t.profitPct||0)>=0?C.up:C.down) + '">Backtest Trade</div>' +
               '<div style="display:grid;grid-template-columns:40px 1fr;gap:2px 8px;font-size:10px;margin-top:4px">' +
               '<span style="color:#9CA3AF">Entry</span><span>' + t.entryDate + ' @ ' + (t.entryPrice||0).toFixed(2) + '</span>' +
               '<span style="color:#9CA3AF">Exit</span><span>' + t.exitDate + ' @ ' + (t.exitPrice||0).toFixed(2) + '</span>' +
               '<span style="color:#9CA3AF">P&L</span><span style="color:' + ((t.profitPct||0)>=0?C.up:C.down) + '">' + ((t.profitPct||0)>=0?'+':'') + (t.profitPct||0).toFixed(1) + '%</span>' +
               '<span style="color:#9CA3AF">Held</span><span>' + (t.holdingDays||0) + ' days</span>' +
               '</div>';
    }
}

window.BuySignalOverlay = BuySignalOverlay;
window.SellSignalOverlay = SellSignalOverlay;
window.SupportLineOverlay = SupportLineOverlay;
window.AIRecommendationOverlay = AIRecommendationOverlay;
window.BacktestTradeOverlay = BacktestTradeOverlay;
`;
//# sourceMappingURL=chart-overlays.js.map