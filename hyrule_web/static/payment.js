/**
 * Chain dispatcher for Hyrule Cloud (Block C / Wave 3).
 *
 * The frontend pulls the supported chain list from the same-origin
 * /api/payments/networks, which app.py proxies to the backend's canonical
 * /v1/payments/networks (NEVER hardcodes — per [[feedback_verified_payment_chains]]),
 * reads the selected chain from the #payment-chain selector on review.html,
 * and routes to the right family adapter:
 *
 *   - family=evm → window.HyrulePayments.payWithEvm (payment-evm.js)
 *   - family=svm → window.HyrulePayments.payWithSolana (payment-svm.js, Wave 5)
 *
 * No chain config lives in JS. If the backend disables a chain in Vault,
 * the selector loses it on the next page load — no JS change required.
 */

(function () {
    "use strict";

    var payBtn = document.getElementById("pay-btn");
    var statusEl = document.getElementById("payment-status");
    var selector = document.getElementById("payment-chain");
    var dataForm = document.getElementById("order-data");

    if (!payBtn || !statusEl) return;

    var networksByKey = {};

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
        // Only reveal the selector UI when there's a real choice. Single-
        // chain deployments keep the visual identical to pre-Wave-3.
        var wrap = document.getElementById("payment-chain-wrap");
        if (wrap) wrap.style.display = networks.length > 1 ? "block" : "none";
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
            if (!networks.length) {
                setStatus("No payment chains enabled. Contact ops.", "payment-error");
                payBtn.disabled = true;
            }
        } catch (err) {
            setStatus(
                "Could not load supported chains. Refresh to try again.",
                "payment-error",
            );
            payBtn.disabled = true;
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

    payBtn.addEventListener("click", async function () {
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
})();
