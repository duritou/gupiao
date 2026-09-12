/** HTTP client for communicating with the Python backend. */

import * as http from 'http';
import * as fs from 'fs';
import * as path from 'path';
import { BASE_URL } from '../constants';

const DEFAULT_GET_TIMEOUT_MS = 15_000;
const DEFAULT_POST_TIMEOUT_MS = 30_000;
const HEALTH_TIMEOUT_MS = 4_000;
const LIGHTWEIGHT_PROBE_TIMEOUT_MS = 2_000;
const releaseFile = path.join(__dirname, '../../release-info.json');
export const frontendRelease = fs.existsSync(releaseFile)
    ? JSON.parse(fs.readFileSync(releaseFile, 'utf8')) : null;

export async function releaseCompatibility(): Promise<{ matches: boolean; message: string }> {
    if (!frontendRelease) return { matches: false, message: '前端未通过统一发布流程构建' };
    const runtime = await httpGet('/system/runtime', 5_000);
    const matches = runtime.deployment_ready && !runtime.disk_drift
        && runtime.release_id === frontendRelease.release_id
        && runtime.artifact_hash === frontendRelease.backend_artifact_hash;
    return {
        matches: Boolean(matches),
        message: `前端 ${frontendRelease.product_version} / ${frontendRelease.release_id}\n`
            + `后端 ${runtime.product_version || '未知'} / ${runtime.release_id || '未托管'}\n`
            + (matches ? '发布一致' : '版本不一致：请安装本次 VSIX 并重新加载窗口'),
    };
}

export class HttpRequestError extends Error {
    constructor(
        message: string,
        public readonly statusCode = 0,
        public readonly responseBody = '',
    ) {
        super(message);
        this.name = 'HttpRequestError';
    }
}

function parseResponse(path: string, statusCode: number, body: string): any {
    if (statusCode < 200 || statusCode >= 300) {
        throw new HttpRequestError(
            `HTTP ${statusCode} for ${path}`,
            statusCode,
            body.slice(0, 500),
        );
    }
    if (!body) return {};
    try {
        return JSON.parse(body);
    } catch {
        throw new HttpRequestError(`Invalid JSON response for ${path}`, statusCode, body.slice(0, 500));
    }
}

export function httpGet(path: string, timeoutMs = DEFAULT_GET_TIMEOUT_MS): Promise<any> {
    return new Promise((resolve, reject) => {
        const req = http.get(BASE_URL + path, res => {
            let body = '';
            res.setEncoding('utf8');
            res.on('data', chunk => body += chunk);
            res.on('end', () => {
                try {
                    resolve(parseResponse(path, res.statusCode || 0, body));
                } catch (error) {
                    reject(error);
                }
            });
        });
        req.setTimeout(timeoutMs, () => {
            req.destroy(new HttpRequestError(`Request timed out after ${timeoutMs}ms: ${path}`));
        });
        req.on('error', reject);
    });
}

export function httpPost(path: string, body?: any, timeoutMs = DEFAULT_POST_TIMEOUT_MS): Promise<any> {
    return releaseCompatibility().then(state => {
        if (!state.matches) throw new HttpRequestError(state.message);
        return postCompatible(path, body, timeoutMs);
    });
}

function postCompatible(path: string, body: any, timeoutMs: number): Promise<any> {
    return new Promise((resolve, reject) => {
        const bodyStr = body ? JSON.stringify(body) : '';
        const options: http.RequestOptions = {
            method: 'POST',
            headers: body ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(bodyStr).toString() } : {},
        };
        const req = http.request(BASE_URL + path, options, res => {
            let responseBody = '';
            res.setEncoding('utf8');
            res.on('data', chunk => responseBody += chunk);
            res.on('end', () => {
                try {
                    resolve(parseResponse(path, res.statusCode || 0, responseBody));
                } catch (error) {
                    reject(error);
                }
            });
        });
        req.setTimeout(timeoutMs, () => {
            req.destroy(new HttpRequestError(`Request timed out after ${timeoutMs}ms: ${path}`));
        });
        req.on('error', reject);
        if (bodyStr) { req.write(bodyStr); }
        req.end();
    });
}

export async function healthCheck(): Promise<boolean> {
    try {
        await httpGet('/system/health', HEALTH_TIMEOUT_MS);
        return true;
    } catch {
        // A busy backend can delay the JSON health route while Uvicorn is
        // already accepting requests.  openapi.json is a lightweight probe
        // that prevents a running system service from being shown as offline.
        const origin = BASE_URL.replace(/\/api\/v1\/?$/, '');
        return healthCheckUrl(`${origin}/openapi.json`, LIGHTWEIGHT_PROBE_TIMEOUT_MS);
    }
}

export function healthCheckUrl(url: string, timeoutMs = LIGHTWEIGHT_PROBE_TIMEOUT_MS): Promise<boolean> {
    return new Promise(resolve => {
        const req = http.get(url, res => {
            res.resume();
            resolve((res.statusCode || 500) < 400);
        });
        req.setTimeout(timeoutMs, () => { req.destroy(); resolve(false); });
        req.on('error', () => resolve(false));
    });
}

export function sleep(ms: number): Promise<void> {
    return new Promise(r => setTimeout(r, ms));
}
