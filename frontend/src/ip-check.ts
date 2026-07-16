import "./styles/ip-check.css";

type ProbeStatus = "collected" | "blocked" | "unsupported" | "failed";

interface IPCheckConfig {
  quality_tool_id?: string | null;
  quality_price?: string | null;
}

interface ProbeManifest {
  agent_identity_challenge: string;
  execution_requirement: string;
  probes: Array<Record<string, unknown>>;
  report_url: string;
  version: string;
}

interface SessionResponse {
  session_id: string;
  token: string;
  expires_at: string;
  retention_seconds: number;
  ipv4_probe_url: string;
  ipv6_probe_url: string;
  dns_probe_hostname: string;
  stun_urls: string[];
  probe_manifest: ProbeManifest;
}

interface BrowserFingerprint {
  fingerprint_id: string;
  scope: "session";
  expires_at: string;
  header_traits: Record<string, string>;
  client_traits: Record<string, unknown>;
  consistency: Record<string, boolean | null>;
  high_entropy_traits_used: boolean;
  provenance: Record<string, string>;
}

interface SessionReport {
  session_id: string;
  expires_at: string;
  https_ipv4_addresses: string[];
  https_ipv6_addresses: string[];
  dns_resolver_addresses: string[];
  webrtc_public_addresses: string[];
  webrtc_status: ProbeStatus | null;
  stun_public_addresses: string[];
  stun_status: ProbeStatus | null;
  ipv4_status: string;
  ipv6_status: string;
  webrtc_leak_status: string;
  nat_egress_status: string;
  dns_leak_status: string;
  dns_expectation_configured: boolean;
  browser_fingerprint: BrowserFingerprint | null;
  agent_fingerprint: Record<string, unknown> | null;
  retention_seconds: number;
}

interface WebRTCResult {
  status: ProbeStatus;
  publicAddresses: string[];
}

function parseIPv4(value: string): number[] | null {
  const parts = value.split(".");
  if (parts.length !== 4) return null;
  const numbers = parts.map((part) => Number(part));
  if (
    numbers.some(
      (part, index) =>
        !Number.isInteger(part) || part < 0 || part > 255 || `${part}` !== parts[index],
    )
  ) {
    return null;
  }
  return numbers;
}

function parseIPv6(value: string): number[] | null {
  const normalized = value.toLowerCase().replace(/^\[|\]$/g, "");
  if (!normalized.includes(":") || normalized.includes("%")) return null;
  const halves = normalized.split("::");
  if (halves.length > 2) return null;
  const left = halves[0] ? halves[0].split(":") : [];
  const right = halves.length === 2 && halves[1] ? halves[1].split(":") : [];
  const expandEmbeddedIPv4 = (parts: string[]): string[] | null => {
    if (!parts.at(-1)?.includes(".")) return parts;
    const ipv4 = parseIPv4(parts.at(-1) ?? "");
    if (!ipv4) return null;
    return [
      ...parts.slice(0, -1),
      ((ipv4[0] << 8) | ipv4[1]).toString(16),
      ((ipv4[2] << 8) | ipv4[3]).toString(16),
    ];
  };
  const expandedLeft = expandEmbeddedIPv4(left);
  const expandedRight = expandEmbeddedIPv4(right);
  if (!expandedLeft || !expandedRight) return null;
  const missing = 8 - expandedLeft.length - expandedRight.length;
  if ((halves.length === 1 && missing !== 0) || (halves.length === 2 && missing < 1)) return null;
  const groups = [
    ...expandedLeft,
    ...Array.from({ length: Math.max(0, missing) }, () => "0"),
    ...expandedRight,
  ];
  if (groups.length !== 8 || groups.some((group) => !/^[a-f0-9]{1,4}$/.test(group))) {
    return null;
  }
  return groups.map((group) => Number.parseInt(group, 16));
}

