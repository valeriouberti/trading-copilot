/**
 * WebSocket client for real-time signal and price updates.
 *
 * Connects to /ws/signals and dispatches custom events that
 * page-specific JS can listen to.
 *
 * Events dispatched on `document`:
 *   - "ws:price_update"  — { symbol, price, change_pct, regime, timestamp }
 *   - "ws:signal"        — { symbol, direction, entry, sl, tp, ... }
 *   - "ws:regime_change" — { old_regime, new_regime, reason }
 *   - "ws:connected"     — WebSocket opened
 *   - "ws:disconnected"  — WebSocket closed
 */

(function () {
    "use strict";

    let ws = null;
    let reconnectTimer = null;
    const RECONNECT_DELAY = 3000; // ms

    function getWsUrl() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        return `${proto}//${location.host}/ws/signals`;
    }

    function connect() {
        if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
            return;
        }

        ws = new WebSocket(getWsUrl());

        ws.onopen = function () {
            console.log("[WS] connected");
            document.dispatchEvent(new CustomEvent("ws:connected"));
            updateStatusDot(true);
        };

        ws.onclose = function () {
            console.log("[WS] disconnected — reconnecting in", RECONNECT_DELAY, "ms");
            document.dispatchEvent(new CustomEvent("ws:disconnected"));
            updateStatusDot(false);
            scheduleReconnect();
        };

        ws.onerror = function (err) {
            console.error("[WS] error", err);
            ws.close();
        };

        ws.onmessage = function (event) {
            try {
                const data = JSON.parse(event.data);
                handleMessage(data);
            } catch (e) {
                console.warn("[WS] bad message", event.data);
            }
        };
    }

    function scheduleReconnect() {
        if (reconnectTimer) return;
        reconnectTimer = setTimeout(function () {
            reconnectTimer = null;
            connect();
        }, RECONNECT_DELAY);
    }

    function handleMessage(data) {
        const type = data.type;
        if (!type) return;

        // Dispatch as custom event
        document.dispatchEvent(new CustomEvent("ws:" + type, { detail: data }));

        // Signal fired → browser notification + tab badge
        if (type === "signal") {
            showSignalAlert(data);
        }
    }

    function showSignalAlert(data) {
        // Update page title with signal badge
        const dir = data.direction === "LONG" ? "🟢" : "🔴";
        const origTitle = document.title.replace(/^[🟢🔴⚪]\s*SIGNAL\s*—\s*/, "");
        document.title = `${dir} SIGNAL — ${origTitle}`;

        // Reset title after 30 seconds
        setTimeout(function () {
            document.title = origTitle;
        }, 30000);

        // Browser notification (if permitted)
        if (Notification.permission === "granted") {
            new Notification(`${data.direction} Signal — ${data.symbol}`, {
                body: `Entry: ${data.entry}  SL: ${data.sl}  TP: ${data.tp}`,
                icon: "/static/img/favicon.png",
            });
        } else if (Notification.permission !== "denied") {
            Notification.requestPermission();
        }
    }

    function updateStatusDot(connected) {
        const dot = document.querySelector(".status-dot");
        if (dot) {
            dot.style.background = connected ? "var(--accent-green)" : "var(--accent-red)";
        }
        const text = document.querySelector(".status-text");
        if (text) {
            text.textContent = connected ? "Live" : "Reconnecting...";
        }
    }

    // Auto-connect when script loads
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", connect);
    } else {
        connect();
    }

    // Expose for manual use
    window.tradingWs = {
        connect: connect,
        send: function (data) {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(typeof data === "string" ? data : JSON.stringify(data));
            }
        },
    };
})();
