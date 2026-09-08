// Shared frontend types (issue #14 TS migration).

/** GET /v1/vm/{id}/status — VMPublicStatusResponse.
 *
 * The API carries TWO status vocabularies and they are not interchangeable:
 *  - `status` is VMStatus: provisioning|ready|running|suspended|failed|destroyed
 *  - `launch_proof_status` is the customer-facing launch-proof contract:
 *    accepted|payment_required|provisioning|provisioned|failed|rolled_back
 *
 * This type previously declared `status` with the launch-proof vocabulary, so
 * a live `ready` matched nothing and the page sat on "Building your VM…"
 * forever. Use `displayState()` rather than reading either field directly.
 */
export type VmLifecycleStatus =
  | "provisioning"
  | "ready"
  | "running"
  | "suspended"
  | "failed"
  | "destroyed";

export type LaunchProofStatus =
  | "accepted"
  | "payment_required"
  | "provisioning"
  | "provisioned"
  | "failed"
  | "rolled_back";

export interface VmStatus {
  expiry?: {
    state:
      | "active"
      | "expired"
      | "deletion_eligible"
      | "deleting"
      | "retaining"
      | "retained"
      | "restoring"
      | "destroyed"
      | "not_set"
      | "not_applicable";
    grace_ends_at?: string | null;
    retained_until?: string | null;
    observed_at?: string;
    deletion_eligible?: boolean;
    message?: string;
  } | null;
  status?: VmLifecycleStatus;
  launch_proof_status?: LaunchProofStatus;
  payment_status?: string;
  dns_aaaa_verified?: boolean;
  ssh_smoke_status?: string;
  rollback_available?: boolean;
  /** The API field is `hostname`. `fqdn` has never existed on this response. */
  hostname?: string;
  ipv6?: string;
  ipv6_prefix?: string;
  expires_at?: string;
  profile?: string;
  resources?: { vcpu: number; ram_mb: number; disk_gb: number };
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
  headers?: Record<string, string>;
  onSuccess?: (result: Record<string, unknown>) => void;
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