export function isPublicIp(value: string): boolean {
  const ipv4 = parseIPv4(value);
  if (ipv4) {
    const [a, b, c] = ipv4;
    return !(
      a === 0 ||
      a === 10 ||
      a === 127 ||
      a >= 224 ||
      (a === 100 && b >= 64 && b <= 127) ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 0) ||
      (a === 192 && b === 168) ||
      (a === 192 && b === 88 && c === 99) ||
      (a === 198 && (b === 18 || b === 19)) ||
      (a === 198 && b === 51 && c === 100) ||
      (a === 203 && b === 0 && c === 113)
    );
  }
  const ipv6 = parseIPv6(value);
  if (!ipv6) return false;
  const [first, second] = ipv6;
  // Conservative global-unicast allowlist. False negatives are safer than
  // submitting a private, link-local, documentation, or mDNS candidate.
  return first >= 0x2000 && first <= 0x3fff && !(first === 0x2001 && second === 0x0db8);
}

export function extractPublicIceAddress(candidate: string): string | null {
  const parts = candidate.trim().split(/\s+/);
  const address = parts[4] ?? "";
  return isPublicIp(address) ? address : null;
}

export function parseExpectedResolvers(value: string): string[] {
  return [
    ...new Set(
      value
        .split(/[\s,]+/)
        .map((entry) => entry.trim())
        .filter(Boolean),
    ),
  ];
}

function requiredElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Missing IP-check element: ${selector}`);
  return element;
}

async function apiJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { Accept: "application/json", ...init.headers },
    cache: "no-store",
    credentials: url.startsWith("/api/") ? "same-origin" : "omit",
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status}).`;
    try {
      const body = (await response.json()) as { detail?: unknown; error?: unknown };
      detail = String(body.detail ?? body.error ?? detail);
    } catch {
      // Keep the bounded status message when the response is not JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function trustedProbeUrl(value: string, family: 4 | 6): string {
  const url = new URL(value);
  const expected = family === 4 ? "v4.check.hyrule.host" : "v6.check.hyrule.host";
  if (url.protocol !== "https:" || url.hostname !== expected) {
    throw new Error(`The ${family === 4 ? "IPv4" : "IPv6"} probe target is not trusted.`);
  }
  return url.toString();
}

async function runHttpProbe(session: SessionResponse, family: 4 | 6): Promise<string | null> {
  const url = trustedProbeUrl(
    family === 4 ? session.ipv4_probe_url : session.ipv6_probe_url,
    family,
  );
  const result = await apiJson<{ address: string }>(url, {
    method: "POST",
    mode: "cors",
    headers: { Authorization: `Bearer ${session.token}` },
  });
  return isPublicIp(result.address) ? result.address : null;
}

async function triggerDns(hostname: string): Promise<void> {
  if (!/^[a-f0-9]{32}\.dns\.check\.hyrule\.host$/i.test(hostname)) {
    throw new Error("The DNS probe target is not trusted.");
  }
  await new Promise<void>((resolve) => {
    const image = new Image();
    const finish = (): void => resolve();
    image.onload = finish;
    image.onerror = finish;
    image.referrerPolicy = "no-referrer";
    image.src = `https://${hostname}/probe-${crypto.randomUUID()}.gif`;
    window.setTimeout(finish, 1500);
  });
}

export async function collectWebRTC(stunUrls: string[], timeoutMs = 4500): Promise<WebRTCResult> {
  if (typeof RTCPeerConnection === "undefined") {
    return { status: "unsupported", publicAddresses: [] };
  }
  const safeUrls = stunUrls.filter((url) => /^stun:stun\.hyrule\.host(?::\d+)?$/i.test(url));
  if (!safeUrls.length) return { status: "unsupported", publicAddresses: [] };
  const addresses = new Set<string>();
  let sawCandidate = false;
  let connection: RTCPeerConnection | null = null;
  try {
    connection = new RTCPeerConnection({ iceServers: [{ urls: safeUrls }] });
    connection.createDataChannel("hyrule-observation");
    const complete = new Promise<void>((resolve) => {
      const finish = (): void => resolve();
      connection!.onicecandidate = (event): void => {
        if (!event.candidate) {
          finish();
          return;
        }
        sawCandidate = true;
        const direct = (event.candidate as RTCIceCandidate & { address?: string }).address;
        const address =
          direct && isPublicIp(direct)
            ? direct
            : extractPublicIceAddress(event.candidate.candidate);
        if (address) addresses.add(address);
      };
      window.setTimeout(finish, timeoutMs);
    });
    const offer = await connection.createOffer();
    await connection.setLocalDescription(offer);
    await complete;
    return {
      status: sawCandidate ? "collected" : "blocked",
      publicAddresses: [...addresses],
    };
  } catch {
    return { status: "failed", publicAddresses: [] };
  } finally {
    connection?.close();
  }
}

