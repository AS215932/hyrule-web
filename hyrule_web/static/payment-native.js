/**
 * Native crypto (BTC / XMR) payment driver for Hyrule Cloud checkout.
 *
 * Exposes window.HyrulePaymentNative.pay(asset, opts) where asset is "BTC"
 * or "XMR". The flow:
 *   1. POST /api/v1/intent/create with order_payload + client_order_id
 *      (idempotency key generated client-side, persisted to sessionStorage
 *      so a page reload doesn't allocate a second address).
 *   2. Render the deposit address + amount + countdown + QR code (drawn
 *      from the qr_code_uri the backend returns; uses qrcode-svg from CDN).
 *   3. Poll GET /api/v1/intent/{id} every 5s. On PROVISIONED, stash the
 *      one-shot management_token in sessionStorage (mirrors A0) and
 *      redirect to /order/status/{vm_id}.
 *
 * Zero dependencies on a wallet plugin. Customer broadcasts from their own
 * wallet (mobile/desktop). The only third-party JS is qrcode-svg loaded
 * lazily from a CDN — see drawQR().
 */
(function () {
    "use strict";

    var POLL_MS = 5000;
    var QR_LIB_URL = "https://cdn.jsdelivr.net/npm/qrcode-svg@1.1.0/dist/qrcode.min.js";
    var qrLibPromise = null;

    function loadQRLib() {
        if (qrLibPromise) return qrLibPromise;
        qrLibPromise = new Promise(function (resolve, reject) {
            // If the lib is somehow already loaded, resolve immediately.
            if (typeof window.QRCode === "function") {
                resolve(window.QRCode);
                return;
            }
            var s = document.createElement("script");
            s.src = QR_LIB_URL;
            s.async = true;
            s.onload = function () { resolve(window.QRCode); };
            s.onerror = function () { reject(new Error("Failed to load QR library")); };
            document.head.appendChild(s);
        });
        return qrLibPromise;
    }

    async function drawQR(container, content) {
        try {
            var QR = await loadQRLib();
            var qr = new QR({
                content: content,
                padding: 2,
                width: 256,
                height: 256,
                color: "#000",
                background: "#fff",
                ecl: "M",
            });
            container.innerHTML = qr.svg();
        } catch (e) {
            // Fallback: just show the URI as a copyable string. The plan
            // promised server-side segno rendering as the long-term path;
            // until the backend wires that, the CDN is the v1 fallback.
            container.innerHTML = "<code style=\"word-break:break-all;font-size:.85rem\">" +
                String(content).replace(/[<>&]/g, function (c) {
                    return c === "<" ? "&lt;" : c === ">" ? "&gt;" : "&amp;";
                }) + "</code>";
        }
    }

    function newClientOrderId() {
        // Browser-side UUID v4-ish; collision-irrelevant since it's just an
        // idempotency key scoped to one customer's payment intent.
        var arr = new Uint8Array(16);
        crypto.getRandomValues(arr);
        arr[6] = (arr[6] & 0x0f) | 0x40;
        arr[8] = (arr[8] & 0x3f) | 0x80;
        return Array.from(arr).map(function (b, i) {
            var hex = b.toString(16).padStart(2, "0");
            return (i === 4 || i === 6 || i === 8 || i === 10) ? "-" + hex : hex;
        }).join("");
    }

    function gatherOrderPayload(formEl) {
        var fd = new FormData(formEl);
        var payload = {
            os: fd.get("os"),
            size: fd.get("size"),
            duration_days: parseInt(fd.get("duration_days"), 10),
            ssh_pubkey: fd.get("ssh_pubkey"),
            domain_mode: fd.get("domain_mode") || "auto",
        };
        if (fd.get("hostname")) payload.hostname = fd.get("hostname");
        if (fd.get("domain") && fd.get("domain_mode") === "custom") {
            payload.domain = fd.get("domain");
        }
        return payload;
    }

    function stashManagementToken(intentBody) {
        // Same shape A0/payment.js writes for x402 orders. status.html reads this.
        if (intentBody && intentBody.vm_id && intentBody.management_token) {
            try {
                sessionStorage.setItem(
                    "hyr_vm_mgmt:" + intentBody.vm_id,
                    JSON.stringify({
                        token: intentBody.management_token,
                        url: intentBody.management_url || null,
                        issued: Date.now(),
                    })
                );
            } catch (e) {
                console.warn("Failed to stash management token:", e);
            }
        }
    }

    /**
     * @param {"BTC"|"XMR"} asset
     * @param {Object} opts:
     *   - orderForm: the hidden #order-data form element
     *   - render: HTMLElement to render the deposit card into
     *   - onStatus(msg, css_class): UI status callback
     */
    async function pay(asset, opts) {
        var setStatus = opts.onStatus || function () {};
        var render = opts.render;
        var orderForm = opts.orderForm;
        if (!render || !orderForm) {
            throw new Error("HyrulePaymentNative.pay: render + orderForm required");
        }

        // Idempotent intent creation: a per-asset client_order_id is stashed
        // in sessionStorage so reload doesn't allocate a fresh deposit.
        var stashKey = "hyr_intent_client_order_id:" + asset;
        var clientOrderId = sessionStorage.getItem(stashKey);
        if (!clientOrderId) {
            clientOrderId = newClientOrderId();
            sessionStorage.setItem(stashKey, clientOrderId);
        }

        setStatus("Allocating deposit address…", "payment-pending");
        var createResp = await fetch("/api/v1/intent/create", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                asset: asset,
                client_order_id: clientOrderId,
                order_payload: gatherOrderPayload(orderForm),
            }),
        });
        if (!createResp.ok) {
            var err = await createResp.json().catch(function () { return {}; });
            throw new Error(err.detail || err.error || "Intent create failed: " + createResp.status);
        }
        var intent = await createResp.json();

        renderDepositCard(render, intent);

        setStatus("Awaiting payment…", "payment-pending");
        await pollUntilTerminal(intent.intent_id, render, setStatus);
    }

    function renderDepositCard(container, intent) {
        var label = intent.asset === "BTC" ? "Bitcoin" : "Monero";
        var expires = intent.expires_at ? new Date(intent.expires_at) : null;
        container.innerHTML = "" +
            "<div class=\"mini-card\" style=\"padding:20px\">" +
              "<div style=\"display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap\">" +
                "<div id=\"hyr-qr\" style=\"width:256px;height:256px;background:#fff;border-radius:8px;flex:0 0 auto\"></div>" +
                "<div style=\"flex:1 1 220px;min-width:220px;display:flex;flex-direction:column;gap:10px\">" +
                  "<div><span class=\"panel-label\">send</span><div style=\"font-size:1.4em;margin-top:4px\"><strong>" + intent.amount_crypto + " " + intent.asset + "</strong></div></div>" +
                  "<div><span class=\"panel-label\">to address</span><div style=\"margin-top:4px\"><code id=\"hyr-addr\" style=\"word-break:break-all;font-size:.85em\">" + intent.address + "</code></div></div>" +
                  "<div style=\"display:flex;gap:6px\"><button id=\"hyr-copy-addr\" class=\"btn btn-secondary btn-xs\">copy address</button><button id=\"hyr-copy-amt\" class=\"btn btn-secondary btn-xs\">copy amount</button></div>" +
                  "<div style=\"font-size:.85em;color:var(--text-soft)\">≈ $" + intent.amount_usd + " · rate locked until " + (intent.rate_valid_until || "—") + "</div>" +
                  "<div id=\"hyr-status\" style=\"font-size:.85em\">Status: <strong>" + intent.status + "</strong> · confirmations: <span id=\"hyr-confs\">" + (intent.confirmations || 0) + "</span></div>" +
                  (expires ? "<div style=\"font-size:.78em;color:var(--text-soft)\">Intent expires " + expires.toISOString() + "</div>" : "") +
                "</div>" +
              "</div>" +
              "<p style=\"margin-top:14px;font-size:.78em;color:var(--text-soft)\">" + label + ": pay the exact amount or more — overpay is fine (becomes a tip). If the rate snapshot expires before you broadcast, we'll re-quote within 1% slippage. Underpayment triggers a manual review.</p>" +
            "</div>";

        document.getElementById("hyr-copy-addr").addEventListener("click", function () {
            navigator.clipboard.writeText(intent.address);
        });
        document.getElementById("hyr-copy-amt").addEventListener("click", function () {
            navigator.clipboard.writeText(intent.amount_crypto);
        });

        var qrTarget = document.getElementById("hyr-qr");
        drawQR(qrTarget, intent.qr_code_uri || (intent.asset.toLowerCase() + ":" + intent.address));
    }

    async function pollUntilTerminal(intentId, container, setStatus) {
        var done = false;
        while (!done) {
            await new Promise(function (r) { setTimeout(r, POLL_MS); });
            var resp;
            try {
                resp = await fetch("/api/v1/intent/" + intentId);
            } catch (e) {
                continue; // transient; retry next tick
            }
            if (!resp.ok) continue;
            var body = await resp.json().catch(function () { return null; });
            if (!body) continue;

            // Refresh UI bits
            var s = document.getElementById("hyr-status");
            var c = document.getElementById("hyr-confs");
            if (s) s.innerHTML = "Status: <strong>" + body.status + "</strong> · confirmations: <span id=\"hyr-confs\">" + (body.confirmations || 0) + "</span>";
            if (c) c.textContent = body.confirmations || 0;

            switch (body.status) {
                case "PROVISIONED":
                    setStatus("Payment received. Redirecting…", "payment-ok");
                    stashManagementToken(body);
                    setTimeout(function () {
                        window.location.href = "/order/status/" + body.vm_id;
                    }, 800);
                    done = true;
                    break;
                case "REFUND_MANUAL":
                    setStatus("Payment received but amount/rate didn't match. Contact the operator with intent ID " + intentId + ".", "payment-warn");
                    done = true;
                    break;
                case "EXPIRED":
                    setStatus("Intent expired with no payment seen. Refresh to start over.", "payment-warn");
                    done = true;
                    break;
                case "FAILED":
                    setStatus("Provisioning failed after payment. Contact the operator with intent ID " + intentId + ".", "payment-error");
                    done = true;
                    break;
                default:
                    // CREATED / WAITING_PAYMENT / SETTLED / PROVISIONING — keep polling
                    break;
            }
        }
    }

    window.HyrulePaymentNative = { pay: pay };
})();
