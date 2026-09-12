export type PageCacheEntry = {
    data?: any;
    fetchedAt: number;
    lastSuccessfulAt?: number;
    retryAfter?: number;
    pending?: Promise<any>;
};

export const PAGE_RETRY_COOLDOWN_MS = 5_000;

export function isPageDataError(data: any): boolean {
    return Boolean(data?.pageError || data?.aiosError);
}

export function cachePageResult(
    previous: PageCacheEntry | undefined,
    result: any,
    now: number,
    retryCooldownMs = PAGE_RETRY_COOLDOWN_MS,
): PageCacheEntry {
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
