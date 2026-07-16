import { getEvmProvider } from "./payment-evm";
import type { Eip1193Provider, PaymentNetwork } from "./types";

interface Challenge {
  nonce: string;
  message: string;
  expires_at: string;
}

function status(message: string, tone = ""): void {
  const element = document.getElementById("wallet-auth-status");
  if (!element) return;
  element.textContent = message;
  element.className = "payment-status " + tone;
}

async function jsonError(response: Response, fallback: string): Promise<Error> {
  const body = await response.json().catch(() => ({}));
  return new Error(body.detail || body.error || fallback);
}

async function accounts(provider: Eip1193Provider): Promise<string[]> {
  return (await provider.request({ method: "eth_requestAccounts" })) as string[];
}

async function chainId(provider: Eip1193Provider): Promise<number> {
  const raw = (await provider.request({ method: "eth_chainId" })) as string;
  const selected = Number.parseInt(raw, 16);
  if (!Number.isSafeInteger(selected) || selected <= 0) {
    throw new Error("The wallet returned an invalid chain ID.");
  }
  return selected;
}

export function personalMessageHex(message: string): string {
  const bytes = new TextEncoder().encode(message);
  return (
    "0x" +
    Array.from(bytes)
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("")
  );
}

export async function signWalletMessage(
  provider: Eip1193Provider,
  address: string,
  message: string,
): Promise<string> {
  const encoded = personalMessageHex(message);
  try {
    return (await provider.request({
      method: "personal_sign",
      params: [encoded, address],
    })) as string;
  } catch (error) {
    if ((error as { code?: number }).code === 4001) throw error;
    return (await provider.request({
      method: "personal_sign",
      params: [address, encoded],
    })) as string;
  }
}

async function switchWalletChain(
  provider: Eip1193Provider,
  network: PaymentNetwork,
): Promise<void> {
  const chainIdHex = `0x${network.chain_id.toString(16)}`;
  try {
    await provider.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: chainIdHex }],
    });
  } catch (error) {
    if ((error as { code?: number }).code !== 4902) throw error;
    await provider.request({
      method: "wallet_addEthereumChain",
      params: [
        {
          chainId: chainIdHex,
          chainName: network.display_name,
          nativeCurrency: network.native_currency || {
            name: "Ether",
            symbol: "ETH",
            decimals: 18,
          },
          rpcUrls: [network.rpc_url].filter(Boolean),
          blockExplorerUrls: [network.block_explorer_url].filter(Boolean),
        },
      ],
    });
  }
}

export async function resolveWalletAuthChain(
  provider: Eip1193Provider,
  onSwitch?: (network: PaymentNetwork) => void,
): Promise<number> {
  const selected = await chainId(provider);
  const response = await fetch("/api/payments/networks");
  if (!response.ok) throw new Error("Could not load supported wallet chains.");
  const body = (await response.json()) as { networks?: PaymentNetwork[] };
  const networks = (Array.isArray(body.networks) ? body.networks : []).filter(
    (network) =>
      network.family === "evm" && Number.isSafeInteger(network.chain_id) && network.chain_id > 0,
  );
  if (!networks.length) throw new Error("No EVM wallet chains are currently enabled.");
  if (networks.some((network) => network.chain_id === selected)) return selected;

  let lastError: unknown;
  for (const network of networks) {
    try {
      onSwitch?.(network);
      await switchWalletChain(provider, network);
      const switched = await chainId(provider);
      if (switched === network.chain_id) return switched;
    } catch (error) {
      if ((error as { code?: number }).code === 4001) throw error;
      lastError = error;
    }
  }

  const reason = lastError instanceof Error ? `: ${lastError.message}` : ".";
  throw new Error(`Could not switch this wallet to an enabled chain${reason}`);
}

async function challenge(
  action: "login" | "link" | "rotate",
  address: string,
  selectedChain: number,
): Promise<Challenge> {
  const response = await fetch("/api/auth/wallet/challenge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, address, chain_id: selectedChain }),
  });
  if (!response.ok) throw await jsonError(response, "Could not create wallet challenge.");
  return response.json();
}

