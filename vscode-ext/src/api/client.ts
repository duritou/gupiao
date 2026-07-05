/** HTTP client for communicating with the Python backend. */

import * as http from 'http';
import { BASE_URL } from '../constants';

export function httpGet(path: string): Promise<any> {
    return new Promise((resolve, reject) => {
        http.get(BASE_URL + path, res => {
            let d = ''; res.on('data', c => d += c);
            res.on('end', () => { try { resolve(JSON.parse(d)); } catch { resolve(d); } });
        }).on('error', reject);
    });
}

export function httpPost(path: string, body?: any): Promise<any> {
    return new Promise((resolve, reject) => {
        const bodyStr = body ? JSON.stringify(body) : '';
        const options: http.RequestOptions = {
            method: 'POST',
            headers: body ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(bodyStr).toString() } : {},
        };
        const req = http.request(BASE_URL + path, options, res => {
            let d = ''; res.on('data', c => d += c);
            res.on('end', () => { try { resolve(JSON.parse(d)); } catch { resolve(d); } });
        });
        req.on('error', reject);
        if (bodyStr) { req.write(bodyStr); }
        req.end();
    });
}

export async function healthCheck(): Promise<boolean> {
    try { await httpGet('/system/health'); return true; } catch { return false; }
}

export function sleep(ms: number): Promise<void> {
    return new Promise(r => setTimeout(r, ms));
}
