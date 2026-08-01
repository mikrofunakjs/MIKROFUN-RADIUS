const express = require('express');
const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestWaWebVersion } = require('@whiskeysockets/baileys');

const pino = require('pino');
const qrcode = require('qrcode');
const fs = require('fs');

const app = express();
app.use(express.json());

// WA_PORT, not PORT: run_dist.py sets PORT for the web panel (80) and spawns
// this service with its environment inherited, so honouring PORT made the
// gateway try to bind the panel's port and die with EADDRINUSE.
const PORT = process.env.WA_PORT || 3000;
const crypto = require('crypto');

if (!process.env.WA_API_KEY) {
    console.error('FATAL: WA_API_KEY environment variable not set');
    process.exit(1);
}
const API_KEY = process.env.WA_API_KEY;

let sock;
let currentQR = null;
let connectionStatus = 'initializing';
let connectionErrorReason = null;
let initTimeout = null;
let reconnectTimer = null;
let isReconnecting = false;

const rateLimitMap = new Map();
const RATE_LIMIT_WINDOW = 60000;
const MAX_REQUESTS_PER_WINDOW = 30;
const MAX_PER_TARGET_WINDOW = 5;
const targetRateMap = new Map();

function normalizePhoneNumber(target) {
    // Normalize phone number to digits-only form for rate-limit key
    let normalized = target.toString();
    if (normalized.includes('@')) {
        normalized = normalized.split('@')[0];
    }
    return normalized.replace(/\D/g, '');
}

function checkRateLimit(target) {
    const now = Date.now();
    const globalKey = 'global';
    if (!rateLimitMap.has(globalKey)) {
        rateLimitMap.set(globalKey, []);
    }
    const globalTimestamps = rateLimitMap.get(globalKey).filter(t => now - t < RATE_LIMIT_WINDOW);
    if (globalTimestamps.length >= MAX_REQUESTS_PER_WINDOW) {
        return { allowed: false, error: 'Global rate limit exceeded. Try again later.' };
    }

    if (target) {
        const targetKey = normalizePhoneNumber(target);
        if (!targetRateMap.has(targetKey)) {
            targetRateMap.set(targetKey, []);
        }
        const targetTimestamps = targetRateMap.get(targetKey).filter(t => now - t < RATE_LIMIT_WINDOW);
        if (targetTimestamps.length >= MAX_PER_TARGET_WINDOW) {
            return { allowed: false, error: 'Too many messages to this number. Try again later.' };
        }
        targetTimestamps.push(now);
        targetRateMap.set(targetKey, targetTimestamps);
    }

    globalTimestamps.push(now);
    rateLimitMap.set(globalKey, globalTimestamps);
    return { allowed: true };
}

// Drop stale per-target buckets so the map does not grow unbounded over time.
setInterval(() => {
    const now = Date.now();
    for (const [key, timestamps] of targetRateMap) {
        if (!timestamps.some(t => now - t < RATE_LIMIT_WINDOW)) {
            targetRateMap.delete(key);
        }
    }
}, RATE_LIMIT_WINDOW).unref();

function authMiddleware(req, res, next) {
    const key = req.headers['x-api-key'] || '';
    try {
        if (!crypto.timingSafeEqual(Buffer.from(key), Buffer.from(API_KEY))) {
            return res.status(401).json({ success: false, error: 'Unauthorized' });
        }
    } catch (e) {
        return res.status(401).json({ success: false, error: 'Unauthorized' });
    }
    next();
}

function clearInitTimeout() {
    if (initTimeout) {
        clearTimeout(initTimeout);
        initTimeout = null;
    }
}

function clearReconnectTimer() {
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }
}

function armInitTimeout() {
    clearInitTimeout();
    initTimeout = setTimeout(() => {
        if (connectionStatus === 'initializing') {
            connectionStatus = 'offline';
            connectionErrorReason = 'Timeout saat inisialisasi. Cek koneksi internet VPS atau PM2 logs.';
            console.log("Initialization timeout, marking offline.");
            scheduleRetry(15000);
        }
    }, 20000);
}

