/**
 * Solana payment driver for Hyrule Cloud x402 checkout (Block H).
 *
 * Exposes window.HyrulePaymentSVM.pay(network, opts) where `network` is the
 * full object from GET /v1/payments/networks for a `solana:*` CAIP-2 entry
 * (caip2, token_address, token_decimals, rpc_url).
 *
 * Targets the major Solana wallets exposed via window.solana / window.solflare /
 * window.backpack. The wallet signs an SPL `transferChecked` for USDC; the
 * facilitator submits the signed transaction.
 *
 * @solana/web3.js + @solana/spl-token are loaded on demand from esm.sh — we
 * keep the EVM bundle untouched (~zero bytes) for users who never click the
 * Solana tab. Caches the ESM imports in module-level state after first use.
 *
 * Hard requirement (per feedback_verified_payment_chains.md): all chain
 * metadata flows from the backend's /v1/payments/networks. No hardcoded mints.
 */
(function () {
    "use strict";

    var WEB3_URL = "https://esm.sh/@solana/web3.js@1.95.0";
    var SPL_URL = "https://esm.sh/@solana/spl-token@0.4.9";

    // Lazy-loaded ESM modules + adapter cache.
    var _web3 = null;
    var _spl = null;

    async function loadSolanaModules() {
        if (_web3 && _spl) return { web3: _web3, spl: _spl };
        var pair = await Promise.all([import(WEB3_URL), import(SPL_URL)]);
        _web3 = pair[0];
        _spl = pair[1];
        return { web3: _web3, spl: _spl };
    }

    /**
     * Locate an injected wallet adapter. Order of preference: Phantom →
     * Solflare → Backpack. Returns the adapter object exposing
     * connect()/publicKey/signTransaction.
     */
    function detectWallet() {
        if (window.phantom && window.phantom.solana) return window.phantom.solana;
        if (window.solana && window.solana.isPhantom) return window.solana;
        if (window.solflare && window.solflare.isSolflare) return window.solflare;
        if (window.backpack) return window.backpack;
        return null;
    }

    /**
     * Build the X-PAYMENT header for an SVM exact payment.
     * Solana payload is `{transaction: <base64-signed-tx>}` per ExactSvmPayloadV2.
     */
    function buildPaymentHeader(network, signedTxBase64, requirements) {
        var payload = {
            x402Version: 2,
            scheme: "exact",
            network: network.caip2,
            payload: { transaction: signedTxBase64 },
            accepted: requirements,
        };
        return btoa(JSON.stringify(payload));
    }

    /**
     * Build + sign the SPL transferChecked transaction.
     *
     * @param {Object} wallet - the detected wallet adapter
     * @param {Object} network - full Solana network metadata
     * @param {Object} accept  - the matching accepts[] entry from the 402
     * @returns {Promise<string>} base64-encoded signed transaction
     */
    async function buildAndSignTransfer(wallet, network, accept) {
        var mods = await loadSolanaModules();
        var web3 = mods.web3;
        var spl = mods.spl;

        var connection = new web3.Connection(network.rpc_url, "confirmed");

        var payerPubkey = wallet.publicKey;
        if (!payerPubkey) throw new Error("Wallet did not expose publicKey after connect()");

        var mint = new web3.PublicKey(accept.token_address);
        var recipient = new web3.PublicKey(accept.pay_to);

        // Resolve the canonical SPL token program (not Token-2022). We only
        // target USDC for now, which lives on the classic Token program.
        var payerAta = await spl.getAssociatedTokenAddress(
            mint, payerPubkey, false, spl.TOKEN_PROGRAM_ID, spl.ASSOCIATED_TOKEN_PROGRAM_ID
        );
        var recipientAta = await spl.getAssociatedTokenAddress(
            mint, recipient, true, spl.TOKEN_PROGRAM_ID, spl.ASSOCIATED_TOKEN_PROGRAM_ID
        );

        // Amount is the dollar price * 10^decimals (mirrors EVM driver).
        var priceUsd = parseFloat((accept.price || "0").replace("$", ""));
        var decimals = accept.token_decimals != null ? accept.token_decimals : network.token_decimals;
        var rawAmount = Math.round(priceUsd * Math.pow(10, decimals));

        // BigInt for the SPL instruction — JS Number is fine for USDC at
        // <= ~$9e9 but the SPL helper expects bigint.
        var amount = BigInt(rawAmount);

        var ix = spl.createTransferCheckedInstruction(
            payerAta, mint, recipientAta, payerPubkey, amount, decimals,
            [], spl.TOKEN_PROGRAM_ID
        );

        var latest = await connection.getLatestBlockhash("confirmed");
        var tx = new web3.Transaction({
            feePayer: payerPubkey,
            recentBlockhash: latest.blockhash,
        }).add(ix);

        var signed = await wallet.signTransaction(tx);
        var serialized = signed.serialize();
        return btoa(String.fromCharCode.apply(null, serialized));
    }

    /**
     * Full SVM x402 round-trip (mirrors HyrulePaymentEVM.pay):
     *   1. POST orderPayload → 402 with X-PAYMENT-REQUIRED
     *   2. Wallet signs SPL transferChecked
     *   3. POST orderPayload + X-PAYMENT header → 200 with vm_id
     *
     * @param {Object} network - solana:* network row from /v1/payments/networks
     * @param {Object} opts: endpoint, orderPayload, onStatus, onSettled
     */
    async function pay(network, opts) {
        var wallet = detectWallet();
        if (!wallet) {
            throw new Error("No Solana wallet detected. Install Phantom, Solflare, or Backpack.");
        }
        var endpoint = opts.endpoint || "/api/vm/create";
        var orderPayload = opts.orderPayload;
        var setStatus = opts.onStatus || function () {};

        setStatus("Connecting wallet…", "payment-pending");
        await wallet.connect();

        setStatus("Requesting payment details…", "payment-pending");
        var firstResp = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(orderPayload),
        });

        if (firstResp.status !== 402) {
            if (firstResp.ok) {
                var okResult = await firstResp.json();
                if (opts.onSettled) opts.onSettled(okResult);
                return { result: okResult, network: network };
            }
            var errBody = await firstResp.json().catch(function () { return {}; });
            throw new Error(errBody.detail || errBody.error || "API error " + firstResp.status);
        }

        var headerB64 = firstResp.headers.get("x-payment-required");
        if (!headerB64) throw new Error("Missing X-PAYMENT-REQUIRED header in 402");
        var paymentReq = JSON.parse(atob(headerB64));
        var accept = (paymentReq.accepts || []).find(function (a) {
            return a.network === network.caip2;
        });
        if (!accept) {
            throw new Error("Server did not advertise " + network.caip2);
        }
        if (accept.family && accept.family !== "svm") {
            throw new Error("Backend returned non-SVM family for " + network.caip2 + ": " + accept.family);
        }

        setStatus("Loading Solana libraries…", "payment-pending");
        // Pre-warm web3 + spl-token caches before the sign prompt.
        await loadSolanaModules();

        setStatus("Sign the transaction in your wallet…", "payment-pending");
        var signedTxB64 = await buildAndSignTransfer(wallet, network, accept);

        var paymentB64 = buildPaymentHeader(network, signedTxB64, accept);

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

    window.HyrulePaymentSVM = {
        pay: pay,
        // Exported for unit-testing in browser devtools (not used by dispatcher).
        _detectWallet: detectWallet,
        _buildPaymentHeader: buildPaymentHeader,
        _loadSolanaModules: loadSolanaModules,
    };
})();
