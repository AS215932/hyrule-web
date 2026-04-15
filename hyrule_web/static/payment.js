/**
 * x402 browser payment flow for Hyrule Cloud.
 *
 * Handles wallet connection, EIP-712 signing (EIP-3009 TransferWithAuthorization),
 * and x402 payment header construction. ~150 lines, zero dependencies.
 *
 * Requires: MetaMask, Rabby, or any EIP-1193 browser wallet with USDC on Base.
 */

(function () {
    "use strict";

    var USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
    var BASE_CHAIN_ID = 8453;

    var payBtn = document.getElementById("pay-btn");
    var statusEl = document.getElementById("payment-status");

    if (!payBtn || !statusEl) return;

    function setStatus(msg, cls) {
        statusEl.textContent = msg;
        statusEl.className = "payment-status " + (cls || "");
    }

    payBtn.addEventListener("click", async function () {
        if (!window.ethereum) {
            setStatus("No wallet detected. Install MetaMask or Rabby to continue.", "payment-error");
            return;
        }

        payBtn.disabled = true;
        setStatus("Connecting wallet\u2026", "payment-pending");

        try {
            // 1. Connect wallet
            var accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
            var from = accounts[0];

            // 2. Switch to Base
            try {
                await window.ethereum.request({
                    method: "wallet_switchEthereumChain",
                    params: [{ chainId: "0x" + BASE_CHAIN_ID.toString(16) }],
                });
            } catch (switchErr) {
                if (switchErr.code === 4902) {
                    await window.ethereum.request({
                        method: "wallet_addEthereumChain",
                        params: [{
                            chainId: "0x" + BASE_CHAIN_ID.toString(16),
                            chainName: "Base",
                            nativeCurrency: { name: "ETH", symbol: "ETH", decimals: 18 },
                            rpcUrls: ["https://mainnet.base.org"],
                            blockExplorerUrls: ["https://basescan.org"],
                        }],
                    });
                } else {
                    throw switchErr;
                }
            }

            // 3. Gather order data from hidden form
            var form = document.getElementById("order-data");
            var fd = new FormData(form);
            var orderPayload = {
                os: fd.get("os"),
                size: fd.get("size"),
                duration_days: parseInt(fd.get("duration_days"), 10),
                ssh_pubkey: fd.get("ssh_pubkey"),
                domain_mode: fd.get("domain_mode") || "auto",
            };
            var hostname = fd.get("hostname");
            if (hostname) orderPayload.hostname = hostname;
            if (fd.get("domain") && fd.get("domain_mode") === "custom") {
                orderPayload.domain = fd.get("domain");
            }

            // 4. First request — get 402 with payment requirements
            setStatus("Requesting payment details\u2026", "payment-pending");
            var firstResp = await fetch("/api/vm/create", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(orderPayload),
            });

            if (firstResp.status !== 402) {
                if (firstResp.ok) {
                    var okResult = await firstResp.json();
                    window.location.href = "/order/status/" + okResult.vm_id;
                    return;
                }
                var errBody = await firstResp.json().catch(function () { return {}; });
                throw new Error(errBody.detail || errBody.error || "API error: " + firstResp.status);
            }

            // 5. Parse x402 payment requirements from header
            var paymentHeader = firstResp.headers.get("x-payment-required");
            if (!paymentHeader) throw new Error("Missing X-PAYMENT-REQUIRED header in 402 response");

            var paymentReq = JSON.parse(atob(paymentHeader));
            var accept = paymentReq.accepts[0];

            // Convert "$0.50" → 500000 (USDC has 6 decimals)
            var priceStr = (accept.price || "0").replace("$", "");
            var priceUsdc = Math.round(parseFloat(priceStr) * 1e6);

            // 6. Build EIP-712 typed data for EIP-3009 TransferWithAuthorization
            var nonce = "0x" + Array.from(crypto.getRandomValues(new Uint8Array(32)))
                .map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
            var now = Math.floor(Date.now() / 1000);
            var validAfter = String(now - 600);
            var validBefore = String(now + 3600);
            var payTo = accept.payTo || accept.pay_to;

            var typedData = {
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
                    name: "USD Coin",
                    version: "2",
                    chainId: BASE_CHAIN_ID,
                    verifyingContract: USDC_BASE,
                },
                primaryType: "TransferWithAuthorization",
                message: {
                    from: from,
                    to: payTo,
                    value: String(priceUsdc),
                    validAfter: validAfter,
                    validBefore: validBefore,
                    nonce: nonce,
                },
            };

            // 7. Request wallet signature — this triggers the popup
            setStatus("Please sign the payment in your wallet\u2026", "payment-pending");
            var signature = await window.ethereum.request({
                method: "eth_signTypedData_v4",
                params: [from, JSON.stringify(typedData)],
            });

            // 8. Build x402 payment header
            var paymentPayload = {
                x402Version: 2,
                scheme: accept.scheme || "exact",
                network: accept.network,
                payload: {
                    authorization: {
                        from: from,
                        to: payTo,
                        value: String(priceUsdc),
                        validAfter: validAfter,
                        validBefore: validBefore,
                        nonce: nonce,
                    },
                    signature: signature,
                },
            };

            var paymentB64 = btoa(JSON.stringify(paymentPayload));

            // 9. Retry with payment
            setStatus("Processing payment\u2026", "payment-pending");
            var paidResp = await fetch("/api/vm/create", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-PAYMENT": paymentB64,
                },
                body: JSON.stringify(orderPayload),
            });

            if (!paidResp.ok) {
                var paidErr = await paidResp.json().catch(function () { return {}; });
                throw new Error(paidErr.detail || paidErr.error || "Payment failed: " + paidResp.status);
            }

            var result = await paidResp.json();
            setStatus("Payment successful! Redirecting\u2026", "payment-ok");

            setTimeout(function () {
                window.location.href = "/order/status/" + result.vm_id;
            }, 1000);

        } catch (err) {
            if (err.code === 4001) {
                setStatus("Payment cancelled.", "payment-warn");
            } else {
                setStatus("Error: " + err.message, "payment-error");
                console.error("x402 payment error:", err);
            }
            payBtn.disabled = false;
        }
    });
})();