function scheduleRetry(delayMs) {
    if (!isReconnecting) {
        isReconnecting = true;
        clearReconnectTimer();
        reconnectTimer = setTimeout(() => {
            isReconnecting = false;
            connectToWhatsApp();
        }, delayMs);
    }
}

async function connectToWhatsApp() {
    connectionErrorReason = null;
    clearReconnectTimer();
    armInitTimeout();
    try {
        console.log("Loading auth state...");
        const { state, saveCreds } = await useMultiFileAuthState('auth_info_baileys');

        console.log("Fetching latest WhatsApp Web version...");
        let wanodeVersion, isLatest;
        try {
            const v = await fetchLatestWaWebVersion();
            wanodeVersion = v.version;
            isLatest = v.isLatest;
            console.log(`Using WA v${wanodeVersion.join('.')}, isLatest: ${isLatest}`);
        } catch (verErr) {
            console.error('Failed to fetch WA version:', verErr.message);
            connectionStatus = 'offline';
            connectionErrorReason = 'Gagal mengambil versi WhatsApp Web. Cek koneksi internet VPS.';
            scheduleRetry(30000);
            return;
        }

        console.log("Creating WA socket...");
        sock = makeWASocket({
            version: wanodeVersion,
            auth: state,
            printQRInTerminal: true,
            logger: pino({ level: 'warn' })
        });

        console.log("Binding socket events...");

        sock.ev.on('connection.update', async (update) => {
            const { connection, lastDisconnect, qr } = update;

            if (qr) {
                connectionStatus = 'qr';
                currentQR = await qrcode.toDataURL(qr);
                console.log('QR Code generated. Please scan.');
            }

            if (connection === 'close') {
                const statusCode = lastDisconnect?.error?.output?.statusCode;

                if (statusCode === 405) {
                    console.error('WhatsApp Web rejected the connection (405 Method Not Allowed). Retrying in 60s.');
                    connectionStatus = 'offline';
                    connectionErrorReason = 'Koneksi Ditolak (405). IP VPS diblokir sementara oleh WhatsApp atau protokol Baileys perlu diupdate.';
                    currentQR = null;
                    scheduleRetry(60000);
                    return;
                }

                const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
                console.log('Connection closed due to', lastDisconnect?.error, ', reconnecting:', shouldReconnect);

                if (shouldReconnect) {
                    connectionStatus = 'disconnected';
                    scheduleRetry(3000);
                } else {
                    console.log('Logged out from WhatsApp. Deleting session.');
                    connectionStatus = 'disconnected';
                    currentQR = null;
                    try {
                        if (sock) {
                            sock.ev.removeAllListeners('connection.update');
                            sock.ev.removeAllListeners('creds.update');
                        }
                    } catch (e) {}
                    try { fs.rmSync('auth_info_baileys', { recursive: true, force: true }); } catch (e) { }
                    scheduleRetry(1000);
                }
            } else if (connection === 'open') {
                console.log('WhatsApp Web Connected!');
                clearReconnectTimer();
                clearInitTimeout();
                connectionStatus = 'connected';
                currentQR = null;
                connectionErrorReason = null;
                isReconnecting = false;
            }
        });

        sock.ev.on('creds.update', saveCreds);

        // ── AI CS: Forward incoming messages to MikroFun backend ──
        sock.ev.on('messages.upsert', async ({ messages, type }) => {
            if (type !== 'notify') return;
            for (const msg of messages) {
                const isGroup = msg.key?.remoteJid?.endsWith('@g.us');
                const isOwn = msg.key?.fromMe;
                if (isGroup || isOwn) continue;

                const text = msg.message?.conversation
                          || msg.message?.extendedTextMessage?.text
                          || '';
                if (!text || !text.trim()) continue;

                const sender = msg.key?.remoteJid?.split('@')[0] || '';

                // Apply rate limit to prevent financial DoS via excessive AI calls
                const rateCheck = checkRateLimit(sender);
                if (!rateCheck.allowed) {
                    console.log(`AI CS: Rate limit hit for ${sender}`);
                    continue;
                }

                try {
                    await fetch('http://127.0.0.1:5000/api/ai/wa-reply', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
                        body: JSON.stringify({ sender, text })
                    });
                } catch (e) {
                    console.log('AI CS forward error:', e.message);
                }
            }
        });
    } catch (err) {
        console.error('Failed to initialize WhatsApp:', err);
        connectionStatus = 'offline';
        connectionErrorReason = 'Gagal Inisialisasi: ' + err.message;
        isReconnecting = false;
        scheduleRetry(10000);
    }
}

