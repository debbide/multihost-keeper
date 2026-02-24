import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import axios from 'axios';
import { SocksProxyAgent } from 'socks-proxy-agent';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export class ProxyService {
    constructor(configDir = path.join(__dirname, 'data')) {
        this.proxyProcess = null;
        this.nodes = [];
        this.projectRoot = process.cwd();
        this.proxyListen = process.env.PROXY_LISTEN || '127.0.0.1';

        // Ensure data directory exists
        if (!fs.existsSync(configDir)) {
            fs.mkdirSync(configDir, { recursive: true });
        }

        this.configPath = path.join(configDir, 'proxy_config.json');
        console.log('[ProxyService] Initialized. CWD:', this.projectRoot, 'Config:', this.configPath);

        this.binPath = process.platform === 'win32' ? 'sing-box.exe' : 'sing-box';
        this.basePort = 20000;
        this.nodePortMap = new Map(); // nodeId -> localPort
    }

    setNodes(nodes) {
        this.nodes = nodes || [];
        this.updatePortMap();
    }

    updatePortMap() {
        this.nodePortMap.clear();
        const usedPorts = new Set();
        this.nodes.forEach((node, index) => {
            let desiredPort = null;
            if (node && node.local_port !== undefined && node.local_port !== null) {
                const parsed = parseInt(node.local_port);
                if (!isNaN(parsed) && parsed > 0) desiredPort = parsed;
            }

            if (!desiredPort || usedPorts.has(desiredPort)) {
                desiredPort = this.basePort + index;
                while (usedPorts.has(desiredPort)) {
                    desiredPort += 1;
                }
            }

            usedPorts.add(desiredPort);
            this.nodePortMap.set(node.id, desiredPort);
        });
    }

    getLocalPort(nodeId) {
        return this.nodePortMap.get(nodeId);
    }

    generateConfig() {
        const uuidRequired = new Set(['vmess', 'vless', 'tuic']);
        const isValidUuid = (value) => typeof value === 'string'
            && /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(value);

        const validNodes = (this.nodes || []).filter((node) => {
            if (!node) return false;
            if (uuidRequired.has(node.type)) {
                const uuid = node.uuid || '';
                if (!isValidUuid(uuid)) {
                    const label = node.name || node.id || node.type;
                    console.error(`[ProxyService] Skipping node ${label}: invalid uuid "${uuid}"`);
                    return false;
                }
            }
            return true;
        });

        this.nodes = validNodes;
        this.updatePortMap();
        const inbounds = validNodes.map((node, index) => ({
            type: 'socks',
            tag: `in-${node.id}`,
            listen: this.proxyListen,
            listen_port: this.nodePortMap.get(node.id) || (this.basePort + index)
        }));

        const outbounds = validNodes.map(node => {
            const outbound = {
                type: node.type,
                tag: `out-${node.id}`,
                server: node.server,
                server_port: node.port
            };

            if (node.password) outbound.password = node.password;

            if (node.uuid) {
                let uuid = node.uuid;
                if (uuid.includes('%3A') || uuid.includes(':')) {
                    uuid = decodeURIComponent(uuid).split(':')[0];
                }
                outbound.uuid = uuid;
            }

            if (node.type === 'vmess') {
                outbound.security = node.security || 'none';
                outbound.alter_id = parseInt(node.alterId || 0);
            } else if (node.type === 'shadowsocks') {
                outbound.method = node.method || 'aes-256-gcm';
            } else if (node.type === 'vless') {
                outbound.packet_encoding = node.packet_encoding || 'xudp';
            }

            const isTls = node.security === 'tls' || node.security === 'reality' || node.tls === true;

            if (isTls || node.sni) {
                outbound.tls = {
                    enabled: true,
                    server_name: node.sni || node.wsHost || node.server,
                    insecure: !!node.insecure
                };

                outbound.tls.utls = {
                    enabled: true,
                    fingerprint: node.fp || 'chrome'
                };

                if (node.record_fragment !== undefined) {
                    outbound.tls.record_fragment = !!node.record_fragment;
                }

                if (node.alpn) {
                    outbound.tls.alpn = Array.isArray(node.alpn) ? node.alpn : node.alpn.split(',');
                } else if (node.transport === 'ws') {
                    outbound.tls.alpn = ['http/1.1'];
                }

                if (node.security === 'reality') {
                    outbound.tls.reality = {
                        enabled: true,
                        public_key: node.pbk,
                        short_id: node.sid
                    };
                    if (node.spx) outbound.tls.reality.spider_x = node.spx;
                }
            }

            if (node.transport === 'ws') {
                let cleanPath = node.wsPath || '/';
                let maxEarlyData = node.max_early_data;

                if (cleanPath.includes('ed=')) {
                    try {
                        const match = cleanPath.match(/[?&]ed=(\d+)/);
                        if (match && match[1]) {
                            if (maxEarlyData === undefined) maxEarlyData = parseInt(match[1]);
                            cleanPath = cleanPath.replace(/[?&]ed=\d+/, '');
                            cleanPath = cleanPath.replace(/\?$/, '').replace(/&$/, '');
                            if (!cleanPath) cleanPath = '/';
                        }
                    } catch (e) { /* ignore parse error */ }
                }

                outbound.transport = {
                    type: 'ws',
                    path: cleanPath,
                    headers: {}
                };

                const hostHeader = node.wsHost || node.sni || node.server;
                if (hostHeader && !hostHeader.match(/^\d+\.\d+\.\d+\.\d+$/)) {
                    outbound.transport.headers['Host'] = hostHeader;
                    if (outbound.tls && !outbound.tls.server_name) {
                        outbound.tls.server_name = hostHeader;
                    }
                }

                if (maxEarlyData !== undefined) {
                    outbound.transport.max_early_data = parseInt(maxEarlyData);
                    outbound.transport.early_data_header_name = node.early_data_header_name || 'Sec-WebSocket-Protocol';
                }
            } else if (node.transport === 'grpc') {
                outbound.transport = {
                    type: 'grpc',
                    service_name: node.serviceName || ''
                };
            }

            if (node.type === 'vless' && node.flow) {
                outbound.flow = node.flow;
            }

            if (node.type === 'hysteria2') {
                outbound.password = node.password;
                if (node.obfs) {
                    outbound.obfs = {
                        type: node.obfs,
                        password: node.obfs_password || ''
                    };
                }
            }

            if (node.type === 'tuic') {
                outbound.uuid = node.uuid;
                outbound.password = node.password;
                outbound.congestion_control = node.congestion_control || 'bbr';
                outbound.udp_relay_mode = node.udp_relay_mode || 'quic-rfc';

                if (!outbound.tls) {
                    outbound.tls = {
                        enabled: true,
                        server_name: node.sni || node.server,
                        insecure: !!node.insecure
                    };
                    if (node.alpn) outbound.tls.alpn = Array.isArray(node.alpn) ? node.alpn : [node.alpn];
                }

                if (outbound.tls && outbound.tls.utls) delete outbound.tls.utls;
            }

            return outbound;
        });

        const routes = {
            rules: [
                {
                    ip_is_private: true,
                    outbound: 'direct'
                },
                ...validNodes.map(node => ({
                    inbound: [`in-${node.id}`],
                    outbound: `out-${node.id}`
                }))
            ],
            auto_detect_interface: true,
            final: 'direct'
        };

        return {
            log: { level: 'info' },
            inbounds,
            outbounds: [...outbounds, { type: 'direct', tag: 'direct' }],
            route: routes
        };
    }

    async start() {
        if (this.nodes.length === 0) {
            console.log('[ProxyService] No proxy nodes configured, skipping start.');
            return;
        }

        try {
            const config = this.generateConfig();

            // Safe logging without credentials
            const maskedConfig = JSON.parse(JSON.stringify(config));
            maskedConfig.outbounds?.forEach(o => {
                if (o.password) o.password = '***';
                if (o.uuid) o.uuid = '***';
                if (o.tls?.reality?.public_key) o.tls.reality.public_key = '***';
            });
            console.log('[ProxyService] Generated config:', JSON.stringify(maskedConfig, null, 2));

            fs.writeFileSync(this.configPath, JSON.stringify(config, null, 2));

            this.stop();

            // Setup sing-box executable
            let execPath = this.binPath;
            const possiblePaths = [
                path.join(this.projectRoot, 'bin', this.binPath),
                '/usr/bin/' + this.binPath,
                '/usr/local/bin/' + this.binPath,
                this.binPath
            ];

            for (const p of possiblePaths) {
                if (fs.existsSync(p)) {
                    execPath = p;
                    break;
                }
            }
            console.log(`[ProxyService] Final sing-box executable path: ${execPath}`);

            this.proxyProcess = spawn(execPath, ['run', '-c', this.configPath]);

            this.proxyProcess.stdout.on('data', (data) => console.log(`[Proxy Log] ${data.toString().trim()}`));
            this.proxyProcess.stderr.on('data', (data) => console.error(`[Proxy STDOUT/ERR] ${data.toString().trim()}`));
            this.proxyProcess.on('error', (err) => console.error(`[ProxyService] Failed to start sing-box process:`, err.message));

        } catch (err) {
            console.error('[ProxyService] Failed to start:', err.message);
        }
    }

    stop() {
        if (this.proxyProcess) {
            this.proxyProcess.kill();
            this.proxyProcess = null;
        }
    }

    async restart(nodes) {
        this.setNodes(nodes);
        await this.start();
    }

    parseProxyLink(link) {
        try {
            link = link.trim();
            if (link.startsWith('{') && link.endsWith('}')) return null;

            if (link.startsWith('vmess://')) {
                const b64 = link.replace('vmess://', '');
                const json = JSON.parse(Buffer.from(b64, 'base64').toString('utf-8'));
                return {
                    id: Math.random().toString(36).substring(2, 9),
                    name: json.ps || 'VMess',
                    type: 'vmess',
                    server: json.add,
                    port: parseInt(json.port),
                    uuid: json.id,
                    security: json.scy || 'auto',
                    alterId: parseInt(json.aid || 0),
                    transport: json.net === 'ws' ? 'ws' : (json.net === 'grpc' ? 'grpc' : 'tcp'),
                    wsPath: json.path || '',
                    wsHost: json.host || '',
                    tls: json.tls === 'tls',
                    sni: json.sni || json.host || ''
                };
            }

            const url = new URL(link);
            const protocol = url.protocol.slice(0, -1).toLowerCase();
            const nodeId = Math.random().toString(36).substring(2, 9);
            const name = decodeURIComponent(url.hash.slice(1)) || `${protocol}_${nodeId}`;
            const params = new URLSearchParams(url.search);

            let config = {
                id: nodeId, name: name, type: protocol,
                server: url.hostname, port: parseInt(url.port)
            };

            if (isNaN(config.port)) {
                config.port = (params.get('security') === 'tls' || params.get('tls') === '1') ? 443 : 80;
            }

            if (params.get('sni')) config.sni = params.get('sni');
            if (params.get('security')) config.security = params.get('security');
            if (['tls', '1', 'true'].includes(params.get('tls'))) config.tls = true;
            if (params.get('alpn')) config.alpn = params.get('alpn');
            if (params.get('path')) config.wsPath = params.get('path');
            config.wsHost = params.get('host') || params.get('wsHost') || '';
            config.transport = params.get('type') || params.get('transport') || params.get('net') || 'tcp';

            if (params.get('serviceName')) config.serviceName = params.get('serviceName');
            if (params.get('fp')) config.fp = params.get('fp');
            if (params.get('pbk')) config.pbk = params.get('pbk');
            if (params.get('sid')) config.sid = params.get('sid');
            if (params.get('spx')) config.spx = params.get('spx');
            if (params.get('flow')) config.flow = params.get('flow');
            if (params.get('packet_encoding')) config.packet_encoding = params.get('packet_encoding');
            if (params.get('ed')) config.max_early_data = params.get('ed');

            if (['1', 'true'].includes(params.get('record_fragment'))) config.record_fragment = true;
            if (['1', 'true'].includes(params.get('insecure')) || params.get('allowInsecure') === '1') config.insecure = true;

            const rawUser = decodeURIComponent(url.username || '');
            const rawPass = decodeURIComponent(url.password || '');

            if (protocol === 'tuic') {
                if (rawUser.includes(':')) {
                    const [uuid, password] = rawUser.split(':', 2);
                    config.uuid = uuid; config.password = password;
                } else {
                    config.uuid = rawUser; config.password = rawPass;
                }
            } else if (protocol === 'hysteria2' || protocol === 'hy2') {
                config.type = 'hysteria2';
                config.password = rawUser || rawPass;
                config.obfs = params.get('obfs');
            } else if (protocol === 'vless') {
                config.uuid = rawUser || rawPass;
            } else if (protocol === 'trojan') {
                config.password = rawUser;
            } else if (protocol === 'ss' || protocol === 'shadowsocks') {
                config.type = 'shadowsocks';
                if (rawUser && !rawPass && !rawUser.includes(':')) {
                    try {
                        const decoded = Buffer.from(rawUser, 'base64').toString('utf-8');
                        if (decoded.includes(':')) {
                            const [m, p] = decoded.split(':', 2);
                            config.method = m; config.password = p;
                        } else config.method = rawUser;
                    } catch (e) { config.method = rawUser; }
                } else {
                    config.method = rawUser; config.password = rawPass;
                }
            } else if (['socks5', 'socks', 'http'].includes(protocol)) {
                config.type = protocol === 'http' ? 'http' : 'socks';
                config.username = rawUser; config.password = rawPass;
            } else {
                return null;
            }

            return config;
        } catch (e) {
            console.error('[ProxyService] Link parse error:', e.message);
            return null;
        }
    }

    async syncSubscription(url) {
        try {
            const response = await axios.get(url);
            let content = response.data;
            try { content = Buffer.from(content, 'base64').toString('utf-8'); } catch (e) { }

            return content.split('\n')
                .filter(l => l.trim())
                .map(l => this.parseProxyLink(l.trim()))
                .filter(Boolean);
        } catch (e) {
            throw e;
        }
    }

    async testNode(nodeId) {
        const localPort = this.getLocalPort(nodeId);
        if (!localPort) throw new Error('Node not active in bridge');

        const startTime = Date.now();
        try {
            const agent = new SocksProxyAgent(`socks5h://127.0.0.1:${localPort}`);
            await axios.get('http://cp.cloudflare.com/generate_204', {
                httpAgent: agent, httpsAgent: agent, timeout: 15000, proxy: false
            });
            return Date.now() - startTime;
        } catch (e) {
            throw new Error(e.response ? `HTTP ${e.response.status}` : e.message);
        }
    }
}

// Default export instance
export const proxyService = new ProxyService();
