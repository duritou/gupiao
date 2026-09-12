import * as fs from 'fs/promises';
import * as path from 'path';
import * as vscode from 'vscode';
import { parseArtifact, renderReview, REVIEW_PROJECTS, ReviewArtifact, validDate } from './model';
import { simulateReview } from './simulation';
import { httpGet } from '../api/client';
import { escapeHtml } from './model';

const RUN_ID_PATTERN = /^friday-[a-f0-9]{32}$/;
const RESULT_LIMIT_BYTES = 65536;

function localReviewRoot(): string | null {
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    return folder ? path.join(folder, 'runtime', 'adaptive-review-lab') : null;
}

async function localRunIds(): Promise<string[]> {
    const root = localReviewRoot();
    if (!root) return [];
    try {
        const entries = await fs.readdir(root, { withFileTypes: true });
        const runs = await Promise.all(entries.filter(entry => RUN_ID_PATTERN.test(entry.name)
            && entry.isDirectory()).map(async entry => ({
            name: entry.name,
            modified: (await fs.stat(path.join(root, entry.name))).mtimeMs,
        })));
        return runs.sort((left, right) => right.modified - left.modified).map(run => run.name).slice(0, 50);
    } catch { return []; }
}

async function readLocalRun(runId: string): Promise<unknown | null> {
    const root = localReviewRoot();
    if (!root || !RUN_ID_PATTERN.test(runId)) return null;
    const file = path.join(root, runId, 'result.json');
    try {
        const info = await fs.lstat(file);
        if (!info.isFile() || info.isSymbolicLink() || info.size > RESULT_LIMIT_BYTES) return null;
        const handle = await fs.open(file, 'r');
        try {
            const buffer = Buffer.alloc(RESULT_LIMIT_BYTES + 1);
            const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
            if (bytesRead > RESULT_LIMIT_BYTES) return null;
            const result = JSON.parse(buffer.subarray(0, bytesRead).toString('utf8'));
            return result?.reference_only === true && result?.schema_version === 1 ? result : null;
        } finally { await handle.close(); }
    } catch { return null; }
}

export async function showHistoricalReview(context: vscode.ExtensionContext): Promise<void> {
    try {
        // Local-first prevents a slow/restarting API from making the command appear hung.
        let runs = await localRunIds();
        if (!runs.length) {
            const index = await httpGet('/review-lab/runs', 3000);
            runs = Array.isArray(index.runs)
                ? index.runs.filter((value: unknown) => typeof value === 'string' && RUN_ID_PATTERN.test(value)) : [];
        }
        if (!runs.length) { vscode.window.showInformationMessage('暂无隔离历史复盘结果'); return; }
        const runId = await vscode.window.showQuickPick(runs, { title: '选择测试复盘（最新在前）' });
        if (!runId || !RUN_ID_PATTERN.test(runId)) return;
        const result = await readLocalRun(runId) ?? await httpGet(`/review-lab/runs/${runId}`, 3000);
        const panel = vscode.window.createWebviewPanel(
            'quantaiReviewLabHistorical', '测试复盘 · 真实历史 / 模拟成交', vscode.ViewColumn.Beside,
            { enableScripts: false, localResourceRoots: [] },
        );
        context.subscriptions.push(panel);
        panel.webview.html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
            <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
            <style>body{padding:24px;color:var(--vscode-foreground);background:var(--vscode-editor-background)}
            pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body>
            <h1>真实历史数据 · 独立模拟交易与学习记录</h1>
            <p>仅供参考。成交为模型假设，不是真实订单。学习为本地总结，不是 AI 训练。
            本次是共同的闭环验证，尚未执行七个上游项目。</p>
            <pre>${escapeHtml(JSON.stringify(result, null, 2))}</pre></body></html>`;
    } catch (error) {
        const message = error instanceof Error ? error.message : '未知错误';
        vscode.window.showErrorMessage(`测试复盘读取失败（未执行任何交易）：${message}`);
    }
}

/** Explicit manual demo: memory-only, never published as daily results. */
export function showReviewSimulation(context: vscode.ExtensionContext): void {
    const date = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
    const entries = new Map(simulateReview(date, () => 'idle').map(entry => [entry.project, entry]));
    const panel = vscode.window.createWebviewPanel(
        'quantaiReviewLabSimulation', '测试复盘 · 合成模拟', vscode.ViewColumn.Beside,
        { enableScripts: false, localResourceRoots: [] },
    );
    context.subscriptions.push(panel);
    panel.webview.html = renderReview(date, entries);
}

/** Deliberately separate from the main panel and backend lifecycle. */
export async function showReviewLab(context: vscode.ExtensionContext): Promise<void> {
    const today = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    }).format(new Date());
    const date = await vscode.window.showInputBox({
        title: '测试复盘：选择结果日期', value: today,
        validateInput: value => validDate(value) ? null : '日期格式应为 YYYY-MM-DD',
    });
    if (!date || !validDate(date)) return;
    const root = path.join(context.globalStorageUri.fsPath, 'review-lab', 'results', date);
    const entries = new Map<string, ReviewArtifact | string>();
    // Serial, bounded reads; never read the production DB or fetch missing data.
    for (const project of REVIEW_PROJECTS) {
        const file = path.join(root, project.replace('/', '__') + '.json');
        let handle: fs.FileHandle | undefined;
        try {
            const info = await fs.lstat(file);
            if (!info.isFile() || info.isSymbolicLink() || info.size > 65536) {
                throw new Error('结果文件不是普通文件或超过 64 KiB');
            }
            handle = await fs.open(file, 'r');
            const buffer = Buffer.alloc(65537);
            const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
            if (bytesRead > 65536) throw new Error('结果文件超过 64 KiB');
            entries.set(project, parseArtifact(buffer.subarray(0, bytesRead).toString('utf8'), date, project));
        } catch (error) {
            if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
                entries.set(project, '结果无效或无法读取；未触发补采，也未使用其他日期结果替代。');
            }
        } finally {
            await handle?.close();
        }
    }
    const panel = vscode.window.createWebviewPanel(
        'quantaiReviewLab', `测试复盘 · ${date}`, vscode.ViewColumn.Beside,
        { enableScripts: false, localResourceRoots: [] },
    );
    context.subscriptions.push(panel);
    panel.webview.html = renderReview(date, entries);
}
