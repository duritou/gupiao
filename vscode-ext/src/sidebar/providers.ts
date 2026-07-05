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
            navItem('Portfolio · 持仓中心', 'quantai.portfolio', 'account'),
            navItem('Watchlist · 自选股', 'quantai.watchlist', 'list-tree'),
            navItem('Decision Journal · 决策日志', 'quantai.journal', 'notebook'),
            navItem('AI Resume · 信任档案', 'quantai.resume', 'verified'),
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

export class StatusProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
    getTreeItem(el: vscode.TreeItem): vscode.TreeItem { return el; }
    async getChildren(): Promise<vscode.TreeItem[]> {
        const online = await healthCheck().catch(() => false);
        return [
            new vscode.TreeItem(online ? '$(check) 后端: 运行中' : '$(circle-outline) 后端: 未启动'),
            new vscode.TreeItem(`$(server) API: ${BASE_URL}`),
        ];
    }
}
