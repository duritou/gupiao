"use strict";
/** Sidebar tree data providers. */
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
exports.StatusProvider = exports.TerminalNavProvider = void 0;
const vscode = __importStar(require("vscode"));
const client_1 = require("../api/client");
const constants_1 = require("../constants");
function navItem(label, cmd, icon) {
    const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
    if (cmd) {
        item.command = { command: cmd, title: label };
    }
    if (icon) {
        item.iconPath = new vscode.ThemeIcon(icon);
    }
    return item;
}
class TerminalNavProvider {
    getTreeItem(el) { return el; }
    getChildren() {
        return [
            navItem('Dashboard · 首页总览', 'quantai.dashboard', 'dashboard'),
            navItem('Decision Center · 决策中心', 'quantai.decisions', 'target'),
            navItem('Portfolio · 持仓中心', 'quantai.portfolio', 'account'),
            navItem('Watchlist · 自选股', 'quantai.watchlist', 'list-tree'),
            navItem('Decision Journal · 决策日志', 'quantai.journal', 'notebook'),
            navItem('AI Resume · 信任档案', 'quantai.resume', 'verified'),
            navItem('AI Profile · 投资画像', 'quantai.profile', 'person'),
            navItem('AI OS · 系统运行', 'quantai.aios', 'pulse'),
            navItem('Replay · 时间机器', 'quantai.replay', 'history'),
            navItem('System Health · 系统健康', 'quantai.health', ' pulse'),
            navItem('Data Connectors · 数据连接', 'quantai.connectors', 'plug'),
            navItem('', '', ''),
            navItem('Alert Center · 预警', 'quantai.alerts', 'bell'),
            navItem('Market Map · 行业热力图', 'quantai.marketmap', 'graph'),
            navItem('Compare · 股票对比', 'quantai.compare', 'symbol-numeric'),
            navItem('Timeline · 评分演变', 'quantai.timeline', 'timeline'),
            navItem('Backtest · 策略验证', 'quantai.backtest', 'history'),
            navItem('Daily Brief · 日报', 'quantai.dailybrief', 'book'),
            navItem('', '', ''),
            navItem('分析股票...', 'quantai.research', 'search'),
            navItem('+ 添加自选', 'quantai.addWatch', 'add'),
        ];
    }
}
exports.TerminalNavProvider = TerminalNavProvider;
class StatusProvider {
    getTreeItem(el) { return el; }
    async getChildren() {
        const online = await (0, client_1.healthCheck)().catch(() => false);
        return [
            new vscode.TreeItem(online ? '$(check) 后端: 运行中' : '$(circle-outline) 后端: 未启动'),
            new vscode.TreeItem(`$(server) API: ${constants_1.BASE_URL}`),
        ];
    }
}
exports.StatusProvider = StatusProvider;
//# sourceMappingURL=providers.js.map