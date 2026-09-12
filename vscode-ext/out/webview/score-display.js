"use strict";
/** Display helpers for scores that may be unavailable. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.finiteScore = finiteScore;
exports.scoreText = scoreText;
exports.scoreTone = scoreTone;
function finiteScore(value) {
    if (value === null || value === undefined || value === '') {
        return null;
    }
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}
function scoreText(value, suffix = '') {
    const number = finiteScore(value);
    return number === null ? 'N/A' : `${number.toFixed(0)}${suffix}`;
}
function scoreTone(value) {
    const number = finiteScore(value);
    if (number === null)
        return 'neutral';
    return number >= 70 ? 'up' : number >= 50 ? 'warn' : 'down';
}
//# sourceMappingURL=score-display.js.map