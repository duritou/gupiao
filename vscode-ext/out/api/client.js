"use strict";
/** HTTP client for communicating with the Python backend. */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.HttpRequestError = exports.frontendRelease = void 0;
exports.releaseCompatibility = releaseCompatibility;
exports.httpGet = httpGet;
exports.httpPost = httpPost;
exports.healthCheck = healthCheck;
exports.healthCheckUrl = healthCheckUrl;
exports.sleep = sleep;
const http = __importStar(require("http"));
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const constants_1 = require("../constants");
const DEFAULT_GET_TIMEOUT_MS = 15_000;
const DEFAULT_POST_TIMEOUT_MS = 30_000;
const HEALTH_TIMEOUT_MS = 4_000;
const LIGHTWEIGHT_PROBE_TIMEOUT_MS = 2_000;
const releaseFile = path.join(__dirname, '../../release-info.json');
exports.frontendRelease = fs.existsSync(releaseFile)
    ? JSON.parse(fs.readFileSync(releaseFile, 'utf8')) : null;
async function releaseCompatibility() {
    if (!exports.frontendRelease)
        return { matches: false, message: '前端未通过统一发布流程构建' };
    const runtime = await httpGet('/system/runtime', 5_000);
    const matches = runtime.deployment_ready && !runtime.disk_drift
        && runtime.release_id === exports.frontendRelease.release_id
        && runtime.artifact_hash === exports.frontendRelease.backend_artifact_hash;
    return {
        matches: Boolean(matches),
        message: `前端 ${exports.frontendRelease.product_version} / ${exports.frontendRelease.release_id}\n`
            + `后端 ${runtime.product_version || '未知'} / ${runtime.release_id || '未托管'}\n`
            + (matches ? '发布一致' : '版本不一致：请安装本次 VSIX 并重新加载窗口'),
    };
}
class HttpRequestError extends Error {
    statusCode;
    responseBody;
    constructor(message, statusCode = 0, responseBody = '') {
        super(message);
        this.statusCode = statusCode;
        this.responseBody = responseBody;
        this.name = 'HttpRequestError';
    }
}
exports.HttpRequestError = HttpRequestError;
function parseResponse(path, statusCode, body) {
    if (statusCode < 200 || statusCode >= 300) {
        throw new HttpRequestError(`HTTP ${statusCode} for ${path}`, statusCode, body.slice(0, 500));
    }
    if (!body)
        return {};
    try {
        return JSON.parse(body);
    }
    catch {
        throw new HttpRequestError(`Invalid JSON response for ${path}`, statusCode, body.slice(0, 500));
    }
}
function httpGet(path, timeoutMs = DEFAULT_GET_TIMEOUT_MS) {
    return new Promise((resolve, reject) => {
        const req = http.get(constants_1.BASE_URL + path, res => {
            let body = '';
            res.setEncoding('utf8');
            res.on('data', chunk => body += chunk);
            res.on('end', () => {
                try {
                    resolve(parseResponse(path, res.statusCode || 0, body));
                }
                catch (error) {
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
function httpPost(path, body, timeoutMs = DEFAULT_POST_TIMEOUT_MS) {
    return releaseCompatibility().then(state => {
        if (!state.matches)
            throw new HttpRequestError(state.message);
        return postCompatible(path, body, timeoutMs);
    });
}
function postCompatible(path, body, timeoutMs) {
    return new Promise((resolve, reject) => {
        const bodyStr = body ? JSON.stringify(body) : '';
        const options = {
            method: 'POST',
            headers: body ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(bodyStr).toString() } : {},
        };
        const req = http.request(constants_1.BASE_URL + path, options, res => {
            let responseBody = '';
            res.setEncoding('utf8');
            res.on('data', chunk => responseBody += chunk);
            res.on('end', () => {
                try {
                    resolve(parseResponse(path, res.statusCode || 0, responseBody));
                }
                catch (error) {
                    reject(error);
                }
            });
        });
        req.setTimeout(timeoutMs, () => {
            req.destroy(new HttpRequestError(`Request timed out after ${timeoutMs}ms: ${path}`));
        });
        req.on('error', reject);
        if (bodyStr) {
            req.write(bodyStr);
        }
        req.end();
    });
}
async function healthCheck() {
    try {
        await httpGet('/system/health', HEALTH_TIMEOUT_MS);
        return true;
    }
    catch {
        // A busy backend can delay the JSON health route while Uvicorn is
        // already accepting requests.  openapi.json is a lightweight probe
        // that prevents a running system service from being shown as offline.
        const origin = constants_1.BASE_URL.replace(/\/api\/v1\/?$/, '');
        return healthCheckUrl(`${origin}/openapi.json`, LIGHTWEIGHT_PROBE_TIMEOUT_MS);
    }
}
function healthCheckUrl(url, timeoutMs = LIGHTWEIGHT_PROBE_TIMEOUT_MS) {
    return new Promise(resolve => {
        const req = http.get(url, res => {
            res.resume();
            resolve((res.statusCode || 500) < 400);
        });
        req.setTimeout(timeoutMs, () => { req.destroy(); resolve(false); });
        req.on('error', () => resolve(false));
    });
}
function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
}
//# sourceMappingURL=client.js.map