connectToWhatsApp();

// --- API ROUTES FOR MIKROFUN PYTHON BACKEND ---

app.get('/status', authMiddleware, (req, res) => {
    res.json({
        status: connectionStatus,
        qr: currentQR,
        error: connectionErrorReason
    });
});

app.post('/send', authMiddleware, async (req, res) => {
    try {
        const { target, message } = req.body;

        if (connectionStatus !== 'connected' || !sock) {
            return res.status(400).json({ success: false, error: 'WhatsApp is not connected.' });
        }

        if (!target || !message) {
            return res.status(400).json({ success: false, error: 'Missing target or message' });
        }

        let formattedTarget = target.toString();
        if (formattedTarget.includes('@')) {
            formattedTarget = formattedTarget.split('@')[0];
        }
        formattedTarget = formattedTarget.replace(/\D/g, '');
        if (formattedTarget.startsWith('620')) {
            formattedTarget = '62' + formattedTarget.substring(3);
        }
        if (formattedTarget.startsWith('0')) {
            formattedTarget = '62' + formattedTarget.substring(1);
        } else if (!formattedTarget.startsWith('62')) {
            formattedTarget = '62' + formattedTarget;
        }
        if (formattedTarget.length < 10 || formattedTarget.length > 15) {
            return res.status(400).json({ success: false, error: 'Invalid phone number after formatting: ' + formattedTarget });
        }
        formattedTarget = `${formattedTarget}@s.whatsapp.net`;

        const rateCheck = checkRateLimit(target);
        if (!rateCheck.allowed) {
            return res.status(429).json({ success: false, error: rateCheck.error });
        }

        const result = await sock.sendMessage(formattedTarget, { text: message });
        res.json({ success: true, message_id: result.key.id });

    } catch (err) {
        console.error('Send message error:', err);
        res.status(500).json({ success: false, error: err.message });
    }
});

app.post('/logout', authMiddleware, async (req, res) => {
    try {
        if (sock) {
            isReconnecting = false;
            clearReconnectTimer();
            await sock.logout();
            connectionStatus = 'disconnected';
            currentQR = null;
            res.json({ success: true, message: 'Logged out successfully' });
        } else {
            res.json({ success: true, message: 'Already disconnected' });
        }
    } catch (err) {
        res.status(500).json({ success: false, error: err.message });
    }
});

app.post('/connect', authMiddleware, async (req, res) => {
    try {
        connectionErrorReason = null;
        isReconnecting = false;
        clearReconnectTimer();
        connectToWhatsApp();
        res.json({ success: true, message: 'Reconnecting...' });
    } catch (err) {
        res.status(500).json({ success: false, error: err.message });
    }
});

// Bind to loopback only: this service is consumed by the local Python backend,
// it must not be reachable from the internet.
const HOST = process.env.WA_BIND_HOST || '127.0.0.1';
app.listen(PORT, HOST, () => {
    console.log(`WhatsApp Gateway Service running on http://${HOST}:${PORT}`);
});
