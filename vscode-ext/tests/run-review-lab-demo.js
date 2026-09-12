// Manual diagnostic artifact generator. Uses a fresh OS temporary directory only.
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { simulateReview } = require('../out/review-lab/simulation');
const { renderReview, parseArtifact } = require('../out/review-lab/model');

async function main() {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), 'adaptive-review-simulation-'));
    const date = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
    let checks = 0;
    const scenarios = {
        idle: () => 'idle', busy: () => 'busy', unknown: () => 'unknown',
        interrupted: () => ++checks === 3 ? 'busy' : 'idle',
    };
    const statuses = {};
    for (const [name, gate] of Object.entries(scenarios)) {
        const results = simulateReview(date, gate);
        const folder = path.join(root, name);
        await fs.mkdir(folder);
        for (const entry of results) {
            const file = path.join(folder, entry.project.replace('/', '__') + '.json');
            await fs.writeFile(file, JSON.stringify(entry, null, 2), { flag: 'wx' });
            parseArtifact(await fs.readFile(file, 'utf8'), date, entry.project);
        }
        await fs.writeFile(path.join(folder, 'preview.html'),
            renderReview(date, new Map(results.map(entry => [entry.project, entry]))), { flag: 'wx' });
        statuses[name] = results.map(entry => entry.status);
    }
    console.log(JSON.stringify({ root, date, synthetic_only: true, statuses }, null, 2));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
