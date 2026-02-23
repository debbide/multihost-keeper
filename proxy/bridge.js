import path from 'path';
import { fileURLToPath } from 'url';
const logToStderr = (...args) => {
    const msg = args.map(a => (typeof a === 'string' ? a : JSON.stringify(a))).join(' ');
    process.stderr.write(msg + '\n');
};

console.log = logToStderr;
console.error = logToStderr;

const { ProxyService } = await import('./ProxyService.js');

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const action = process.argv[2];
const arg = process.argv[3];

const configDir = process.env.PROXY_CONFIG_DIR || path.join(__dirname, '..', 'data');
const service = new ProxyService(configDir);

const output = (obj) => {
    process.stdout.write(JSON.stringify(obj));
};

const fail = (message) => {
    output({ ok: false, error: message });
    process.exit(1);
};

const readStdin = async () => {
    return await new Promise((resolve, reject) => {
        let data = '';
        process.stdin.setEncoding('utf8');
        process.stdin.on('data', (chunk) => { data += chunk; });
        process.stdin.on('end', () => resolve(data));
        process.stdin.on('error', reject);
    });
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const main = async () => {
    try {
        if (!action) return fail('Missing action');

        if (action === 'parse') {
            const link = arg;
            if (!link) return fail('Missing link');
            const node = service.parseProxyLink(link);
            if (!node) return fail('Invalid proxy link');
            return output({ ok: true, node });
        }

        if (action === 'sync') {
            const url = arg;
            if (!url) return fail('Missing subscription url');
            const nodes = await service.syncSubscription(url);
            return output({ ok: true, nodes });
        }

        if (action === 'test') {
            let raw = arg;
            if (!raw) {
                raw = (await readStdin()).trim();
            }
            if (!raw) return fail('Missing node payload');
            let node;
            try {
                node = JSON.parse(raw);
            } catch (e) {
                return fail('Invalid node payload');
            }
            if (!node.id) {
                node.id = Math.random().toString(36).substring(2, 9);
            }
            service.setNodes([node]);
            await service.start();
            await sleep(800);
            const latency = await service.testNode(node.id);
            service.stop();
            return output({ ok: true, latency_ms: latency });
        }

        if (action === 'build-config') {
            let raw = arg;
            if (!raw) {
                raw = (await readStdin()).trim();
            }
            if (!raw) return fail('Missing nodes payload');
            let nodes;
            try {
                nodes = JSON.parse(raw);
            } catch (e) {
                return fail('Invalid nodes payload');
            }
            if (!Array.isArray(nodes)) {
                return fail('Nodes payload must be array');
            }
            service.setNodes(nodes);
            const config = service.generateConfig();
            return output({ ok: true, config });
        }

        return fail('Unknown action');
    } catch (e) {
        try {
            service.stop();
        } catch (_) {}
        return fail(e && e.message ? e.message : 'Unknown error');
    }
};

main();
