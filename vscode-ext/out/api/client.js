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
exports.httpGet = httpGet;
exports.httpPost = httpPost;
exports.healthCheck = healthCheck;
exports.sleep = sleep;
const http = __importStar(require("http"));
const constants_1 = require("../constants");
function httpGet(path) {
    return new Promise((resolve, reject) => {
        http.get(constants_1.BASE_URL + path, res => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => { try {
                resolve(JSON.parse(d));
            }
            catch {
                resolve(d);
            } });
        }).on('error', reject);
    });
}
function httpPost(path, body) {
    return new Promise((resolve, reject) => {
        const bodyStr = body ? JSON.stringify(body) : '';
        const options = {
            method: 'POST',
            headers: body ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(bodyStr).toString() } : {},
        };
        const req = http.request(constants_1.BASE_URL + path, options, res => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => { try {
                resolve(JSON.parse(d));
            }
            catch {
                resolve(d);
            } });
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
        await httpGet('/system/health');
        return true;
    }
    catch {
        return false;
    }
}
function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
}
//# sourceMappingURL=client.js.map