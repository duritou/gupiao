/** Display helpers for scores that may be unavailable. */

export function finiteScore(value: unknown): number | null {
    if (value === null || value === undefined || value === '') {
        return null;
    }
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}

export function scoreText(value: unknown, suffix = ''): string {
    const number = finiteScore(value);
    return number === null ? 'N/A' : `${number.toFixed(0)}${suffix}`;
}

export function scoreTone(value: unknown): 'up' | 'warn' | 'down' | 'neutral' {
    const number = finiteScore(value);
    if (number === null) return 'neutral';
    return number >= 70 ? 'up' : number >= 50 ? 'warn' : 'down';
}
