/** Sidebar tree data providers. */

import * as vscode from 'vscode';
import { healthCheck } from '../api/client';
import { BASE_URL } from '../constants';

function navItem(label: string, cmd: string, icon: string): vscode.TreeItem {
    const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
    if (cmd) { item.command = { command: cmd, title: label }; }
    if (icon) { item.iconPath = new vscode.ThemeIcon(icon); }
    return item;
}

export class TerminalNavProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
    getTreeItem(el: vscode.TreeItem): vscode.TreeItem { return el; }
    getChildren(): vscode.TreeItem[] {
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
            navItem('测试复盘 · 仅供参考', 'quantai.reviewLab', 'beaker'),
            navItem('测试复盘 · 历史闭环结果', 'quantai.reviewLabHistorical', 'notebook'),
            navItem('System Health · 系统健康', 'quantai.health', 'pulse'),
            navItem('Data Connectors · 数据连接', 'quantai.connectors', 'plug'),
            navItem('Alert Center · 预警', 'quantai.alerts', 'bell'),
            navItem('Market Map · 行业热力图', 'quantai.marketmap', 'graph'),
            navItem('Compare · 股票对比', 'quantai.compare', 'symbol-numeric'),
            navItem('Timeline · 评分演变', 'quantai.timeline', 'history'),
            navItem('Backtest · 策略验证', 'quantai.backtest', 'history'),
            navItem('Daily Brief · 日报', 'quantai.dailybrief', 'book'),
            navItem('News Radar · 新闻雷达', 'quantai.newsradar', 'rss'),
            navItem('Research Reports · 研报管理', 'quantai.reports', 'file-text'),
            navItem('Announcements · 公告中心', 'quantai.announcements', 'megaphone'),
            navItem('Financials · 财务数据', 'quantai.financials', 'graph-line'),
            navItem('Valuation · 估值数据', 'quantai.valuation', 'symbol-misc'),
            navItem('Fund Flow · 资金流向', 'quantai.fundflow', 'arrow-both'),
            navItem('Dragon Tiger · 龙虎榜', 'quantai.dragonTiger', 'flame'),
            navItem('分析股票...', 'quantai.research', 'search'),
            navItem('+ 添加自选', 'quantai.addWatch', 'add'),
            navItem('重启后端服务', 'quantai.restartServer', 'debug-restart'),
        ];
    }
}

export class StatusProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
    private readonly _onDidChangeTreeData = new vscode.EventEmitter<
        vscode.TreeItem | undefined | null | void
    >();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
    private readonly _pollTimer: ReturnType<typeof setInterval>;
    private aiipOnline: boolean | null = null;
    private healthFailureStreak = 0;

    constructor() {
        this._pollTimer = setInterval(() => { void this.pollHealth(); }, 3000);
        void this.pollHealth();
    }

    refresh(): void { this._onDidChangeTreeData.fire(); }
    dispose(): void {
        clearInterval(this._pollTimer);
        this._onDidChangeTreeData.dispose();
    }

    private async pollHealth(): Promise<void> {
        const online = await healthCheck().catch(() => false);
        if (online) {
            this.healthFailureStreak = 0;
            if (this.aiipOnline === true) return;
            this.aiipOnline = true;
        } else {
            this.healthFailureStreak += 1;
            // Do not turn one slow probe into a false "not started" alarm.
            if (this.healthFailureStreak < 3) return;
            if (this.aiipOnline === false) return;
            this.aiipOnline = false;
        }
        this.refresh();
    }

    getTreeItem(el: vscode.TreeItem): vscode.TreeItem { return el; }
    async getChildren(): Promise<vscode.TreeItem[]> {
        if (this.aiipOnline === null) await this.pollHealth();
        const aiipOnline = this.aiipOnline === true;
        const aiipLabel = this.aiipOnline === null
            ? 'AIIP: 检测中'
            : aiipOnline ? 'AIIP: 运行中' : 'AIIP: 未启动';

        const aiipStatusItem = new vscode.TreeItem(aiipLabel);
        aiipStatusItem.iconPath = new vscode.ThemeIcon(
            this.aiipOnline === null ? 'sync~spin' : aiipOnline ? 'check' : 'circle-outline',
        );

        const apiItem = new vscode.TreeItem(`API: ${BASE_URL}`);
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
