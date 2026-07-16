// Shared frontend types (issue #14 TS migration).

export interface VmStatus {
  status: "payment_required" | "provisioning" | "provisioned" | "failed" | "rolled_back";
  payment_status?: string;
  dns_aaaa_verified?: boolean;
  ssh_smoke_status?: string;
  rollback_available?: boolean;
  fqdn?: string;
  ipv6?: string;
  operator_message?: string;
  customer_message?: string;
}

/** Minimal EIP-1193 provider surface the EVM payment flow uses. */
export interface Eip1193Provider {
  request(args: { method: string; params?: unknown[] | Record<string, unknown> }): Promise<unknown>;
}

interface PaymentNetworkBase {
  key: string;
  display_name: string;
  asset: string;
  caip2?: string;
  token_address: string;
  token_decimals: number;
  native_currency?: { name: string; symbol: string; decimals: number };
  rpc_url?: string;
  block_explorer_url?: string;
  pay_to?: string;
  testnet?: boolean;
}

/** One entry from GET /v1/payments/networks (the backend is the source of truth). */
export type PaymentNetwork =
  | (PaymentNetworkBase & {
      family: "evm";
      chain_id: number;
      eip712_domain?: { name: string; version: string };
      wallet_chain?: string;
    })
  | (PaymentNetworkBase & {
      family: "svm";
      chain_id: null;
      wallet_chain: string;
      eip712_domain?: never;
    });

export interface X402PayOptions {
  network: PaymentNetwork;
  button: HTMLButtonElement | null;
  statusEl: HTMLElement | null;
  orderPath: string;
  body: Record<string, unknown>;
  headers?: Record<string, string>;
  onSuccess?: (result: Record<string, unknown>) => void;
}

export type EvmPayOptions = X402PayOptions;

export interface NativePayOptions {
  orderForm: HTMLFormElement;
  render: HTMLElement | null;
  onStatus: (msg: string, cls?: string) => void;
}

export interface HyrulePaymentsNS {
  payWithEvm?: (opts: X402PayOptions) => Promise<void> | void;
  payWithSolana?: (opts: X402PayOptions) => Promise<void> | void;
}

export interface HyrulePaymentNativeNS {
  pay: (asset: string, opts: NativePayOptions) => Promise<void>;
}

/** EIP-712 TransferWithAuthorization typed-data envelope (x402 exact scheme). */
export interface TransferWithAuthorizationTypedData {
  types: Record<string, { name: string; type: string }[]>;
  domain: { name: string; version: string; chainId: number; verifyingContract: string };
  primaryType: "TransferWithAuthorization";
  message: {
    from: string;
    to: string;
    value: string;
    validAfter: string;
    validBefore: string;
    nonce: string;
  };
}
