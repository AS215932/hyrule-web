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

/** One entry from GET /v1/payments/networks (the backend is the source of truth). */
export interface PaymentNetwork {
  key: string;
  family: string; // "evm" | "svm"
  display_name: string;
  asset: string;
  caip2?: string;
  chain_id: number;
  token_address: string;
  token_decimals: number;
  eip712_domain: { name: string; version: string };
  native_currency?: { name: string; symbol: string; decimals: number };
  rpc_url?: string;
  block_explorer_url?: string;
  testnet?: boolean;
}

export interface EvmPayOptions {
  network: PaymentNetwork;
  button: HTMLButtonElement | null;
  statusEl: HTMLElement | null;
  orderPath: string;
  body: Record<string, unknown>;
}

export interface NativePayOptions {
  orderForm: HTMLFormElement;
  render: HTMLElement | null;
  onStatus: (msg: string, cls?: string) => void;
}

export interface HyrulePaymentsNS {
  payWithEvm?: (opts: EvmPayOptions) => Promise<void> | void;
  payWithSolana?: (opts: EvmPayOptions) => Promise<void> | void;
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
