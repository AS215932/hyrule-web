/**
 * Hyrule Cloud x402 payment dispatcher (Block C).
 *
 * Fetches the live PaymentConfig from /api/v1/payments/networks, populates
 * the chain selector, and delegates the actual EIP-3009 signing flow to
 * payment-evm.js. Block E will add payment-native.js for BTC/XMR; this
 * dispatcher will route based on the selected payment method tab.
 *
 * Hard requirement: chain metadata MUST come from the backend — never
 * hardcode contract addresses or chain IDs in this file
 * (feedback_verified_payment_chains.md).
 */
(function () {
    "use strict";

    var payBtn = document.getElementById("pay-btn");
    var statusEl = document.getElementById("payment-status");
    var chainSelect = document.getElementById("payment-chain");
    // Block E: when present, lets the customer pick USDC / BTC / XMR. The
    // hidden value (default: "evm") drives the dispatcher below.
    var methodInputs = document.querySelectorAll("input[name=\"payment-method\"]");
    var nativeRender = document.getElementById("payment-native-render");
    if (!payBtn || !statusEl) return;

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

    // Block A0: stash one-time anon management token in sessionStorage.
    function stashManagementToken(apiResult) {
        if (apiResult && apiResult.vm_id && apiResult.management_token) {
            try {
                sessionStorage.setItem(
                    "hyr_vm_mgmt:" + apiResult.vm_id,
                    JSON.stringify({
                        token: apiResult.management_token,
                        url: apiResult.management_url || null,
                        issued: Date.now(),
                    })
                );
            } catch (e) {
                console.warn("Failed to stash management token:", e);
            }
        }
    }

    var networksByKey = {};

    async function loadNetworks() {
        try {
            var resp = await fetch("/api/v1/payments/networks", {
                headers: { "Accept": "application/json" },
            });
            if (!resp.ok) throw new Error("HTTP " + resp.status);
            var body = await resp.json();
            var nets = body.networks || [];
            nets.forEach(function (n) { networksByKey[n.key] = n; });
            if (chainSelect) {
                // Clear placeholder + populate
                chainSelect.innerHTML = "";
                nets.forEach(function (n) {
                    var opt = document.createElement("option");
                    opt.value = n.key;
                    opt.textContent = n.display_name + " (USDC)";
                    chainSelect.appendChild(opt);
                });
                chainSelect.disabled = false;
            }
            payBtn.disabled = false;
        } catch (err) {
            setStatus("Could not load payment networks. Try refreshing.", "payment-error");
            console.error("loadNetworks failed:", err);
        }
    }

    function gatherOrderPayload() {
        var form = document.getElementById("order-data");
        var fd = new FormData(form);
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

    payBtn.disabled = true;
    if (chainSelect) chainSelect.disabled = true;
    loadNetworks();

    // Toggle UI surfaces (chain dropdown vs. native deposit card) based on
    // the selected method radio. EVM shows the chain selector; BTC/XMR hide
    // it and reveal the deposit-card slot.
    function refreshMethodUI() {
        var m = currentMethod();
        if (chainSelect) {
            chainSelect.parentElement.style.display = (m === "evm") ? "" : "none";
        }
        if (nativeRender) {
            nativeRender.style.display = (m === "btc" || m === "xmr") ? "" : "none";
            if (m === "evm") nativeRender.innerHTML = "";
        }
        payBtn.textContent = (m === "evm")
            ? payBtn.dataset.evmLabel || payBtn.textContent
            : "Generate " + m.toUpperCase() + " deposit address";
    }

    // Stash the original "Pay $X USDC" label so we can restore it.
    if (payBtn.textContent && !payBtn.dataset.evmLabel) {
        payBtn.dataset.evmLabel = payBtn.textContent.trim();
    }

    Array.prototype.forEach.call(methodInputs, function (el) {
        el.addEventListener("change", refreshMethodUI);
    });
    refreshMethodUI();

    payBtn.addEventListener("click", async function () {
        var method = currentMethod();
        payBtn.disabled = true;

        try {
            if (method === "evm") {
                var selectedKey = chainSelect ? chainSelect.value : "base";
                var network = networksByKey[selectedKey];
                if (!network) {
                    setStatus("Pick a chain first.", "payment-warn");
                    payBtn.disabled = false;
                    return;
                }
                // Block H: dispatch by network.family so an `solana:*` entry
                // routes to payment-svm.js instead of payment-evm.js. The
                // EVM/SVM drivers share the same pay(network, opts) contract.
                var family = network.family || "evm";
                var driver = null;
                if (family === "evm" && window.HyrulePaymentEVM) {
                    driver = window.HyrulePaymentEVM;
                } else if (family === "svm" && window.HyrulePaymentSVM) {
                    driver = window.HyrulePaymentSVM;
                }
                if (!driver) {
                    setStatus("Payment driver for " + family + " not loaded.", "payment-error");
                    payBtn.disabled = false;
                    return;
                }
                var outcome = await driver.pay(network, {
                    endpoint: "/api/vm/create",
                    orderPayload: gatherOrderPayload(),
                    onStatus: setStatus,
                    onSettled: function (apiResult) {
                        stashManagementToken(apiResult);
                    },
                });
                setStatus("Payment successful! Redirecting…", "payment-ok");
                setTimeout(function () {
                    window.location.href = "/order/status/" + outcome.result.vm_id;
                }, 1000);
            } else if (method === "btc" || method === "xmr") {
                if (!window.HyrulePaymentNative) {
                    setStatus("Native crypto driver not loaded.", "payment-error");
                    payBtn.disabled = false;
                    return;
                }
                await window.HyrulePaymentNative.pay(method.toUpperCase(), {
                    orderForm: document.getElementById("order-data"),
                    render: nativeRender,
                    onStatus: setStatus,
                });
                // Pay button stays disabled; polling drives the redirect.
            } else {
                setStatus("Unknown payment method.", "payment-error");
                payBtn.disabled = false;
            }
        } catch (err) {
            if (err && err.code === 4001) {
                setStatus("Payment cancelled.", "payment-warn");
            } else {
                setStatus("Error: " + (err && err.message ? err.message : err), "payment-error");
                console.error("payment error:", err);
            }
            payBtn.disabled = false;
        }
    });
})();
