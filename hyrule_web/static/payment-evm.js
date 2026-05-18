/**
 * EVM payment driver for Hyrule Cloud x402 checkout.
 *
 * Exposes window.HyrulePaymentEVM.pay(network, opts) where `network` is the
 * full object from GET /v1/payments/networks (caip2, chain_id, token_address,
 * token_decimals, eip712_domain, rpc_url, block_explorer_url, display_name).
 *
 * The dispatcher (payment.js) reads the selected chain and calls into here.
 * All chain-specific metadata flows from the backend — never hardcode here.
 *
 * Zero dependencies. Targets EIP-1193 wallets (MetaMask, Rabby, Coinbase,
 * Brave) with USDC on the chosen chain.
 */
(function () {
    "use strict";

    function chainIdHex(chainId) {
        return "0x" + chainId.toString(16);
    }

    function bytes32Nonce() {
        return "0x" + Array.from(crypto.getRandomValues(new Uint8Array(32)))
            .map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
    }

    async function ensureChain(network) {
        // wallet_switchEthereumChain → falls back to wallet_addEthereumChain on 4902
        var hex = chainIdHex(network.chain_id);
        try {
            await window.ethereum.request({
                method: "wallet_switchEthereumChain",
                params: [{ chainId: hex }],
            });
        } catch (err) {
            if (err && err.code === 4902) {
                await window.ethereum.request({
                    method: "wallet_addEthereumChain",
                    params: [{
                        chainId: hex,
                        chainName: network.display_name,
                        nativeCurrency: { name: "ETH", symbol: "ETH", decimals: 18 },
                        rpcUrls: [network.rpc_url],
                        blockExplorerUrls: [network.block_explorer_url],
                    }],
                });
            } else {
                throw err;
            }
        }
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
                from: from, to: payTo,
                value: String(valueUnits),
                validAfter: String(validAfter),
                validBefore: String(validBefore),
                nonce: nonce,
            },
        };
    }

    /**
     * Build an x402 V2 X-PAYMENT header for the given (network, signed authorization).
     */
    function buildPaymentHeader(network, from, payTo, valueUnits, validAfter, validBefore, nonce, signature) {
        var payload = {
            x402Version: 2,
            scheme: "exact",
            network: network.caip2,
            payload: {
                authorization: {
                    from: from,
                    to: payTo,
                    value: String(valueUnits),
                    validAfter: String(validAfter),
                    validBefore: String(validBefore),
                    nonce: nonce,
                },
                signature: signature,
            },
        };
        return btoa(JSON.stringify(payload));
    }

    /**
     * Perform the full two-stage x402 payment:
     *   1. POST orderPayload → 402 (server tells us amount + payTo)
     *   2. wallet signs EIP-3009 authorization for THIS chain
     *   3. POST orderPayload + X-PAYMENT header → 200 with vm_id
     *
     * @param {Object} network - full network row from /v1/payments/networks
     * @param {Object} opts:
     *   - endpoint: API path (default "/api/vm/create")
     *   - orderPayload: object posted as JSON
     *   - onStatus(msg, css_class): UI status callback
     *   - onSettled(apiResult): called with the final 200 body
     * @returns {Promise<{result, network}>}
     */
    async function pay(network, opts) {
        if (!window.ethereum) {
            throw new Error("No EIP-1193 wallet detected (install MetaMask, Rabby, or Coinbase Wallet).");
        }
        var endpoint = opts.endpoint || "/api/vm/create";
        var orderPayload = opts.orderPayload;
        var setStatus = opts.onStatus || function () {};

        setStatus("Connecting wallet…", "payment-pending");
        var accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
        var from = accounts[0];

        setStatus("Switching to " + network.display_name + "…", "payment-pending");
        await ensureChain(network);

        setStatus("Requesting payment details…", "payment-pending");
        var firstResp = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(orderPayload),
        });

        if (firstResp.status !== 402) {
            // Either an outright 2xx (dev-bypass / pre-paid) or an error.
            if (firstResp.ok) {
                var okResult = await firstResp.json();
                if (opts.onSettled) opts.onSettled(okResult);
                return { result: okResult, network: network };
            }
            var errBody = await firstResp.json().catch(function () { return {}; });
            throw new Error(errBody.detail || errBody.error || "API error " + firstResp.status);
        }

        // Parse the multi-chain 402 and pick the entry matching this network.
        var headerB64 = firstResp.headers.get("x-payment-required");
        if (!headerB64) throw new Error("Missing X-PAYMENT-REQUIRED header in 402");
        var paymentReq = JSON.parse(atob(headerB64));
        var accept = (paymentReq.accepts || []).find(function (a) {
            return a.network === network.caip2;
        });
        if (!accept) {
            throw new Error("Server did not advertise " + network.caip2 + " (got " +
                (paymentReq.accepts || []).map(function (a) { return a.network; }).join(", ") + ")");
        }

        var priceUsd = parseFloat((accept.price || "0").replace("$", ""));
        // Use server-supplied decimals so we don't drift from on-chain truth.
        var decimals = accept.token_decimals != null ? accept.token_decimals : network.token_decimals;
        var valueUnits = Math.round(priceUsd * Math.pow(10, decimals));
        var payTo = accept.pay_to || accept.payTo;
        if (!payTo) throw new Error("Server 402 omitted pay_to");

        var nonce = bytes32Nonce();
        var nowSec = Math.floor(Date.now() / 1000);
        var validAfter = nowSec - 600;
        var validBefore = nowSec + 3600;

        var typedData = buildTypedData(network, from, payTo, valueUnits, validAfter, validBefore, nonce);

        setStatus("Sign in your wallet to authorize " + (priceUsd) + " USDC on " + network.display_name + "…", "payment-pending");
        var signature = await window.ethereum.request({
            method: "eth_signTypedData_v4",
            params: [from, JSON.stringify(typedData)],
        });

        var paymentB64 = buildPaymentHeader(
            network, from, payTo, valueUnits, validAfter, validBefore, nonce, signature
        );

        setStatus("Settling payment via facilitator…", "payment-pending");
        var paidResp = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-PAYMENT": paymentB64 },
            body: JSON.stringify(orderPayload),
        });
        if (!paidResp.ok) {
            var paidErr = await paidResp.json().catch(function () { return {}; });
            throw new Error(paidErr.detail || paidErr.error || "Payment failed: " + paidResp.status);
        }

        var result = await paidResp.json();
        if (opts.onSettled) opts.onSettled(result);
        return { result: result, network: network };
    }

    window.HyrulePaymentEVM = {
        pay: pay,
        // Exported for unit-testing in browser dev tools; not used by dispatcher.
        _buildTypedData: buildTypedData,
        _buildPaymentHeader: buildPaymentHeader,
    };
})();
