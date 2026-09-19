/** Sidebar tree data providers. */

import * as vscode from 'vscode';
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

export class StatusProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
    private readonly _onDidChangeTreeData = new vscode.EventEmitter<
        vscode.TreeItem | undefined | null | void
    >();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
    private aiipOnline: boolean | null = null;
    private healthFailureStreak = 0;

    /** The extension owns the single health probe; the sidebar only renders it. */
    setBackendOnline(online: boolean): void {
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

    refresh(): void { this._onDidChangeTreeData.fire(); }
    dispose(): void {
        this._onDidChangeTreeData.dispose();
    }

    getTreeItem(el: vscode.TreeItem): vscode.TreeItem { return el; }
    async getChildren(): Promise<vscode.TreeItem[]> {
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
