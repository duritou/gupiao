/**
 * Research Timeline v1.0 — Interactive event timeline below chart.
 *
 * Shows all evidence events along the time axis:
 *   🔵 Signal events    🟢 AI buy recs    🔴 AI sell recs
 *   🟡 News/earnings    🟣 Knowledge       ⚪ Backtest trades
 *
 * Click any marker → chart crosshair jumps to date + evidence panel updates.
 */

export const TIMELINE_JS = `
// ============================================================
// Timeline — renders as a thin strip below the chart
// ============================================================

const TIMELINE_COLORS = {
    buy_signal:  '#22C55E',
    sell_signal: '#EF4444',
    support:     '#F97316',
    resistance:  '#3B82F6',
    ai_rec:      '#7C3AED',
    backtest:    '#F59E0B',
    news:        '#60A5FA',
    earnings:    '#EC4899',
    knowledge:   '#A78BFA',
    event:       '#9CA3AF',
};

const TIMELINE_ICONS = {
    buy_signal:  '▲',
    sell_signal: '▼',
    support:     '━',
    resistance:  '━',
    ai_rec:      '★',
    backtest:    '●',
    news:        '◆',
    earnings:    '⬟',
    knowledge:   '⬡',
    event:       '○',
};

class ResearchTimeline {
    constructor(containerId, runtime) {
        this.container = document.getElementById(containerId);
        this.runtime = runtime;
        if (!this.container || !this.runtime) return;

        this.margin = { top: 6, right: 8, bottom: 4, left: 8 };
        this.markerR = 5;
        this._needsResize = true;

        this.buildDOM();
        this.bindEvents();

        // Listen for evidence changes
        this.runtime.evidence.on('add', () => this.render());
        this.runtime.evidence.on('batch', () => this.render());
    }

    buildDOM() {
        this.container.innerHTML = '';
        this.container.style.cssText = 'position:relative;background:#111827;border:1px solid #1F2937;border-radius:6px;overflow:hidden;min-height:40px;cursor:pointer;';
        this.canvas = document.createElement('canvas');
        this.canvas.style.cssText = 'display:block;width:100%;height:100%;';
        this.container.appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d');

        // Tooltip
        this.tooltip = document.createElement('div');
        this.tooltip.style.cssText = 'position:absolute;top:-90px;left:8px;background:#111827;border:1px solid #1F2937;border-radius:6px;padding:8px 12px;font-size:11px;color:#F3F4F6;pointer-events:none;display:none;z-index:20;font-family:JetBrains Mono,sans-serif;min-width:180px;max-width:240px;box-shadow:0 4px 12px rgba(0,0,0,0.5);';
        this.container.appendChild(this.tooltip);
    }

    bindEvents() {
        this.canvas.addEventListener('mousemove', (e) => this._onMouseMove(e));
        this.canvas.addEventListener('mouseleave', () => {
            this.tooltip.style.display = 'none';
            this.render();
        });
        this.canvas.addEventListener('click', (e) => this._onClick(e));
        window.addEventListener('resize', () => { this._needsResize = true; this.render(); });
    }

    _resize() {
        const rect = this.container.getBoundingClientRect();
        this._needsResize = false;
        this._lastW = rect.width;
        this._lastH = rect.height;
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.canvas.style.width = rect.width + 'px';
        this.canvas.style.height = rect.height + 'px';
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    _onMouseMove(e) {
        const rect = this.canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const hit = this._hitTest(mx, my);
        if (hit) {
            this.tooltip.innerHTML = this._buildTooltip(hit);
            this.tooltip.style.display = 'block';
            this.tooltip.style.left = Math.min(mx + 8, rect.width - 200) + 'px';
            this._hoveredEv = hit;
        } else {
            this.tooltip.style.display = 'none';
            this._hoveredEv = null;
        }
        this.render();
    }

    _onClick(e) {
        const rect = this.canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const hit = this._hitTest(mx, my);
        if (hit) {
            // Navigate chart crosshair to this date
            const engine = this.runtime.engine;
            const idx = engine.data.findIndex(d => d.date >= hit.date);
            if (idx >= 0) {
                engine.crosshairIndex = idx;
                // Center view on this date
                const half = Math.floor((engine.visibleEnd - engine.visibleStart) / 2);
                engine.visibleStart = Math.max(0, idx - half);
                engine.visibleEnd = Math.min(engine.data.length - 1, idx + half);
                engine._updateTooltip(idx);
                engine.render(this.runtime.overlays);
            }
            // Fire callback
            if (this.onEventClick) this.onEventClick(hit);
        }
    }

    _hitTest(mx, my) {
        const allEvidence = this.runtime.evidence.getAll();
        if (allEvidence.length === 0) return null;
        const data = this.runtime.engine.data;
        if (data.length === 0) return null;
        const W = this._lastW;
        const H = this._lastH;
        const chartW = W - this.margin.left - this.margin.right;
        const count = data.length;
        const cs = chartW / count;
        const midY = H / 2;

        // Check each evidence position
        for (const ev of allEvidence) {
            const idx = data.findIndex(d => d.date >= ev.date);
            if (idx < 0) continue;
            const x = this.margin.left + idx * cs + cs / 2;
            if (Math.abs(mx - x) < this.markerR + 4 && Math.abs(my - midY) < this.markerR + 4) {
                return ev;
            }
        }
        return null;
    }

    _buildTooltip(ev) {
        const color = TIMELINE_COLORS[ev.type] || TIMELINE_COLORS.event;
        let html = '<div style="font-size:10px;color:#9CA3AF;margin-bottom:3px">' + ev.date + '</div>';
        html += '<div style="font-size:12px;font-weight:600;color:' + color + '">' + (ev.title || ev.type) + '</div>';
        if (ev.description) html += '<div style="font-size:10px;color:#9CA3AF;margin-top:2px">' + ev.description + '</div>';
        if (ev.score > 0) html += '<div style="font-size:10px;margin-top:2px">Score <span style="color:' + color + '">' + ev.score.toFixed(0) + '</span></div>';
        if (ev.confidence > 0) html += '<div style="font-size:10px;color:#9CA3AF">Confidence ' + (ev.confidence * 100).toFixed(0) + '%</div>';
        if (ev.source && ev.source.length) {
            html += '<div style="margin-top:4px;border-top:1px solid #1F2937;padding-top:3px;font-size:9px">';
            html += ev.source.map(s => '<span style="color:#58a6ff">' + s + '</span>').join(' · ');
            html += '</div>';
        }
        html += '<div style="font-size:9px;color:#6B7280;margin-top:3px">点击跳转到该日期</div>';
        return html;
    }

    // =========== RENDER ===========
    render() {
        if (this._needsResize) this._resize();
        const ctx = this.ctx;
        const W = this._lastW;
        const H = this._lastH;
        const m = this.margin;

        ctx.clearRect(0, 0, W * 2, H * 2);
        ctx.fillStyle = '#111827';
        ctx.fillRect(0, 0, W, H);

        const allEvidence = this.runtime.evidence.getAll();
        const data = this.runtime.engine.data;
        if (data.length === 0) return;
        const count = data.length;
        const chartW = W - m.left - m.right;
        const cs = chartW / count;
        const midY = H / 2;

        // Center line
        ctx.strokeStyle = '#1F2937';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(m.left, midY);
        ctx.lineTo(W - m.right, midY);
        ctx.stroke();

        // Date labels (sparse)
        ctx.fillStyle = '#6B7280';
        ctx.font = '8px sans-serif';
        ctx.textAlign = 'center';
        const labelStep = Math.max(1, Math.floor(count / 5));
        for (let i = 0; i < count; i += labelStep) {
            const x = m.left + i * cs + cs / 2;
            const ds = data[i].date.length >= 10 ? data[i].date.slice(5) : data[i].date;
            ctx.fillText(ds, x, H - 2);
        }

        // Evidence markers (grouped by date to avoid overlap)
        const dateGroups = {};
        for (const ev of allEvidence) {
            const key = ev.date;
            if (!dateGroups[key]) dateGroups[key] = [];
            dateGroups[key].push(ev);
        }

        for (const [date, events] of Object.entries(dateGroups)) {
            const idx = data.findIndex(d => d.date >= date);
            if (idx < 0) continue;
            const x = m.left + idx * cs + cs / 2;

            // Stack vertically if multiple events on same date
            const spacing = Math.min(12, (H - 12) / events.length);
            const totalH = events.length * spacing;
            const startY = midY - totalH / 2 + spacing / 2;

            events.forEach((ev, ei) => {
                const y = startY + ei * spacing;
                const color = TIMELINE_COLORS[ev.type] || TIMELINE_COLORS.event;
                const icon = TIMELINE_ICONS[ev.type] || TIMELINE_ICONS.event;
                const isHovered = this._hoveredEv === ev;

                // Glow for hovered
                if (isHovered) {
                    ctx.fillStyle = color + '33';
                    ctx.beginPath();
                    ctx.arc(x, y, this.markerR + 4, 0, Math.PI * 2);
                    ctx.fill();
                }

                // Marker circle
                ctx.fillStyle = color;
                ctx.beginPath();
                ctx.arc(x, y, this.markerR, 0, Math.PI * 2);
                ctx.fill();

                // Icon inside marker
                ctx.fillStyle = '#111827';
                ctx.font = '7px sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(icon, x, y);
            });
        }
    }

    /** Set callback when event marker is clicked */
    set onClick(fn) { this.onEventClick = fn; }
}

window.ResearchTimeline = ResearchTimeline;
window.TIMELINE_COLORS = TIMELINE_COLORS;
`;
