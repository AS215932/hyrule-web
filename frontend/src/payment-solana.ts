/** Solana x402 payment adapter using Wallet Standard and the official SVM SDK. */

import { x402Client } from "@x402/core/client";
import type { Network, PaymentRequired } from "@x402/core/types";
import { ExactSvmScheme } from "@x402/svm/exact/client";
import {
  address,
  getTransactionDecoder,
  getTransactionEncoder,
  type SignatureDictionary,
  type TransactionSigner,
} from "@solana/kit";
import {
  SolanaSignTransaction,
  type SolanaSignTransactionFeature,
} from "@solana/wallet-standard-features";
import type { Wallet, WalletAccount } from "@wallet-standard/base";
import { getWallets } from "@wallet-standard/app";
import {
  StandardConnect,
  StandardEvents,
  type StandardConnectFeature,
  type StandardEventsFeature,
} from "@wallet-standard/features";

import type { PaymentNetwork, X402PayOptions } from "./types";
import { encodeBase64Json, executeX402, quoteX402, type X402Quote } from "./x402";

type CompatibleWallet = Wallet & {
  features: Wallet["features"] & StandardConnectFeature & SolanaSignTransactionFeature;
};

const SVM_ADDRESS = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

function status(element: HTMLElement | null, message: string, tone = ""): void {
  if (!element) return;
  element.textContent = message;
  element.className = "payment-status " + tone;
}

function isCompatible(wallet: Wallet, chain: string): wallet is CompatibleWallet {
  return (
    wallet.chains.includes(chain as Wallet["chains"][number]) &&
    StandardConnect in wallet.features &&
    SolanaSignTransaction in wallet.features
  );
}

export function compatibleSolanaWallets(
  chain: string,
  wallets: readonly Wallet[] = getWallets().get(),
): CompatibleWallet[] {
  return wallets
    .filter((wallet): wallet is CompatibleWallet => isCompatible(wallet, chain))
    .sort((left, right) => {
      const authorized = Number(right.accounts.length > 0) - Number(left.accounts.length > 0);
      return authorized || left.name.localeCompare(right.name);
    });
}

function accountFor(accounts: readonly WalletAccount[], chain: string): WalletAccount | undefined {
  return accounts.find(
    (account) =>
      account.chains.includes(chain as WalletAccount["chains"][number]) &&
      account.features.includes(SolanaSignTransaction),
  );
}

export async function connectSolanaWallet(
  chain: string,
  wallets?: readonly Wallet[],
): Promise<{ wallet: CompatibleWallet; account: WalletAccount }> {
  const wallet = compatibleSolanaWallets(chain, wallets)[0];
  if (!wallet) {
    throw new Error(
      "No Wallet Standard wallet supporting Solana transaction signing is available.",
    );
  }
  let account = accountFor(wallet.accounts, chain);
  if (!account) {
    const connected = await wallet.features[StandardConnect].connect();
    account = accountFor(connected.accounts, chain);
  }
  if (!account) throw new Error(`${wallet.name} did not provide a Solana account.`);
  return { wallet, account };
}

/** Adapt Wallet Standard's byte-oriented API to Solana Kit's partial signer. */
export function walletStandardSigner(
  wallet: CompatibleWallet,
  initialAccount: WalletAccount,
  chain: string,
): TransactionSigner {
  let currentAccount: WalletAccount | null = initialAccount;
  const events = wallet.features[StandardEvents] as
    | StandardEventsFeature[typeof StandardEvents]
    | undefined;
  const unsubscribe = events?.on("change", ({ accounts }) => {
    if (accounts) {
      currentAccount =
        accounts.find((candidate) => candidate.address === initialAccount.address) || null;
    }
  });

  return {
    address: address(initialAccount.address),
    async signTransactions(transactions) {
      const encoder = getTransactionEncoder();
      const decoder = getTransactionDecoder();
      const signerAddress = address(initialAccount.address);
      try {
        const signingAccount = currentAccount;
        if (!signingAccount || signingAccount.address !== initialAccount.address) {
          throw new Error("The selected Solana wallet account changed before signing.");
        }
        const outputs = await wallet.features[SolanaSignTransaction].signTransaction(
          ...transactions.map((transaction) => ({
            account: signingAccount,
            transaction: Uint8Array.from(encoder.encode(transaction)),
            chain: chain as Wallet["chains"][number],
          })),
        );
        if (outputs.length !== transactions.length) {
          throw new Error("The Solana wallet did not sign every requested transaction.");
        }
        return outputs.map((output): SignatureDictionary => {
          const signed = decoder.decode(output.signedTransaction);
          const signature = signed.signatures[signerAddress];
          if (!signature) {
            throw new Error("The Solana wallet did not sign with the selected account.");
          }
          return { [signerAddress]: signature } as SignatureDictionary;
        });
      } finally {
        unsubscribe?.();
      }
    },
  };
}