async function verify(
  nonce: string,
  signature: string,
  secondarySignature?: string,
): Promise<void> {
  const response = await fetch("/api/auth/wallet/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      nonce,
      signature,
      secondary_signature: secondarySignature || null,
    }),
  });
  if (!response.ok) throw await jsonError(response, "Wallet verification failed.");
}

async function providerOrThrow(): Promise<Eip1193Provider> {
  const provider = await getEvmProvider();
  if (!provider) throw new Error("No EVM wallet is available.");
  return provider;
}

async function login(): Promise<void> {
  status("Connecting wallet…", "payment-pending");
  const provider = await providerOrThrow();
  const [address] = await accounts(provider);
  if (!address) throw new Error("The wallet returned no account.");
  const selectedChain = await resolveWalletAuthChain(provider, (network) => {
    status(`Switch your wallet to ${network.display_name}…`, "payment-pending");
  });
  const request = await challenge("login", address, selectedChain);
  status("Sign the Hyrule login challenge…", "payment-pending");
  await verify(request.nonce, await signWalletMessage(provider, address, request.message));
  status("Signed in. Redirecting…", "payment-ok");
  window.location.href = walletLogin?.dataset.next || "/dashboard";
}

async function link(): Promise<void> {
  status("Connecting wallet…", "payment-pending");
  const provider = await providerOrThrow();
  const [address] = await accounts(provider);
  if (!address) throw new Error("The wallet returned no account.");
  const selectedChain = await resolveWalletAuthChain(provider, (network) => {
    status(`Switch your wallet to ${network.display_name}…`, "payment-pending");
  });
  const request = await challenge("link", address, selectedChain);
  status("Sign the wallet-link challenge…", "payment-pending");
  await verify(request.nonce, await signWalletMessage(provider, address, request.message));
  status("Wallet linked. Reloading…", "payment-ok");
  window.location.reload();
}

async function rotate(container: HTMLElement): Promise<void> {
  const current = (container.dataset.wallet || "").toLowerCase();
  const requested = window.prompt("Enter the new primary wallet address:")?.trim();
  if (!requested || !/^0x[0-9a-fA-F]{40}$/.test(requested)) {
    throw new Error("Enter a valid 0x wallet address.");
  }
  if (requested.toLowerCase() === current) throw new Error("Choose a different wallet.");
  const provider = await providerOrThrow();
  const [active] = await accounts(provider);
  if (!active || active.toLowerCase() !== current) {
    throw new Error("Select the currently linked wallet before starting rotation.");
  }
  const selectedChain = await resolveWalletAuthChain(provider, (network) => {
    status(`Switch your wallet to ${network.display_name}…`, "payment-pending");
  });
  const request = await challenge("rotate", requested, selectedChain);
  status("First signature: approve with the current wallet…", "payment-pending");
  const currentSignature = await signWalletMessage(provider, active, request.message);

  status(
    "Switch your wallet to the new address, then approve the account request…",
    "payment-pending",
  );
  try {
    await provider.request({ method: "wallet_requestPermissions", params: [{ eth_accounts: {} }] });
  } catch (error) {
    if ((error as { code?: number }).code === 4001) throw error;
  }
  const [next] = await accounts(provider);
  if (!next || next.toLowerCase() !== requested.toLowerCase()) {
    throw new Error("The selected wallet does not match the requested new address.");
  }
  status("Second signature: approve with the new wallet…", "payment-pending");
  const nextSignature = await signWalletMessage(provider, next, request.message);
  await verify(request.nonce, currentSignature, nextSignature);
  status("Primary wallet rotated. Reloading…", "payment-ok");
  window.location.reload();
}

function run(action: () => Promise<void>): void {
  void action().catch((error: unknown) => {
    if ((error as { code?: number }).code === 4001) {
      status("Wallet request cancelled.", "payment-warn");
      return;
    }
    status(error instanceof Error ? error.message : String(error), "payment-error");
  });
}

const walletLogin = document.getElementById("wallet-login") as HTMLButtonElement | null;
walletLogin?.addEventListener("click", () => run(login));
document.getElementById("wallet-link")?.addEventListener("click", () => run(link));
const walletContainer = document.getElementById("wallet-account");
document.getElementById("wallet-rotate")?.addEventListener("click", () => {
  if (walletContainer) run(() => rotate(walletContainer));
});
