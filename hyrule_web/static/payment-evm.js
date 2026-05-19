/**
 * EVM payment adapter for Hyrule Cloud (Block C / Wave 3).
 *
 * Chain-agnostic: takes a `network` config object describing the target chain
 * and signs an EIP-712 TransferWithAuthorization against the USDC contract on
 * that chain. The caller (payment.js dispatcher) is responsible for fetching
 * the network list from `/v1/payments/networks` and passing the chosen entry
 * through. NEVER hardcode a chain here — that's the dispatcher's job and the
 * backend's source of truth per [[feedback_verified_payment_chains]].
 *
 * Wave 5 (Block H) adds a sibling payment-svm.js for Solana via Phantom etc.
 * The dispatcher routes by `network.family`.
 *
 * Exports:
 *   window.HyrulePayments.payWithEvm({network, button, statusEl, orderPath, body})
 *     - network: the chosen entry from /v1/payments/networks (carries
 *       chain_id, token_address, eip712_domain, etc.)
 *     - button: the click target (disabled during flow)
 *     - statusEl: the .payment-status div for user feedback
 *     - orderPath: e.g. "/api/vm/create" — the 402-gated endpoint
 *     - body: the JSON payload for the POST (everything OTHER than X-PAYMENT)
 */

(function () {
    "use strict";

    var ns = window.HyrulePayments = window.HyrulePayments || {};

    function setStatus(statusEl, msg, cls) {
        if (!statusEl) return;
        statusEl.textContent = msg;
        statusEl.className = "payment-status " + (cls || "");
    }

    async function ensureChain(network) {
        // EIP-1193: wallet_switchEthereumChain. If the chain isn't yet known
        // to the wallet, fall back to wallet_addEthereumChain with the
        // explorer/rpc info from /v1/payments/networks.
        var chainIdHex = "0x" + network.chain_id.toString(16);
        try {
            await window.ethereum.request({
                method: "wallet_switchEthereumChain",
                params: [{ chainId: chainIdHex }],
            });
        } catch (switchErr) {
            if (switchErr.code === 4902) {
                await window.ethereum.request({
                    method: "wallet_addEthereumChain",
                    params: [{
                        chainId: chainIdHex,
                        chainName: network.display_name,
                        nativeCurrency: { name: "ETH", symbol: "ETH", decimals: 18 },
                        rpcUrls: [network.rpc_url].filter(Boolean),
                        blockExplorerUrls: [network.block_explorer_url].filter(Boolean),
                    }],
                });
            } else {
                throw switchErr;
            }
        }
    }

    function nonceHex32() {
        var bytes = crypto.getRandomValues(new Uint8Array(32));
        return "0x" + Array.from(bytes)
            .map(function (b) { return b.toString(16).padStart(2, "0"); })
            .join("");
    }

    function buildTypedData(network, from, payTo, valueUnits, validAfter, validBefore, nonce) {
        return {
            types: {
                EIP712Domain: [
                    { name: "name", type: "string" },
                    { name: "version", type: "string" },
                    { name: "chainId", type: "uint256" },
                    { name: "verifyingContract", type: "address" },
                ],
                TransferWithAuthorization: [
                    { name: "from", type: "address" },
                    { name: "to", type: "address" },
                    { name: "value", type: "uint256" },
                    { name: "validAfter", type: "uint256" },
                    { name: "validBefore", type: "uint256" },
                    { name: "nonce", type: "bytes32" },
                ],
            },
            domain: {
                name: network.eip712_domain.name,
                version: network.eip712_domain.version,
                chainId: network.chain_id,
                verifyingContract: network.token_address,
            },
            primaryType: "TransferWithAuthorization",
            message: {
                from: from,
                to: payTo,
                value: String(valueUnits),
                validAfter: validAfter,
                validBefore: validBefore,
                nonce: nonce,
            },
        };
    }

    async function payWithEvm(opts) {
        var network = opts.network;
        var button = opts.button;
        var statusEl = opts.statusEl;
        var orderPath = opts.orderPath;
        var body = opts.body;

        if (!window.ethereum) {
            setStatus(statusEl, "No wallet detected. Install MetaMask or Rabby.", "payment-error");
            return;
        }

        if (button) button.disabled = true;
        setStatus(statusEl, "Connecting wallet…", "payment-pending");

        try {
            var accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
            var from = accounts[0];

            await ensureChain(network);

            // First request: 402 with payment requirements.
            setStatus(statusEl, "Requesting payment details…", "payment-pending");
            var firstResp = await fetch(orderPath, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });

            if (firstResp.status !== 402) {
                if (firstResp.ok) {
                    // Some test/dev paths bypass payment — still honour the
                    // management-token forwarding (Block A0).
                    var okResult = await firstResp.json();
                    var okTok = okResult.management_token
                        ? "?token=" + encodeURIComponent(okResult.management_token)
                        : "";
                    window.location.href = "/order/status/" + okResult.vm_id + okTok;
                    return;
                }
                var errBody = await firstResp.json().catch(function () { return {}; });
                throw new Error(errBody.detail || errBody.error || "API error: " + firstResp.status);
            }

            var paymentHeader = firstResp.headers.get("x-payment-required");
            if (!paymentHeader) throw new Error("Missing X-PAYMENT-REQUIRED header");
            var paymentReq = JSON.parse(atob(paymentHeader));
            // Pick the accept entry that matches OUR chain — the backend may
            // advertise multiple. Fall back to first if no exact match.
            var accept = (paymentReq.accepts || []).find(function (a) {
                return a.network === network.caip2 || a.network === network.key;
            }) || (paymentReq.accepts || [])[0];
            if (!accept) throw new Error("No matching `accepts` entry for " + network.caip2);

            var priceStr = (accept.price || "0").replace("$", "");
            var valueUnits = Math.round(parseFloat(priceStr) * Math.pow(10, network.token_decimals));

            var nonce = nonceHex32();
            var now = Math.floor(Date.now() / 1000);
            var validAfter = String(now - 600);
            var validBefore = String(now + 3600);
            var payTo = accept.payTo || accept.pay_to;
            if (!payTo) throw new Error("Facilitator response missing payTo");

            var typedData = buildTypedData(
                network, from, payTo, valueUnits, validAfter, validBefore, nonce,
            );

            setStatus(statusEl, "Please sign the payment in your wallet…", "payment-pending");
            var signature = await window.ethereum.request({
                method: "eth_signTypedData_v4",
                params: [from, JSON.stringify(typedData)],
            });

            var paymentPayload = {
                x402Version: 2,
                scheme: accept.scheme || "exact",
                network: accept.network,
                payload: {
                    authorization: {
                        from: from,
                        to: payTo,
                        value: String(valueUnits),
                        validAfter: validAfter,
                        validBefore: validBefore,
                        nonce: nonce,
                    },
                    signature: signature,
                },
            };
            var paymentB64 = btoa(JSON.stringify(paymentPayload));

            setStatus(statusEl, "Processing payment…", "payment-pending");
            var paidResp = await fetch(orderPath, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-PAYMENT": paymentB64,
                },
                body: JSON.stringify(body),
            });

            if (!paidResp.ok) {
                var paidErr = await paidResp.json().catch(function () { return {}; });
                throw new Error(paidErr.detail || paidErr.error || "Payment failed: " + paidResp.status);
            }

            var result = await paidResp.json();
            setStatus(statusEl, "Payment successful! Redirecting…", "payment-ok");
            setTimeout(function () {
                var tok = result.management_token
                    ? "?token=" + encodeURIComponent(result.management_token)
                    : "";
                window.location.href = "/order/status/" + result.vm_id + tok;
            }, 1000);
        } catch (err) {
            if (err && err.code === 4001) {
                setStatus(statusEl, "Payment cancelled.", "payment-warn");
            } else {
                setStatus(statusEl, "Error: " + (err && err.message ? err.message : String(err)), "payment-error");
                console.error("EVM payment error:", err);
            }
            if (button) button.disabled = false;
        }
    }

    ns.payWithEvm = payWithEvm;
})();