export function validateSolanaQuote(quote: X402Quote, network: PaymentNetwork): void {
  const accept = quote.accept;
  const payTo = accept.payTo || accept.pay_to;
  const feePayer = accept.extra?.feePayer;
  if (network.family !== "svm" || !network.caip2 || !network.wallet_chain) {
    throw new Error("The selected Solana network metadata is incomplete.");
  }
  if ((accept.scheme || "exact") !== "exact") {
    throw new Error("The live quote does not use the exact payment scheme.");
  }
  if (accept.network !== network.caip2) {
    throw new Error("The selected Solana network does not match the live quote.");
  }
  if (accept.asset !== network.token_address) {
    throw new Error("The quoted token mint is not enabled for this network.");
  }
  if (!payTo || (network.pay_to && payTo !== network.pay_to)) {
    throw new Error("The quoted Solana recipient does not match the enabled receiver.");
  }
  if (!/^\d+$/.test(accept.amount) || BigInt(accept.amount) <= 0n) {
    throw new Error("The live quote contains an invalid base-unit amount.");
  }
  if (typeof feePayer !== "string" || !SVM_ADDRESS.test(feePayer)) {
    throw new Error("The facilitator did not provide a valid Solana fee payer.");
  }
}

export async function signSolanaX402Quote(
  quote: X402Quote,
  network: PaymentNetwork,
  wallets?: readonly Wallet[],
): Promise<string> {
  validateSolanaQuote(quote, network);
  const { wallet, account } = await connectSolanaWallet(network.wallet_chain!, wallets);
  const signer = walletStandardSigner(wallet, account, network.wallet_chain!);
  const client = new x402Client().register(
    network.caip2 as Network,
    new ExactSvmScheme(signer, { rpcUrl: network.rpc_url }),
  );
  // Registering only the chosen CAIP-2 network makes the SDK select this exact
  // acceptance even when the challenge also offers EVM payment options.
  if (
    quote.requirements.x402Version !== 2 ||
    !quote.requirements.resource ||
    typeof quote.requirements.resource.url !== "string"
  ) {
    throw new Error("The API returned incomplete x402 v2 resource metadata.");
  }
  const required = {
    ...quote.requirements,
    accepts: [quote.accept],
  } as unknown as PaymentRequired;
  const payload = await client.createPaymentPayload(required);
  return encodeBase64Json(payload);
}

async function payWithSolana(options: X402PayOptions): Promise<void> {
  const { network, button, statusEl, orderPath, body, headers = {}, onSuccess } = options;
  if (button) button.disabled = true;
  status(statusEl, "Requesting exact Solana payment details…", "payment-pending");
  try {
    const quoted = await quoteX402(
      {
        url: orderPath,
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers },
        body: JSON.stringify(body),
      },
      network.caip2 || network.key,
    );
    let result: Record<string, unknown>;
    if (quoted.kind === "response") {
      result = (await quoted.response.json()) as Record<string, unknown>;
    } else {
      status(statusEl, "Connect and sign the Solana transaction…", "payment-pending");
      const signature = await signSolanaX402Quote(quoted.quote, network);
      status(statusEl, "Settling the Solana payment…", "payment-pending");
      const response = await executeX402(quoted.quote, signature);
      result = (await response.json()) as Record<string, unknown>;
    }
    status(statusEl, "Payment successful! Redirecting…", "payment-ok");
    if (onSuccess) {
      onSuccess(result);
      return;
    }
    const vmId = typeof result.vm_id === "string" ? result.vm_id : "";
    if (vmId && typeof result.management_token === "string") {
      sessionStorage.setItem(
        "hyr_vm_mgmt:" + vmId,
        JSON.stringify({
          token: result.management_token,
          url: result.management_url || null,
          issued: Date.now(),
        }),
      );
    }
    setTimeout(() => {
      window.location.href = vmId ? "/order/status/" + vmId : "/order";
    }, 1000);
  } catch (error) {
    if ((error as { code?: number }).code === 4001) {
      status(statusEl, "Payment cancelled.", "payment-warn");
    } else {
      const message = error instanceof Error ? error.message : String(error);
      status(statusEl, "Error: " + message, "payment-error");
      console.error("Solana payment error:", error);
    }
    if (button) button.disabled = false;
  }
}

const namespace = (window.HyrulePayments = window.HyrulePayments || {});
namespace.payWithSolana = payWithSolana;
