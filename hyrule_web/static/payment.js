/**
 * Payment dispatcher for Hyrule Cloud (Block C / Wave 3 + Block E / Wave 4).
 *
 * Top-level payment-method tabs (review.html: input[name="payment-method"]):
 *   - evm      → USDC via x402. Pull the chain list from /api/payments/networks
 *                (app.py proxies /api/* → backend /v1/*), populate #payment-chain,
 *                and dispatch to window.HyrulePayments.payWithEvm (payment-evm.js).
 *                family=svm is reserved for Wave 5 (payWithSolana).
 *   - btc/xmr  → native intent. window.HyrulePaymentNative.pay (payment-native.js)
 *                opens an /api/v1/intent/* deposit and polls it to PROVISIONED.
 *
 * No chain config or addresses live in JS — the EVM chain list comes from the
 * backend and the BTC/XMR deposit details come from /v1/intent/*, never
 * hardcoded here (per [[feedback_verified_payment_chains]]).
 */

(function () {
    "use strict";

    var payBtn = document.getElementById("pay-btn");
    var statusEl = document.getElementById("payment-status");
    var selector = document.getElementById("payment-chain");
    var dataForm = document.getElementById("order-data");
    // Block E: payment-method radios + the native deposit render slot.
    var methodInputs = document.querySelectorAll('input[name="payment-method"]');
    var nativeRender = document.getElementById("payment-native-render");

    if (!payBtn || !statusEl) return;

    var networksByKey = {};

    function currentMethod() {
        for (var i = 0; i < methodInputs.length; i++) {
            if (methodInputs[i].checked) return methodInputs[i].value;
        }
        return "evm";
    }

    function setStatus(msg, cls) {
        statusEl.textContent = msg;
        statusEl.className = "payment-status " + (cls || "");
    }

    function renderSelector(networks) {
        if (!selector) return;
        // Empty the placeholder option and add one per network.
        selector.innerHTML = "";
        networks.forEach(function (n) {
            var opt = document.createElement("option");
            opt.value = n.key;
            opt.textContent = n.display_name + " · " + n.asset
                + (n.testnet ? " (testnet)" : "");
            selector.appendChild(opt);
        });
    }

    async function loadNetworks() {
        try {
            // Same-origin: app.py proxies /api/* → backend /v1/* (see proxy_api).
            var resp = await fetch("/api/payments/networks");
            if (!resp.ok) throw new Error("networks: HTTP " + resp.status);
            var body = await resp.json();
            var networks = body.networks || [];
            networks.forEach(function (n) {
                networksByKey[n.key] = n;
            });
            renderSelector(networks);
            if (!networks.length && currentMethod() === "evm") {
                setStatus("No payment chains enabled. Contact ops.", "payment-error");
            }
        } catch (err) {
            // Don't disable pay-btn outright — BTC/XMR don't need the chain list.
            if (currentMethod() === "evm") {
                setStatus(
                    "Could not load supported chains. Refresh to try again.",
                    "payment-error",
                );
            }
            console.error("network-list fetch failed", err);
        }
    }

    function selectedNetwork() {
        if (selector && selector.value) {
            return networksByKey[selector.value];
        }
        // No selector on the page (single-chain deployment) → fall back to
        // the first network the backend advertises.
        var keys = Object.keys(networksByKey);
        if (keys.length) return networksByKey[keys[0]];
        return null;
    }

    function orderBody() {
        if (!dataForm) return {};
        var fd = new FormData(dataForm);
        var payload = {
            os: fd.get("os"),
            size: fd.get("size"),
            duration_days: parseInt(fd.get("duration_days"), 10),
            ssh_pubkey: fd.get("ssh_pubkey"),
            domain_mode: fd.get("domain_mode") || "auto",
        };
        var hostname = fd.get("hostname");
        if (hostname) payload.hostname = hostname;
        if (fd.get("domain") && fd.get("domain_mode") === "custom") {
            payload.domain = fd.get("domain");
        }
        return payload;
    }

    // Block E: toggle the EVM chain selector vs the native deposit slot based
    // on the selected method tab. EVM shows #payment-chain-wrap; BTC/XMR hide
    // it and reveal #payment-native-render.
    function refreshMethodUI() {
        var m = currentMethod();
        var wrap = document.getElementById("payment-chain-wrap");
        if (wrap) wrap.style.display = (m === "evm") ? "block" : "none";
        if (nativeRender) {
            nativeRender.style.display = (m === "btc" || m === "xmr") ? "block" : "none";
            if (m === "evm") nativeRender.innerHTML = "";
        }
    }

    Array.prototype.forEach.call(methodInputs, function (el) {
        el.addEventListener("change", refreshMethodUI);
    });

    payBtn.addEventListener("click", async function () {
        var method = currentMethod();

        // Block E: native BTC/XMR path — open an intent + poll. No chain.
        if (method === "btc" || method === "xmr") {
            if (!window.HyrulePaymentNative
                || typeof window.HyrulePaymentNative.pay !== "function") {
                setStatus("Native crypto adapter not loaded.", "payment-error");
                return;
            }
            return window.HyrulePaymentNative.pay(method.toUpperCase(), {
                orderForm: dataForm,
                render: nativeRender,
                onStatus: setStatus,
            });
        }

        // EVM (Wave 3) path — USDC via x402.
        var network = selectedNetwork();
        if (!network) {
            setStatus("No payment chain selected.", "payment-error");
            return;
        }
        var ns = window.HyrulePayments || {};
        if (network.family === "evm") {
            if (typeof ns.payWithEvm !== "function") {
                setStatus("EVM adapter not loaded.", "payment-error");
                return;
            }
            return ns.payWithEvm({
                network: network,
                button: payBtn,
                statusEl: statusEl,
                orderPath: "/api/vm/create",
                body: orderBody(),
            });
        }
        if (network.family === "svm") {
            if (typeof ns.payWithSolana !== "function") {
                setStatus(
                    "Solana support ships in Wave 5; pick an EVM chain.",
                    "payment-warn",
                );
                return;
            }
            return ns.payWithSolana({
                network: network,
                button: payBtn,
                statusEl: statusEl,
                orderPath: "/api/vm/create",
                body: orderBody(),
            });
        }
        setStatus("Unsupported chain family: " + network.family, "payment-error");
    });

    loadNetworks();
    refreshMethodUI();
})();
