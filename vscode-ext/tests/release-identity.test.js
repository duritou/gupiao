const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');
const test = require('node:test');

function clientFor(runtime) {
    let writes = 0;
    const stamp = { release_id: 'release-A', backend_artifact_hash: 'hash-A', product_version: '1.1.6' };
    const fakeHttp = {
        get(_url, callback) {
            const response = new EventEmitter();
            response.statusCode = 200;
            response.setEncoding = () => {};
            callback(response);
            queueMicrotask(() => {
                response.emit('data', JSON.stringify(runtime));
                response.emit('end');
            });
            return { setTimeout() {}, on() {}, destroy() {} };
        },
        request() { writes++; throw new Error('unexpected mutation'); },
    };
    const exports = {};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../out/api/client.js'), 'utf8'), {
        exports, __dirname: path.join(__dirname, '../out/api'), Buffer,
        require(name) {
            if (name === 'http') return fakeHttp;
            if (name === 'fs') return { existsSync: () => true, readFileSync: () => JSON.stringify(stamp) };
            if (name === '../constants') return { BASE_URL: 'http://localhost/api/v1' };
            return require(name);
        },
    });
    return { client: exports, writes: () => writes };
}

test('same product version but different release blocks writes', async () => {
    const { client, writes } = clientFor({
        release_id: 'release-B', artifact_hash: 'hash-A', product_version: '1.1.6',
        deployment_ready: true, disk_drift: false,
    });
    await assert.rejects(client.httpPost('/tasks/execute/run_scanner'), /版本不一致/);
    assert.equal(writes(), 0);
});

test('matching release and artifact are reported as matched', async () => {
    const { client } = clientFor({
        release_id: 'release-A', artifact_hash: 'hash-A', deployment_ready: true, disk_drift: false,
    });
    assert.equal((await client.releaseCompatibility()).matches, true);
});
