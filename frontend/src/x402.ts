/** Shared x402 v2 challenge parsing and paid-request replay. */

export interface X402Acceptance {
  scheme?: string;
  network: string;
  amount: string;
  asset?: string;
  payTo?: string;
  pay_to?: string;
  maxTimeoutSeconds?: number;
  extra?: Record<string, unknown>;
}

export interface X402Requirements {
  x402Version?: number;
  resource?: Record<string, unknown>;
  accepts: X402Acceptance[];
  [key: string]: unknown;
}

export interface X402RequestSpec {
  url: string;
  method: string;
  headers?: Record<string, string>;
  body?: string;
}

export interface X402Quote {
  request: X402RequestSpec;
  requirements: X402Requirements;
  accept: X402Acceptance;
}

export type X402QuoteResult =
  | { kind: "quote"; quote: X402Quote }
  | { kind: "response"; response: Response };

function decodeBase64Json(value: string): unknown {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const bytes = Uint8Array.from(atob(padded), (char) => char.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}

export function encodeBase64Json(value: unknown): string {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function isRequirements(value: unknown): value is X402Requirements {
  if (!value || typeof value !== "object") return false;
  const accepts = (value as { accepts?: unknown }).accepts;
  return (
    Array.isArray(accepts) &&
    accepts.every(
      (accept) =>
        !!accept &&
        typeof accept === "object" &&
        typeof (accept as { network?: unknown }).network === "string" &&
        typeof (accept as { amount?: unknown }).amount === "string",
    )
  );
}

export async function paymentRequirements(response: Response): Promise<X402Requirements> {
  const encoded =
    response.headers.get("payment-required") || response.headers.get("x-payment-required");
  if (encoded) {
    const decoded = decodeBase64Json(encoded);
    if (isRequirements(decoded)) return decoded;
  }

  const body = (await response
    .clone()
    .json()
    .catch(() => null)) as unknown;
  if (isRequirements(body)) return body;
  if (body && typeof body === "object") {
    const nested =
      (body as { paymentRequirements?: unknown; payment_required?: unknown }).paymentRequirements ??
      (body as { payment_required?: unknown }).payment_required;
    if (isRequirements(nested)) return nested;
  }
  throw new Error("The API returned 402 without valid x402 payment requirements.");
}

export function selectAcceptance(
  requirements: X402Requirements,
  network: string | readonly string[],
): X402Acceptance {
  const identifiers = Array.isArray(network) ? network : [network];
  const accept = requirements.accepts.find((candidate) => identifiers.includes(candidate.network));
  if (!accept) throw new Error(`The live quote does not accept ${identifiers.join(" or ")}.`);
  return accept;
}

export function fetchRequest(
  spec: X402RequestSpec,
  extraHeaders: Record<string, string> = {},
): Promise<Response> {
  return fetch(spec.url, {
    method: spec.method,
    headers: { ...spec.headers, ...extraHeaders },
    body: spec.method === "GET" || spec.method === "HEAD" ? undefined : spec.body,
  });
}

async function responseError(response: Response): Promise<Error> {
  const body = (await response
    .clone()
    .json()
    .catch(() => null)) as { detail?: unknown; error?: unknown } | null;
  const detail = body?.detail ?? body?.error;
  return new Error(
    typeof detail === "string" ? detail : `API request failed (${response.status}).`,
  );
}

export async function quoteX402(
  request: X402RequestSpec,
  network: string | readonly string[],
): Promise<X402QuoteResult> {
  const response = await fetchRequest(request);
  if (response.status !== 402) {
    if (!response.ok) throw await responseError(response);
    return { kind: "response", response };
  }
  const requirements = await paymentRequirements(response);
  return {
    kind: "quote",
    quote: { request, requirements, accept: selectAcceptance(requirements, network) },
  };
}

export async function executeX402(quote: X402Quote, signature: string): Promise<Response> {
  const response = await fetchRequest(quote.request, {
    "Payment-Signature": signature,
    // Compatibility for API deployments that still consume the pre-v2 name.
    "X-PAYMENT": signature,
  });
  if (!response.ok) throw await responseError(response);
  return response;
}

export function validateSignedPayment(quote: X402Quote, signature: string): void {
  let decoded: unknown;
  try {
    decoded = decodeBase64Json(signature.trim());
  } catch {
    throw new Error("Payment-Signature must be a base64-encoded x402 v2 payload.");
  }
  if (!decoded || typeof decoded !== "object") throw new Error("Invalid x402 payment payload.");
  const envelope = decoded as {
    x402Version?: unknown;
    scheme?: unknown;
    network?: unknown;
    accepted?: X402Acceptance;
    payload?: {
      authorization?: { from?: unknown; to?: unknown; value?: unknown };
      signature?: unknown;
      transaction?: unknown;
    };
  };
  const accepted: X402Acceptance =
    envelope.accepted ||
    ({
      scheme: typeof envelope.scheme === "string" ? envelope.scheme : undefined,
      network: typeof envelope.network === "string" ? envelope.network : "",
      amount: quote.accept.amount,
      asset: quote.accept.asset,
      payTo: quote.accept.payTo || quote.accept.pay_to,
    } satisfies X402Acceptance);
  const authorization = envelope.payload?.authorization;
  const payTo = quote.accept.payTo || quote.accept.pay_to;
  if (envelope.x402Version !== 2) throw new Error("Only x402 v2 payment payloads are accepted.");
  if ((accepted.scheme || "exact") !== (quote.accept.scheme || "exact")) {
    throw new Error("Payment scheme does not match the quote.");
  }
  if (accepted.network !== quote.accept.network)
    throw new Error("Payment network does not match the quote.");
  if (accepted.amount !== quote.accept.amount) {
    throw new Error("Payment amount does not match the quote.");
  }
  if (accepted.asset && accepted.asset !== quote.accept.asset) {
    throw new Error("Payment asset does not match the quote.");
  }
  const acceptedPayTo = accepted.payTo || accepted.pay_to;
  const addressMatches = quote.accept.network.startsWith("solana:")
    ? acceptedPayTo === payTo
    : String(acceptedPayTo).toLowerCase() === String(payTo).toLowerCase();
  if (!addressMatches) throw new Error("Payment payee does not match the quote.");

  if (quote.accept.network.startsWith("solana:")) {
    const transaction = envelope.payload?.transaction;
    if (typeof transaction !== "string" || transaction.length < 32) {
      throw new Error("Solana payment payload does not contain a signed transaction.");
    }
    try {
      atob(transaction.replace(/-/g, "+").replace(/_/g, "/"));
    } catch {
      throw new Error("Solana payment transaction is not valid base64.");
    }
    return;
  }
  if (typeof authorization?.from !== "string" || authorization.from.length === 0) {
    throw new Error("Payment authorization does not contain a payer.");
  }
  if (!authorization || String(authorization.to).toLowerCase() !== String(payTo).toLowerCase()) {
    throw new Error("Payment payee does not match the quote.");
  }
  if (String(authorization.value) !== accepted.amount) {
    throw new Error("Payment amount does not match the quote.");
  }
  if (typeof envelope.payload?.signature !== "string" || !envelope.payload.signature) {
    throw new Error("Payment authorization does not contain a signature.");
  }
}

export function humanTokenAmount(amount: string, decimals: number): string {
  const units = BigInt(amount);
  const divisor = 10n ** BigInt(decimals);
  const whole = units / divisor;
  const fraction = (units % divisor).toString().padStart(decimals, "0").replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : whole.toString();
}