async function sha256(value: string | ArrayBuffer): Promise<string> {
  const input = typeof value === "string" ? new TextEncoder().encode(value) : value;
  const digest = await crypto.subtle.digest("SHA-256", input);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function canvasHash(): Promise<string | undefined> {
  const canvas = document.createElement("canvas");
  canvas.width = 300;
  canvas.height = 80;
  const context = canvas.getContext("2d");
  if (!context) return undefined;
  context.fillStyle = "#171717";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.font = "18px sans-serif";
  context.fillStyle = "#f1f1f1";
  context.fillText("hyrule.host · agent-first", 12, 36);
  context.strokeStyle = "#8f8f8f";
  context.beginPath();
  context.arc(265, 38, 22, 0, Math.PI * 2);
  context.stroke();
  return sha256(canvas.toDataURL("image/png"));
}

async function audioHash(): Promise<string | undefined> {
  if (typeof OfflineAudioContext === "undefined") return undefined;
  try {
    const context = new OfflineAudioContext(1, 4096, 44100);
    const oscillator = context.createOscillator();
    const compressor = context.createDynamicsCompressor();
    oscillator.type = "triangle";
    oscillator.frequency.value = 10000;
    oscillator.connect(compressor);
    compressor.connect(context.destination);
    oscillator.start(0);
    const buffer = await context.startRendering();
    return sha256(buffer.getChannelData(0).slice(0, 2048).buffer);
  } catch {
    return undefined;
  }
}

function webglTraits(): { webgl_vendor?: string; webgl_renderer?: string } {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("webgl");
  if (!context) return {};
  const extension = context.getExtension("WEBGL_debug_renderer_info");
  if (!extension) return {};
  return {
    webgl_vendor: String(context.getParameter(extension.UNMASKED_VENDOR_WEBGL)).slice(0, 256),
    webgl_renderer: String(context.getParameter(extension.UNMASKED_RENDERER_WEBGL)).slice(0, 512),
  };
}

async function browserTraits(highEntropyConsent: boolean): Promise<Record<string, unknown>> {
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory;
  const traits: Record<string, unknown> = {
    user_agent: navigator.userAgent,
    languages: [...navigator.languages],
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    platform: navigator.platform,
    vendor: navigator.vendor,
    screen_width: screen.width,
    screen_height: screen.height,
    color_depth: screen.colorDepth,
    hardware_concurrency: navigator.hardwareConcurrency,
    device_memory_gib: memory,
    max_touch_points: navigator.maxTouchPoints,
    cookies_enabled: navigator.cookieEnabled,
    do_not_track: navigator.doNotTrack,
    high_entropy_consent: highEntropyConsent,
  };
  if (highEntropyConsent) {
    Object.assign(traits, webglTraits());
    const [canvas, audio] = await Promise.all([canvasHash(), audioHash()]);
    if (canvas) traits.canvas_sha256 = canvas;
    if (audio) traits.audio_sha256 = audio;
  }
  return traits;
}

function text(selector: string, value: string): void {
  requiredElement<HTMLElement>(selector).textContent = value;
}

function renderDefinitionList(element: HTMLElement, rows: Array<[string, string]>): void {
  element.replaceChildren();
  for (const [label, value] of rows) {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = label;
    description.textContent = value;
    wrapper.append(term, description);
    element.append(wrapper);
  }
}

function consistencySummary(report: SessionReport): [string, string] {
  const browserChecks = Object.values(report.browser_fingerprint?.consistency ?? {}).filter(
    (value): value is boolean => typeof value === "boolean",
  );
  if (
    report.webrtc_leak_status === "possible_leak" ||
    report.dns_leak_status === "possible_leak" ||
    browserChecks.includes(false)
  ) {
    return ["Review", "One or more observed and declared signals disagree"];
  }
  if (
    report.webrtc_leak_status === "no_leak" &&
    ["no_leak", "not_assessed"].includes(report.dns_leak_status) &&
    !browserChecks.includes(false)
  ) {
    return ["Consistent", "No mismatch was found in the collected evidence"];
  }
  return ["Inconclusive", "A missing or blocked probe is not evidence of a leak"];
}

function renderReport(report: SessionReport): void {
  text("#ip-result-v4", report.https_ipv4_addresses.join(", ") || "Not observed");
  text("#ip-result-v4-status", report.ipv4_status);
  text("#ip-result-v6", report.https_ipv6_addresses.join(", ") || "Not observed");
  text("#ip-result-v6-status", report.ipv6_status);
  text("#ip-result-dns", report.dns_resolver_addresses.join(", ") || "Not observed");
  text(
    "#ip-result-dns-status",
    report.dns_expectation_configured
      ? report.dns_leak_status
      : "observed · no expectation configured",
  );
  text("#ip-result-webrtc", report.webrtc_public_addresses.join(", ") || "Not observed");
  text(
    "#ip-result-webrtc-status",
    `${report.webrtc_status ?? "missing"} · ${report.webrtc_leak_status}`,
  );
  text("#ip-result-fingerprint", report.browser_fingerprint?.fingerprint_id ?? "Not collected");
  text(
    "#ip-result-fingerprint-status",
    report.browser_fingerprint?.high_entropy_traits_used
      ? "Session scoped · high entropy consented"
      : "Session scoped · standard traits only",
  );
  const [summary, detail] = consistencySummary(report);
  text("#ip-result-consistency", summary);
  text("#ip-result-consistency-status", detail);
  text("#ip-check-expiry", `Evidence expires ${new Date(report.expires_at).toLocaleTimeString()}.`);
  text("#ip-check-report-json", JSON.stringify(report, null, 2));

  renderDefinitionList(requiredElement("#ip-check-provenance"), [
    ["HTTPS egress", "server_observed"],
    ["DNS resolver", "server_observed"],
    ["WebRTC candidates", "client_declared · public only"],
    ["Browser traits", "client_declared · session scoped"],
  ]);
  renderDefinitionList(requiredElement("#ip-check-runtime"), [
    ["Language", navigator.languages.join(", ") || "Unavailable"],
    ["Timezone", Intl.DateTimeFormat().resolvedOptions().timeZone || "Unavailable"],
    ["Platform", navigator.platform || "Unavailable"],
    ["User-Agent", navigator.userAgent],
  ]);
  requiredElement<HTMLElement>("#ip-check-results").hidden = false;
}

function setProbeState(name: string, state: string): void {
  const item = document.querySelector<HTMLElement>(`[data-probe-state="${name}"]`);
  if (!item) return;
  item.dataset.state = state;
  const value = item.querySelector("em");
  if (value) value.textContent = state;
}

function resetProbeStates(): void {
  for (const item of document.querySelectorAll<HTMLElement>("[data-probe-state]")) {
    delete item.dataset.state;
    const value = item.querySelector("em");
    if (value) value.textContent = "waiting";
  }
}

function initIpCheck(): void {
  const form = document.querySelector<HTMLFormElement>("#ip-check-form");
  if (!form) return;
  const configElement = requiredElement<HTMLScriptElement>("#ip-check-config");
  const config = JSON.parse(configElement.textContent || "{}") as IPCheckConfig;
  const runButton = requiredElement<HTMLButtonElement>("#ip-check-run");
  const errorElement = requiredElement<HTMLElement>("#ip-check-error");
  const qualityButton = document.querySelector<HTMLButtonElement>("#ip-check-quality");
  let latestReport: SessionReport | null = null;

  qualityButton?.addEventListener("click", () => {
    const operationId = config.quality_tool_id;
    const address = latestReport?.https_ipv4_addresses[0] ?? latestReport?.https_ipv6_addresses[0];
    if (!operationId || !address) return;
    const expectedCountry = requiredElement<HTMLInputElement>("#ip-check-country")
      .value.trim()
      .toUpperCase();
    const clientContext = {
      user_agent: navigator.userAgent,
      accept_language: navigator.languages.join(","),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    };
    sessionStorage.setItem(
      "hyrule_ip_quality_prefill",
      JSON.stringify({
        operation_id: operationId,
        input: {
          address,
          history_days: 90,
          ...(expectedCountry ? { expected_country_code: expectedCountry } : {}),
          client_context: clientContext,
        },
      }),
    );
    location.assign(`/toolbox?tool=${encodeURIComponent(operationId)}`);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void (async () => {
      errorElement.hidden = true;
      runButton.disabled = true;
      resetProbeStates();
      if (qualityButton) qualityButton.disabled = true;
      try {
        const expectedResolvers = parseExpectedResolvers(
          requiredElement<HTMLTextAreaElement>("#ip-check-dns-expected").value,
        );
        const country = requiredElement<HTMLInputElement>("#ip-check-country").value.trim();
        if (country && !/^[a-z]{2}$/i.test(country)) {
          throw new Error("Expected country must be a two-letter code.");
        }
        setProbeState("session", "running");
        const session = await apiJson<SessionResponse>("/api/ip-check/sessions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expected_dns_resolvers: expectedResolvers }),
        });
        setProbeState("session", "ready");
        text(
          "#ip-check-session-note",
          `Session ${session.session_id} · ${session.retention_seconds}s maximum retention.`,
        );
        const auth = { Authorization: `Bearer ${session.token}` };

        setProbeState("ipv4", "running");
        setProbeState("ipv6", "running");
        const [ipv4, ipv6] = await Promise.allSettled([
          runHttpProbe(session, 4),
          runHttpProbe(session, 6),
        ]);
        setProbeState(
          "ipv4",
          ipv4.status === "fulfilled" && ipv4.value ? "observed" : "unavailable",
        );
        setProbeState(
          "ipv6",
          ipv6.status === "fulfilled" && ipv6.value ? "observed" : "unavailable",
        );

        setProbeState("dns", "querying");
        await triggerDns(session.dns_probe_hostname);
        setProbeState("dns", "query sent");

        setProbeState("webrtc", "running");
        const webRtc = await collectWebRTC(session.stun_urls);
        await apiJson<SessionReport>(
          `/api/ip-check/sessions/${encodeURIComponent(session.session_id)}/observe/browser`,
          {
            method: "POST",
            headers: { ...auth, "Content-Type": "application/json" },
            body: JSON.stringify({
              status: webRtc.status,
              public_addresses: webRtc.publicAddresses,
            }),
          },
        );
        setProbeState("webrtc", webRtc.status);

        setProbeState("fingerprint", "running");
        const highEntropy = requiredElement<HTMLInputElement>("#ip-check-high-entropy").checked;
        await apiJson<BrowserFingerprint>(
          `/api/ip-check/sessions/${encodeURIComponent(session.session_id)}/fingerprints/browser`,
          {
            method: "POST",
            headers: { ...auth, "Content-Type": "application/json" },
            body: JSON.stringify(await browserTraits(highEntropy)),
          },
        );
        setProbeState("fingerprint", highEntropy ? "consented" : "standard");

        let report = await apiJson<SessionReport>(
          `/api/ip-check/sessions/${encodeURIComponent(session.session_id)}`,
          { headers: auth },
        );
        for (let attempt = 0; attempt < 4 && !report.dns_resolver_addresses.length; attempt += 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 300));
          report = await apiJson<SessionReport>(
            `/api/ip-check/sessions/${encodeURIComponent(session.session_id)}`,
            { headers: auth },
          );
        }
        latestReport = report;
        renderReport(report);
        if (
          qualityButton &&
          (report.https_ipv4_addresses.length || report.https_ipv6_addresses.length)
        ) {
          qualityButton.disabled = false;
        }
        requiredElement<HTMLElement>("#ip-check-results").scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      } catch (error) {
        errorElement.textContent = error instanceof Error ? error.message : String(error);
        errorElement.hidden = false;
      } finally {
        runButton.disabled = false;
      }
    })();
  });
}

initIpCheck();
