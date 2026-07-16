import Ajv from "ajv";

import { signX402Quote } from "./payment-evm";
import "./styles/toolbox.css";
import type { PaymentNetwork } from "./types";
import {
  executeX402,
  humanTokenAmount,
  quoteX402,
  validateSignedPayment,
  type X402Quote,
  type X402RequestSpec,
} from "./x402";

type JsonObject = Record<string, unknown>;
type JsonSchema = {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  anyOf?: JsonSchema[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  format?: string;
};

interface ToolParameter {
  name: string;
  in: "path" | "query";
  required: boolean;
  description: string;
  example?: unknown;
  schema: JsonSchema;
}

interface ToolDefinition {
  operation_id: string;
  method: string;
  path: string;
  title: string;
  description: string;
  search_terms: string[];
  category: string;
  executable: boolean;
  input_schema: JsonSchema;
  input_example: JsonObject;
  parameters: ToolParameter[];
  price_display: string;
}

interface CatalogSnapshot {
  status: "live" | "stale" | "unavailable";
  execution_enabled?: boolean;
  tools: ToolDefinition[];
}

interface QuoteState {
  handle: string;
  tool: ToolDefinition;
  quote: X402Quote;
  network: PaymentNetwork;
  expiresAt: number;
  used: boolean;
}

interface ResultState {
  handle: string;
  tool: ToolDefinition;
  status: string;
  value?: unknown;
  raw?: string;
  jobToken?: string;
  statusUrl?: string;
  downloadUrl?: string;
  blob?: Blob;
  blobUrl?: string;
  filename?: string;
  mediaType?: string;
  receipt?: string;
  polling?: Promise<void>;
  pollError?: string;
}

interface ModelContextTool {
  name: string;
  description: string;
  inputSchema: JsonObject;
  annotations?: { readOnlyHint?: boolean; untrustedContentHint?: boolean };
  execute(input: JsonObject): Promise<unknown> | unknown;
}

interface ModelContext {
  registerTool(tool: ModelContextTool, options?: { signal?: AbortSignal }): Promise<void>;
}

const catalogEl = document.querySelector<HTMLScriptElement>("#toolbox-catalog-data");
const networksEl = document.querySelector<HTMLScriptElement>("#toolbox-networks-data");
const catalog = JSON.parse(
  catalogEl?.textContent || '{"status":"unavailable","tools":[]}',
) as CatalogSnapshot;
const networks = JSON.parse(networksEl?.textContent || "[]") as PaymentNetwork[];
const executableTools = catalog.tools.filter((tool) => tool.executable);
const toolsById = new Map(catalog.tools.map((tool) => [tool.operation_id, tool]));
const quotes = new Map<string, QuoteState>();
const results = new Map<string, ResultState>();
const ajv = new Ajv({ allErrors: true, strict: false });

let selectedTool: ToolDefinition | null = null;
let advancedDirty = false;
let selectedCategory = "all";

function requiredElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Missing toolbox element: ${selector}`);
  return element;
}

const searchInput = requiredElement<HTMLInputElement>("#toolbox-search");
const grid = requiredElement<HTMLElement>("#toolbox-grid");
const categoriesEl = requiredElement<HTMLElement>("#toolbox-categories");
const workspace = requiredElement<HTMLElement>("#toolbox-workspace");
const form = requiredElement<HTMLFormElement>("#toolbox-form");
const fieldsEl = requiredElement<HTMLElement>("#toolbox-fields");
const jsonEl = requiredElement<HTMLTextAreaElement>("#toolbox-json");
const networkEl = requiredElement<HTMLSelectElement>("#toolbox-network");
const validationEl = requiredElement<HTMLElement>("#toolbox-validation");
const quotePanel = requiredElement<HTMLElement>("#toolbox-quote-panel");
const emptyQuote = requiredElement<HTMLElement>("#toolbox-empty-quote");
const paymentStatus = requiredElement<HTMLElement>("#toolbox-payment-status");
const resultsSection = requiredElement<HTMLElement>("#toolbox-results");

function effectiveSchema(schema: JsonSchema): JsonSchema {
  if (!schema.anyOf) return schema;
  return schema.anyOf.find((candidate) => candidate.type !== "null") || schema;
}

function titleCase(value: string): string {
  const acronyms: Record<string, string> = {
    asn: "ASN",
    bgp: "BGP",
    cgnat: "CGNAT",
    dns: "DNS",
    dnssec: "DNSSEC",
    http: "HTTP",
    https: "HTTPS",
    id: "ID",
    ip: "IP",
    ms: "ms",
    mx: "MX",
    nat: "NAT",
    rdap: "RDAP",
    sip: "SIP",
    tls: "TLS",
    url: "URL",
    voip: "VoIP",
    whois: "WHOIS",
  };
  return value
    .replace(/_/g, " ")
    .split(/\s+/)
    .map(
      (word) => acronyms[word.toLowerCase()] || word.replace(/^\w/, (char) => char.toUpperCase()),
    )
    .join(" ");
}

function exampleAt(example: unknown, key: string): unknown {
  return example && typeof example === "object" && !Array.isArray(example)
    ? (example as JsonObject)[key]
    : undefined;
}

function createInput(
  name: string,
  schemaValue: JsonSchema,
  required: boolean,
  example: unknown,
  path: string,
): HTMLElement {
  const schema = effectiveSchema(schemaValue);
  const wrapper = document.createElement("div");
  wrapper.className = "toolbox-field";
  const id = `toolbox-field-${path.replace(/[^a-z0-9]+/gi, "-")}`;
  const label = document.createElement("label");
  label.htmlFor = id;
  const strong = document.createElement("strong");
  strong.textContent = titleCase(name);
  label.append(strong);
  if (required) label.append(" · required");
  wrapper.append(label);
  if (schema.description) {
    const description = document.createElement("small");
    description.textContent = schema.description;
    wrapper.append(description);
  }

  const initial = example ?? schema.default;
  let control: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
  if (schema.enum) {
    const select = document.createElement("select");
    if (!required) select.append(new Option("Not set", ""));
    for (const option of schema.enum) select.append(new Option(String(option), String(option)));
    if (initial !== undefined) select.value = String(initial);
    control = select;
  } else if (schema.type === "boolean") {
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(initial);
    control = input;
  } else if (
    schema.type === "array" ||
    (schema.type === "string" && (schema.maxLength || 0) > 2048)
  ) {
    const textarea = document.createElement("textarea");
    textarea.rows = schema.type === "array" ? 3 : 7;
    if (initial !== undefined) {
      textarea.value = schema.type === "array" ? JSON.stringify(initial) : String(initial);
    }
    textarea.placeholder =
      schema.type === "array" ? '["value"] or one value per line' : "Enter text";
    control = textarea;
  } else {
    const input = document.createElement("input");
    input.type = schema.type === "integer" || schema.type === "number" ? "number" : "text";
    if (schema.minimum !== undefined) input.min = String(schema.minimum);
    if (schema.maximum !== undefined) input.max = String(schema.maximum);
    if (schema.minLength !== undefined) input.minLength = schema.minLength;
    if (schema.maxLength !== undefined) input.maxLength = schema.maxLength;
    if (initial !== undefined && initial !== null) input.value = String(initial);
    control = input;
  }
  control.id = id;
  control.dataset.jsonPath = path;
  control.dataset.schemaType = schema.type || "string";
  if (required) control.required = true;
  wrapper.append(control);
  return wrapper;
}

function renderObjectFields(
  schema: JsonSchema,
  example: unknown,
  parent: HTMLElement,
  prefix = "",
): void {
  const properties = schema.properties || {};
  const required = new Set(schema.required || []);
  const entries = Object.entries(properties).sort(
    ([left], [right]) => Number(required.has(right)) - Number(required.has(left)),
  );
  for (const [name, rawProperty] of entries) {
    const property = effectiveSchema(rawProperty);
    const path = prefix ? `${prefix}.${name}` : name;
    const fieldExample = exampleAt(example, name);
    if (property.type === "object" && property.properties) {
      const fieldset = document.createElement("fieldset");
      const legend = document.createElement("legend");
      legend.textContent = titleCase(name);
      fieldset.append(legend);
      renderObjectFields(property, fieldExample, fieldset, path);
      parent.append(fieldset);
    } else {
      parent.append(createInput(name, property, required.has(name), fieldExample, path));
    }
  }
}

function setPath(target: JsonObject, path: string, value: unknown): void {
  const parts = path.split(".");
  let cursor = target;
  for (const part of parts.slice(0, -1)) {
    const next = cursor[part];
    if (!next || typeof next !== "object" || Array.isArray(next)) cursor[part] = {};
    cursor = cursor[part] as JsonObject;
  }
  cursor[parts.at(-1) || path] = value;
}

function controlValue(
  control: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement,
): unknown {
  const type = control.dataset.schemaType;
  if (control instanceof HTMLInputElement && control.type === "checkbox") return control.checked;
  const value = control.value.trim();
  if (!value && !control.required) return undefined;
  if (type === "integer") return Number.parseInt(value, 10);
  if (type === "number") return Number.parseFloat(value);
  if (type === "array") {
    if (!value) return [];
    if (value.startsWith("[")) return JSON.parse(value) as unknown;
    return value
      .split(/[\n,]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return value;
}

function payloadFromFields(): JsonObject {
  const payload: JsonObject = {};
  for (const control of fieldsEl.querySelectorAll<
    HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
  >("[data-json-path]")) {
    const value = controlValue(control);
    if (value !== undefined) setPath(payload, control.dataset.jsonPath || "", value);
  }
  return payload;
}

function syncJsonFromFields(): void {
  if (advancedDirty) return;
  try {
    jsonEl.value = JSON.stringify(payloadFromFields(), null, 2);
  } catch {
    // The validation surface reports malformed array input on submit.
  }
}

function selectTool(operationId: string, payload?: JsonObject): ToolDefinition {
  const tool = toolsById.get(operationId);
  if (!tool || !tool.executable) throw new Error("That diagnostic is not enabled in the toolbox.");
  selectedTool = tool;
  workspace.hidden = false;
  requiredElement<HTMLElement>("#toolbox-title").textContent = tool.title;
  requiredElement<HTMLElement>("#toolbox-path").textContent = `${tool.method} ${tool.path}`;
  requiredElement<HTMLElement>("#toolbox-description").textContent = tool.description;
  fieldsEl.replaceChildren();
  renderObjectFields(tool.input_schema, payload || tool.input_example, fieldsEl);
  for (const parameter of tool.parameters) {
    const field = createInput(
      parameter.name,
      { ...parameter.schema, description: parameter.description || parameter.schema.description },
      parameter.required,
      payload?.[parameter.name] ?? parameter.example,
      parameter.name,
    );
    const control = field.querySelector<HTMLElement>("[data-json-path]");
    if (control) {
      control.dataset.parameter = parameter.name;
      control.dataset.parameterIn = parameter.in;
    }
    fieldsEl.prepend(field);
  }
  advancedDirty = false;
  // Keep body, path, and query examples together in the canonical payload. This
  // also makes untouched required parameters available on the first submit.
  jsonEl.value = JSON.stringify(payloadFromFields(), null, 2);
  validationEl.hidden = true;
  quotePanel.hidden = true;
  emptyQuote.hidden = false;
  paymentStatus.textContent = "";
  workspace.scrollIntoView({ behavior: "smooth", block: "start" });
  return tool;
}

function requestFor(tool: ToolDefinition, input: JsonObject): X402RequestSpec {
  const body = structuredClone(input);
  let path = tool.path;
  const query = new URLSearchParams();
  for (const parameter of tool.parameters) {
    const value = body[parameter.name];
    delete body[parameter.name];
    if (value === undefined || value === null || value === "") {
      if (parameter.required) throw new Error(`${parameter.name} is required.`);
      continue;
    }
    if (parameter.in === "path") {
      path = path.replace(`{${parameter.name}}`, encodeURIComponent(String(value)));
    } else {
      query.set(parameter.name, String(value));
    }
  }
  const apiPath = path.replace(/^\/v1\//, "");
  const url = `/api/${apiPath}${query.size ? `?${query.toString()}` : ""}`;
  const hasBody = tool.method !== "GET" && tool.method !== "HEAD";
  if (!hasBody && Object.keys(body).length) {
    throw new Error(`Unexpected input for ${tool.method}: ${Object.keys(body).join(", ")}.`);
  }
  return {
    url,
    method: tool.method,
    headers: hasBody
      ? { "Content-Type": "application/json", Accept: "application/json, application/gzip" }
      : { Accept: "application/json, application/gzip" },
    body: hasBody ? JSON.stringify(body) : undefined,
  };
}

function validateInput(tool: ToolDefinition, input: JsonObject): void {
  const body = structuredClone(input);
  for (const parameter of tool.parameters) delete body[parameter.name];
  const validate = ajv.compile(tool.input_schema as object);
  if (!validate(body)) {
    const detail = validate.errors
      ?.map((error) => `${error.instancePath || "request"} ${error.message}`)
      .join("; ");
    throw new Error(detail || "The request does not match the enabled OpenAPI schema.");
  }
}

function networkFor(value: string): PaymentNetwork {
  const network = networks.find(
    (candidate) => candidate.caip2 === value || candidate.key === value,
  );
  if (!network || network.family !== "evm")
    throw new Error("That settlement network is not enabled.");
  return network;
}

function quoteOutput(state: QuoteState): JsonObject {
  return {
    quote_handle: state.handle,
    operation_id: state.tool.operation_id,
    expires_at: new Date(state.expiresAt).toISOString(),
    accept: state.quote.accept,
  };
}

async function createQuote(
  operationId: string,
  input: JsonObject,
  networkId: string,
): Promise<JsonObject> {
  if (catalog.status !== "live" || !catalog.execution_enabled)
    throw new Error("Live enabled-operation discovery is unavailable.");
  const tool = selectTool(operationId, input);
  validateInput(tool, input);
  const network = networkFor(networkId);
  paymentStatus.textContent = "Requesting the exact x402 challenge…";
  paymentStatus.className = "payment-status payment-pending";
  const outcome = await quoteX402(
    requestFor(tool, input),
    [network.caip2, network.key].filter((value): value is string => Boolean(value)),
  );
  if (outcome.kind === "response") {
    const result = await consumeResponse(outcome.response, tool);
    return { paid: false, result_handle: result.handle, status: result.status };
  }
  const timeout = Math.max(
    60,
    Math.min(Number(outcome.quote.accept.maxTimeoutSeconds || 300), 3600),
  );
  const state: QuoteState = {
    handle: crypto.randomUUID(),
    tool,
    quote: outcome.quote,
    network,
    expiresAt: Date.now() + timeout * 1000,
    used: false,
  };
  quotes.set(state.handle, state);
  renderQuote(state);
  return quoteOutput(state);
}

function renderQuote(state: QuoteState): void {
  const accept = state.quote.accept;
  emptyQuote.hidden = true;
  quotePanel.hidden = false;
  requiredElement<HTMLElement>("#toolbox-amount").textContent = humanTokenAmount(
    accept.amount,
    state.network.token_decimals,
  );
  requiredElement<HTMLElement>("#toolbox-asset").textContent = state.network.asset;
  requiredElement<HTMLElement>("#toolbox-quote-network").textContent = state.network.display_name;
  requiredElement<HTMLElement>("#toolbox-quote-expiry").textContent = new Date(
    state.expiresAt,
  ).toLocaleTimeString();
  requiredElement<HTMLElement>("#toolbox-quote-handle").textContent = state.handle;
  requiredElement<HTMLButtonElement>("#toolbox-pay-wallet").dataset.quoteHandle = state.handle;
  requiredElement<HTMLButtonElement>("#toolbox-pay-signed").dataset.quoteHandle = state.handle;
  paymentStatus.textContent = "Exact quote received. Choose a signing path.";
  paymentStatus.className = "payment-status payment-ok";
}

function sanitize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sanitize);
  if (!value || typeof value !== "object") return value;
  const clean: JsonObject = {};
  for (const [key, item] of Object.entries(value as JsonObject)) {
    if (/token|signature|authorization|payment[-_]?required/i.test(key)) continue;
    clean[key] = sanitize(item);
  }
  return clean;
}

function filenameFrom(response: Response): string {
  const disposition = response.headers.get("content-disposition") || "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  return decodeURIComponent(encoded || plain || `hyrule-result-${Date.now()}.bin`);
}

async function consumeResponse(response: Response, tool: ToolDefinition): Promise<ResultState> {
  const handle = crypto.randomUUID();
  const contentType = response.headers.get("content-type") || "application/octet-stream";
  const receipt =
    response.headers.get("payment-response") ||
    response.headers.get("x-payment-response") ||
    undefined;
  let state: ResultState;
  if (!contentType.includes("json") || contentType.includes("gzip")) {
    const blob = await response.blob();
    state = {
      handle,
      tool,
      status: "completed",
      blob,
      blobUrl: URL.createObjectURL(blob),
      filename: filenameFrom(response),
      mediaType: contentType,
      receipt,
      value: { filename: filenameFrom(response), media_type: contentType, size_bytes: blob.size },
    };
  } else {
    const value = (await response.json()) as unknown;
    const object = value && typeof value === "object" ? (value as JsonObject) : {};
    state = {
      handle,
      tool,
      status: String(object.status || "completed"),
      value,
      raw: JSON.stringify(sanitize(value), null, 2),
      jobToken: typeof object.job_access_token === "string" ? object.job_access_token : undefined,
      statusUrl: typeof object.status_url === "string" ? object.status_url : undefined,
      downloadUrl: typeof object.download_url === "string" ? object.download_url : undefined,
      receipt,
    };
  }
  results.set(handle, state);
  saveJobState(state);
  renderResult(state);
  addHistory(state);
  if (state.statusUrl && state.jobToken && !isTerminal(state.status)) startPolling(state);
  return state;
}

async function payQuote(handle: string, mode: string, external?: string): Promise<JsonObject> {
  const state = quotes.get(handle);
  if (!state) throw new Error("Unknown or expired quote handle.");
  if (state.used) throw new Error("This quote has already settled successfully.");
  if (Date.now() >= state.expiresAt) throw new Error("This x402 quote has expired.");
  paymentStatus.textContent =
    mode === "browser_wallet"
      ? "Waiting for the wallet signature…"
      : "Validating the agent-signed payload…";
  paymentStatus.className = "payment-status payment-pending";
  let signature: string;
  if (mode === "browser_wallet") {
    signature = await signX402Quote(state.quote, state.network);
  } else if (mode === "signed_x402") {
    if (!external) throw new Error("payment_signature is required for signed_x402 mode.");
    validateSignedPayment(state.quote, external);
    signature = external.trim();
  } else {
    throw new Error("mode must be browser_wallet or signed_x402.");
  }
  paymentStatus.textContent = "Settling and running the diagnostic…";
  const response = await executeX402(state.quote, signature);
  state.used = true;
  const result = await consumeResponse(response, state.tool);
  paymentStatus.textContent = "Payment settled. Result received.";
  paymentStatus.className = "payment-status payment-ok";
  return { result_handle: result.handle, status: result.status, receipt: result.receipt || null };
}

function isTerminal(status: string): boolean {
  return ["completed", "complete", "failed", "error", "expired", "cancelled"].includes(
    status.toLowerCase(),
  );
}

function proxiedJobUrl(path: string, token?: string): string {
  const candidate = /^https?:\/\//i.test(path) || path.startsWith("/") ? path : `/${path}`;
  const source = new URL(candidate, location.origin);
  const params = new URLSearchParams(source.search);
  if (token) params.set("token", token);
  const apiPath = source.pathname.replace(/^\/(?:v1|api)\//, "");
  return `/api/${apiPath}${params.size ? `?${params}` : ""}`;
}

async function pollJob(state: ResultState): Promise<void> {
  let delay = 2000;
  while (state.statusUrl && state.jobToken && !isTerminal(state.status)) {
    // Browser agents can keep a diagnostic moving in a background tab. Use a
    // slower cadence there, but never pause a paid job just because it is hidden.
    await new Promise((resolve) =>
      setTimeout(resolve, document.hidden ? Math.max(delay, 5000) : delay),
    );
    const response = await fetch(proxiedJobUrl(state.statusUrl, state.jobToken), {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`Status check failed (${response.status}).`);
    const value = (await response.json()) as JsonObject;
    state.value = value;
    state.raw = JSON.stringify(sanitize(value), null, 2);
    state.status = String(value.status || state.status);
    if (typeof value.download_url === "string") state.downloadUrl = value.download_url;
    state.pollError = undefined;
    renderResult(state, false);
    saveJobState(state);
    delay = Math.min(Math.round(delay * 1.5), 15000);
  }
}

function startPolling(state: ResultState): void {
  if (state.polling || !state.statusUrl || !state.jobToken || isTerminal(state.status)) return;
  state.polling = pollJob(state)
    .catch((error: unknown) => {
      state.pollError = error instanceof Error ? error.message : String(error);
    })
    .finally(() => {
      state.polling = undefined;
    });
}

function saveJobState(state: ResultState): void {
  if (!state.jobToken || !state.statusUrl) return;
  try {
    sessionStorage.setItem(
      `hyr_toolbox_job:${state.handle}`,
      JSON.stringify({
        handle: state.handle,
        operationId: state.tool.operation_id,
        status: state.status,
        jobToken: state.jobToken,
        statusUrl: state.statusUrl,
        downloadUrl: state.downloadUrl,
      }),
    );
  } catch {
    // Session storage is a convenience; in-memory polling still works.
  }
}

function restoreJobs(): void {
  try {
    for (let index = 0; index < sessionStorage.length; index += 1) {
      const key = sessionStorage.key(index);
      if (!key?.startsWith("hyr_toolbox_job:")) continue;
      const saved = JSON.parse(sessionStorage.getItem(key) || "null") as {
        handle?: string;
        operationId?: string;
        status?: string;
        jobToken?: string;
        statusUrl?: string;
        downloadUrl?: string;
      } | null;
      const tool = saved?.operationId ? toolsById.get(saved.operationId) : undefined;
      if (!saved?.handle || !saved.jobToken || !saved.statusUrl || !tool) continue;
      const state: ResultState = {
        handle: saved.handle,
        tool,
        status: saved.status || "queued",
        jobToken: saved.jobToken,
        statusUrl: saved.statusUrl,
        downloadUrl: saved.downloadUrl,
        value: { status: saved.status || "queued", summary: "Resumed diagnostic job" },
      };
      results.set(state.handle, state);
      addHistory(state);
      if (!isTerminal(state.status)) startPolling(state);
    }
  } catch {
    // Ignore malformed or blocked session storage.
  }
}

function renderResult(state: ResultState, scroll = true): void {
  resultsSection.hidden = false;
  requiredElement<HTMLElement>("#toolbox-result-title").textContent = state.tool.title;
  const clean = sanitize(state.value);
  const object =
    clean && typeof clean === "object" && !Array.isArray(clean) ? (clean as JsonObject) : {};
  requiredElement<HTMLElement>("#toolbox-result-summary").textContent = String(
    object.summary || `Status: ${state.status}`,
  );
  requiredElement<HTMLElement>("#toolbox-result-raw").textContent =
    state.raw || JSON.stringify(clean, null, 2);
  const findings = requiredElement<HTMLElement>("#toolbox-findings");
  findings.replaceChildren();
  if (Array.isArray(object.findings)) {
    for (const rawFinding of object.findings) {
      if (!rawFinding || typeof rawFinding !== "object") continue;
      const finding = rawFinding as JsonObject;
      const article = document.createElement("article");
      article.className = `toolbox-finding finding-${String(finding.severity || "info")}`;
      const heading = document.createElement("strong");
      heading.textContent = String(finding.code || finding.severity || "Finding");
      const message = document.createElement("p");
      message.textContent = String(finding.message || "");
      article.append(heading, message);
      findings.append(article);
    }
  }
  const downloads = requiredElement<HTMLElement>("#toolbox-downloads");
  downloads.replaceChildren();
  if (state.blobUrl) {
    const link = document.createElement("a");
    link.className = "btn btn-primary";
    link.href = state.blobUrl;
    link.download = state.filename || "hyrule-result.bin";
    link.textContent = `Download ${state.filename || "result"}`;
    downloads.append(link);
  } else if (state.downloadUrl && state.jobToken && isTerminal(state.status)) {
    const button = document.createElement("button");
    button.className = "btn btn-primary";
    button.type = "button";
    button.textContent = "Download completed artifact";
    button.addEventListener("click", () => void downloadJob(state));
    downloads.append(button);
  }
  if (scroll) resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function downloadJob(state: ResultState): Promise<void> {
  if (!state.downloadUrl) return;
  const response = await fetch(proxiedJobUrl(state.downloadUrl, state.jobToken));
  if (!response.ok) throw new Error(`Artifact download failed (${response.status}).`);
  const blob = await response.blob();
  state.blob = blob;
  state.blobUrl = URL.createObjectURL(blob);
  state.filename = filenameFrom(response);
  state.mediaType = response.headers.get("content-type") || blob.type;
  renderResult(state);
}

function addHistory(state: ResultState): void {
  const list = requiredElement<HTMLOListElement>("#toolbox-history");
  if (
    list.children.length === 1 &&
    list.firstElementChild?.textContent?.startsWith("No diagnostics")
  )
    list.replaceChildren();
  const item = document.createElement("li");
  const time = document.createElement("time");
  time.dateTime = new Date().toISOString();
  time.textContent = new Date().toLocaleTimeString();
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = `${state.tool.title} · ${state.status}`;
  button.addEventListener("click", () => renderResult(state));
  item.append(time, button);
  list.prepend(item);
}

async function getResult(handle: string, cursor = 0, waitSeconds = 0): Promise<JsonObject> {
  const state = results.get(handle);
  if (!state) throw new Error("Unknown result handle.");
  if (!isTerminal(state.status) && waitSeconds > 0) {
    const deadline = Date.now() + Math.min(waitSeconds, 30) * 1000;
    startPolling(state);
    while (!isTerminal(state.status) && Date.now() < deadline) {
      await new Promise((resolve) =>
        setTimeout(resolve, Math.max(0, Math.min(500, deadline - Date.now()))),
      );
    }
  }
  if (state.downloadUrl && state.jobToken && isTerminal(state.status) && !state.blobUrl)
    await downloadJob(state);
  const start = Math.max(0, cursor);
  if (state.blob) {
    const end = Math.min(start + 768, state.blob.size);
    const bytes = new Uint8Array(await state.blob.slice(start, end).arrayBuffer());
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return {
      status: state.status,
      result_handle: state.handle,
      output: btoa(binary),
      output_encoding: "base64",
      next_cursor: end < state.blob.size ? end : null,
      poll_error: state.pollError || null,
      download: { filename: state.filename, media_type: state.mediaType },
    };
  }
  const raw = state.raw || JSON.stringify(sanitize(state.value));
  const chunk = raw.slice(start, start + 1000);
  return {
    status: state.status,
    result_handle: state.handle,
    output: chunk,
    output_encoding: "utf-8",
    next_cursor: start + chunk.length < raw.length ? start + chunk.length : null,
    poll_error: state.pollError || null,
    download: state.blobUrl ? { filename: state.filename, media_type: state.mediaType } : null,
  };
}

async function registerWebMcp(): Promise<void> {
  const modelContext = (document as Document & { modelContext?: ModelContext }).modelContext;
  if (!modelContext || catalog.status !== "live" || !catalog.execution_enabled) return;
  const controller = new AbortController();
  const operationIds = executableTools.map((tool) => tool.operation_id);
  const networkIds = networks
    .filter((network) => network.family === "evm")
    .map((network) => network.caip2 || network.key);
  await modelContext.registerTool(
    {
      name: "search_hyrule_diagnostics",
      description:
        "Search enabled Hyrule network diagnostics and show matching tools in the visible toolbox.",
      inputSchema: {
        type: "object",
        properties: { query: { type: "string" } },
        required: ["query"],
      },
      annotations: { readOnlyHint: true },
      execute(input) {
        const query = String(input.query || "").toLowerCase();
        filterTools(query);
        const matches = executableTools
          .filter((tool) => searchMatches(tool.search_terms.join(" "), query))
          .slice(0, 10)
          .map((tool) => ({
            operation_id: tool.operation_id,
            title: tool.title,
            price: tool.price_display,
          }));
        return matches;
      },
    },
    { signal: controller.signal },
  );
  await modelContext.registerTool(
    {
      name: "quote_hyrule_diagnostic",
      description:
        "Validate an enabled diagnostic request and return its exact unpaid x402 quote. This does not spend funds.",
      inputSchema: {
        type: "object",
        properties: {
          operation_id: { type: "string", enum: operationIds },
          input: { type: "object", additionalProperties: true },
          network: { type: "string", enum: networkIds },
        },
        required: ["operation_id", "input", "network"],
      },
      annotations: { readOnlyHint: true },
      async execute(input) {
        return createQuote(
          String(input.operation_id),
          (input.input || {}) as JsonObject,
          String(input.network),
        );
      },
    },
    { signal: controller.signal },
  );
  await modelContext.registerTool(
    {
      name: "pay_hyrule_diagnostic",
      description:
        "Pay an exact Hyrule x402 quote and run it using the browser wallet or an agent-signed payment payload.",
      inputSchema: {
        type: "object",
        properties: {
          quote_handle: { type: "string" },
          mode: { type: "string", enum: ["browser_wallet", "signed_x402"] },
          payment_signature: { type: "string" },
        },
        required: ["quote_handle", "mode"],
      },
      annotations: { readOnlyHint: false },
      async execute(input) {
        return payQuote(
          String(input.quote_handle),
          String(input.mode),
          input.payment_signature ? String(input.payment_signature) : undefined,
        );
      },
    },
    { signal: controller.signal },
  );
  await modelContext.registerTool(
    {
      name: "get_hyrule_diagnostic_result",
      description:
        "Read or wait for a paid diagnostic result. Untrusted JSON and base64 binary output are returned in cursor-based pages.",
      inputSchema: {
        type: "object",
        properties: {
          result_handle: { type: "string" },
          cursor: { type: "integer", minimum: 0, default: 0 },
          wait_seconds: { type: "integer", minimum: 0, maximum: 30, default: 0 },
        },
        required: ["result_handle"],
      },
      annotations: { readOnlyHint: true, untrustedContentHint: true },
      async execute(input) {
        return getResult(
          String(input.result_handle),
          Number(input.cursor || 0),
          Number(input.wait_seconds || 0),
        );
      },
    },
    { signal: controller.signal },
  );
}

function searchMatches(haystack: string, query: string): boolean {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const normalized = haystack.toLowerCase();
  return terms.every((term) => normalized.includes(term));
}

function filterTools(query: string, category = selectedCategory): void {
  selectedCategory = category;
  for (const card of grid.querySelectorAll<HTMLElement>("[data-tool-card]")) {
    const matchesText = searchMatches(card.dataset.search || "", query);
    const matchesCategory = category === "all" || card.dataset.category === category;
    card.hidden = !(matchesText && matchesCategory);
  }
  for (const button of categoriesEl.querySelectorAll<HTMLButtonElement>("button")) {
    button.setAttribute("aria-pressed", String(button.dataset.category === category));
  }
}

function renderCategories(): void {
  const categories = [...new Set(catalog.tools.map((tool) => tool.category))];
  for (const category of ["all", ...categories]) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "toolbox-category";
    button.dataset.category = category;
    button.setAttribute("aria-pressed", String(category === selectedCategory));
    button.textContent = category === "all" ? "All tools" : category;
    button.addEventListener("click", () => filterTools(searchInput.value, category));
    categoriesEl.append(button);
  }
}

grid.addEventListener("click", (event) => {
  const button = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-select-tool]");
  if (button?.dataset.selectTool) selectTool(button.dataset.selectTool);
});
requiredElement<HTMLButtonElement>("#toolbox-search-button").addEventListener("click", () =>
  filterTools(searchInput.value),
);
searchInput.addEventListener("input", () => filterTools(searchInput.value));
fieldsEl.addEventListener("input", syncJsonFromFields);
jsonEl.addEventListener("input", () => {
  advancedDirty = true;
});
form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!selectedTool) return;
  void (async () => {
    try {
      validationEl.hidden = true;
      const input = JSON.parse(jsonEl.value || "{}") as JsonObject;
      await createQuote(selectedTool.operation_id, input, networkEl.value);
    } catch (error) {
      validationEl.textContent = error instanceof Error ? error.message : String(error);
      validationEl.hidden = false;
      paymentStatus.textContent = "";
    }
  })();
});
requiredElement<HTMLButtonElement>("#toolbox-pay-wallet").addEventListener("click", (event) => {
  const handle = (event.currentTarget as HTMLButtonElement).dataset.quoteHandle;
  if (handle) void payQuote(handle, "browser_wallet").catch(showPaymentError);
});
requiredElement<HTMLButtonElement>("#toolbox-pay-signed").addEventListener("click", (event) => {
  const handle = (event.currentTarget as HTMLButtonElement).dataset.quoteHandle;
  const signature = requiredElement<HTMLTextAreaElement>("#toolbox-payment-signature").value;
  if (handle) void payQuote(handle, "signed_x402", signature).catch(showPaymentError);
});

function showPaymentError(error: unknown): void {
  paymentStatus.textContent = error instanceof Error ? error.message : String(error);
  paymentStatus.className = "payment-status payment-error";
}

renderCategories();
void registerWebMcp().catch((error: unknown) => {
  console.warn("WebMCP tool registration failed:", error);
});
restoreJobs();
const initialTool = new URLSearchParams(location.search).get("tool");
if (
  initialTool &&
  toolsById.get(initialTool)?.executable &&
  catalog.status === "live" &&
  catalog.execution_enabled
)
  selectTool(initialTool);
