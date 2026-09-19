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
            navItem('Task Monitor · 任务监控', 'quantai.taskmonitor', 'checklist'),
            navItem('Replay · 时间机器', 'quantai.replay', 'history'),
            navItem('公众号复盘 · 方法论', 'quantai.reviewLab', 'book'),
            navItem('System Health · 系统健康', 'quantai.health', 'pulse'),
            navItem('Data Connectors · 数据连接', 'quantai.connectors', 'plug'),
            navItem('Alert Center · 预警', 'quantai.alerts', 'bell'),
            navItem('Timeline · 评分演变', 'quantai.timeline', 'history'),
            navItem('Backtest · 策略验证', 'quantai.backtest', 'history'),
            navItem('Daily Brief · 日报', 'quantai.dailybrief', 'book'),
            navItem('+ 添加自选', 'quantai.addWatch', 'add'),
            navItem('重启后端服务', 'quantai.restartServer', 'debug-restart'),
        ];
    }
}
exports.TerminalNavProvider = TerminalNavProvider;
class StatusProvider {
    _onDidChangeTreeData = new vscode.EventEmitter();
    onDidChangeTreeData = this._onDidChangeTreeData.event;
    aiipOnline = null;
    healthFailureStreak = 0;
    /** The extension owns the single health probe; the sidebar only renders it. */
    setBackendOnline(online) {
        if (online) {
            this.healthFailureStreak = 0;
            if (this.aiipOnline === true)
                return;
            this.aiipOnline = true;
        }
        else {
            this.healthFailureStreak += 1;
            // Do not turn one slow probe into a false "not started" alarm.
            if (this.healthFailureStreak < 3)
                return;
            if (this.aiipOnline === false)
                return;
            this.aiipOnline = false;
        }
        this.refresh();
    }
    refresh() { this._onDidChangeTreeData.fire(); }
    dispose() {
        this._onDidChangeTreeData.dispose();
    }
    getTreeItem(el) { return el; }
    async getChildren() {
        const aiipOnline = this.aiipOnline === true;
        const aiipLabel = this.aiipOnline === null
            ? 'AIIP: 检测中'
            : aiipOnline ? 'AIIP: 运行中' : 'AIIP: 未启动';
        const aiipStatusItem = new vscode.TreeItem(aiipLabel);
        aiipStatusItem.iconPath = new vscode.ThemeIcon(this.aiipOnline === null ? 'sync~spin' : aiipOnline ? 'check' : 'circle-outline');
        const apiItem = new vscode.TreeItem(`API: ${constants_1.BASE_URL}`);
        apiItem.iconPath = new vscode.ThemeIcon('server');
        const aiipRestartItem = new vscode.TreeItem('重启 AIIP 后端', vscode.TreeItemCollapsibleState.None);
        aiipRestartItem.iconPath = new vscode.ThemeIcon('debug-restart');
        aiipRestartItem.command = { command: 'quantai.restartServer', title: '重启 AIIP 后端' };
        aiipRestartItem.tooltip = '杀掉旧进程并重启 AIIP 后端服务';
        return [
            aiipStatusItem,
            apiItem,
            aiipRestartItem,
        ];
    }
}
exports.StatusProvider = StatusProvider;
//# sourceMappingURL=providers.js.map