"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.PAGE_RETRY_COOLDOWN_MS = void 0;
exports.isPageDataError = isPageDataError;
exports.cachePageResult = cachePageResult;
exports.PAGE_RETRY_COOLDOWN_MS = 5_000;
function isPageDataError(data) {
    return Boolean(data?.pageError || data?.aiosError);
}
function cachePageResult(previous, result, now, retryCooldownMs = exports.PAGE_RETRY_COOLDOWN_MS) {
    if (isPageDataError(result)) {
        const lastSuccessfulAt = previous?.lastSuccessfulAt || previous?.fetchedAt || 0;
        return {
            data: {
                ...(previous?.data || {}),
                ...result,
                pageState: lastSuccessfulAt ? 'stale' : 'error',
                lastSuccessfulAt: lastSuccessfulAt ? new Date(lastSuccessfulAt).toISOString() : '',
            },
            fetchedAt: previous?.fetchedAt || 0,
            lastSuccessfulAt,
            retryAfter: now + retryCooldownMs,
        };
    }
    return {
        data: result,
        fetchedAt: now,
        lastSuccessfulAt: now,
    };
}
//# sourceMappingURL=page-cache.js.map