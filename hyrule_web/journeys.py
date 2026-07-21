"""Outcome-led campaign copy. Results stay explicitly non-live until canaries land."""

# Exact prompts and runnable JSON commands intentionally remain on single source
# lines so published copy can be compared byte-for-byte with client fixtures.
# ruff: noqa: E501

from __future__ import annotations

from typing import Any

CAMPAIGN_LAUNCH = "2026-08-04"

_WEBSITE_PROMPT = """Diagnose <URL> from the public internet. Use Hyrule's web check first and deep TLS evidence only if needed. Test DNS, address reachability, HTTP redirects/status, certificate chain/hostname/expiry, protocol support, and relevant IPv4/IPv6 differences. Do not change the target. Return the primary cause, ranked supporting findings, exact redacted commands, source evidence, exact settled cost, UTC start/end, and elapsed seconds. Keep total spend at or below $0.25; ask once before exceeding it."""

_MAIL_PROMPT = """From these candidate domains, choose the first available non-premium name: <CANDIDATES>. Obtain a live one-year domain quote and combine it atomically with a 30-day agent@<domain> Agent Mail activation. Show the exact combined amount and continue without another question only when it is at or below $26.10; otherwise ask once. Save the returned identity token securely. Poll until active, then verify authoritative MX, SPF, DKIM, DMARC, TLS-RPT, MTA-STS, A/AAAA, and PTR/FCrDNS evidence. Send exactly one controlled message to <CONTROLLED_RECIPIENT> and prove one controlled inbound reply. If the message is rejected or spam-filtered, preserve and parse the full bounce and remote MX, run the full mail-delivery report, and distinguish observed DNS, SMTP, IP/ASN reputation, and content inferences. Return redacted commands and identifiers, exact settled costs, UTC start/end, elapsed time per phase, and the 30-day/7-day deletion timeline. Never send to any other recipient."""

_VM_PROMPT = """Provision an xs Debian 13 VM for <WORKLOAD> for 45 days. Use Hyrule's automatically assigned hostname, open only the workload ports plus SSH, and keep new spend at or below $12.00; ask once before exceeding it. Poll to ready, then verify the returned DNS name, public IPv6 reachability, service TLS/HTTP where applicable, and SSH connection details without exposing private keys. Return the redacted exact command, resource ids, connection details, evidence, exact settled cost, UTC start/end, elapsed time per phase, and expiry/cleanup date."""


def _variants(prompt: str, discovery: str, skill: str) -> list[dict[str, str]]:
    return [
        {
            "name": "Coinbase Bazaar MCP",
            "prompt": (
                "Using the Coinbase x402 Bazaar MCP, search for the Hyrule Cloud resource "
                "that matches this outcome, inspect its live schema and price, and execute "
                f"it through proxy_tool_call. {prompt}"
            ),
            "command": (
                "# MCP endpoint\n"
                "https://api.cdp.coinbase.com/platform/v2/x402/discovery/mcp\n\n"
                "# JavaScript client dependencies\n"
                "npm install @x402/mcp @x402/fetch @x402/evm "
                "@modelcontextprotocol/sdk viem"
            ),
            "note": "Bazaar indexes a Hyrule route only after a successful CDP Facilitator settlement.",
        },
        {
            "name": "OpenClaw",
            "prompt": f"Use ${skill}. {prompt}",
            "command": f"openclaw skills install @as215932/{skill}",
            "note": "Launch command; the public Skill remains withheld until its production canary passes.",
        },
        {
            "name": "Generic Agent Skills",
            "prompt": f"Load the {skill} Skill and follow its readiness, budget, and evidence rules. {prompt}",
            "command": discovery,
            "note": "The discovery call is runnable without payment; the client must handle the live x402 v2 retry.",
        },
    ]


JOURNEYS: tuple[dict[str, Any], ...] = (
    {
        "slug": "explain-broken-website-tls",
        "number": "01",
        "title": "Explain why this website or TLS deployment is broken",
        "short_title": "Broken website or TLS",
        "dek": "Start with one public check, escalate to a deep TLS scan only when the evidence requires it, and return a ranked cause rather than raw scanner output.",
        "prompt": _WEBSITE_PROMPT,
        "command": """curl -sS -X POST https://cloud.hyrule.host/v1/web/check \\
  -H 'Content-Type: application/json' \\
  -d '{"url":"<URL>"}'""",
        "cost": "$0.005 first check; up to $0.105 with deep TLS. Hard cap: $0.25.",
        "elapsed": "Observed time will be published from the production canary; no estimate is presented as measurement.",
        "steps": [
            "Normalize the URL and capture DNS/address evidence.",
            "Run the public web check and classify HTTP, reachability, and basic TLS findings.",
            "Buy the $0.10 deep TLS scan only when the first result leaves a chain, hostname, expiry, or protocol question open.",
            "Return one primary cause, supporting evidence, remediation, exact spend, and measured time.",
        ],
        "result": [
            (
                "Run status",
                "Production canary pending — this is a launch-proof template, not a claimed customer result.",
            ),
            ("Target", "<redacted customer URL>"),
            ("Primary cause", "Will be populated only from observed public evidence."),
            ("Settled cost", "$— (no production payment claimed)"),
            ("Elapsed", "— seconds (no production run claimed)"),
        ],
        "variants": _variants(
            _WEBSITE_PROMPT,
            "curl -sS https://cloud.hyrule.host/.well-known/x402.json",
            "hyrule-customer-journeys",
        ),
    },
    {
        "slug": "agent-email-domain-deliverability",
        "number": "02",
        "title": "Buy an agent email identity, then diagnose rejected or spammed mail",
        "short_title": "Agent email identity",
        "dek": "Turn deliverability diagnosis into a complete identity outcome: domain, API-only mailbox, controlled send/receive proof, and evidence-led troubleshooting.",
        "prompt": _MAIL_PROMPT,
        "command": """curl -sS https://cloud.hyrule.host/v1/mail/products

curl -sS -X POST https://cloud.hyrule.host/v1/mail/accounts/quote \\
  -H 'Content-Type: application/json' \\
  -d '{"local_part":"agent","mode":"domain_and_mailbox","domain":"<CANDIDATE>","terms_version":"<LIVE_MAIL_TERMS>","domain_terms_version":"<LIVE_DOMAIN_TERMS>"}'""",
        "cost": "Live one-year domain quote + live Agent Mail activation + live controlled outbound fee. Hard cap: $26.10.",
        "elapsed": "Split into quote/payment, registrar, mailbox/DNS, send/receive, and diagnosis phases in the real canary.",
        "steps": [
            "Choose only from the ordered candidate list and reject premium or over-cap quotes.",
            "Settle one atomic domain-plus-mailbox x402 payment and save the shared capability token.",
            "Verify MX, SPF, DKIM, DMARC, TLS-RPT, MTA-STS, A/AAAA, and PTR/FCrDNS from public resolvers.",
            "Send to exactly one controlled recipient, prove an inbound reply, and parse any full bounce before broader diagnosis.",
        ],
        "result": [
            (
                "Run status",
                "Dedicated Stalwart and production canary pending — no mailbox result is claimed yet.",
            ),
            ("Identity", "agent@<redacted-domain>"),
            ("Delivery proof", "Pending one-recipient controlled canary and inbound reply."),
            ("Settled cost", "$— (no registrar or mail payment claimed)"),
            ("Elapsed", "— seconds by phase (no production run claimed)"),
        ],
        "variants": _variants(
            _MAIL_PROMPT,
            "curl -sS https://cloud.hyrule.host/v1/mail/products",
            "hyrule-agent-mail",
        ),
    },
    {
        "slug": "deploy-fresh-vm",
        "number": "03",
        "title": "Deploy a fresh VM and return connection details",
        "short_title": "Fresh workload VM",
        "dek": "Provision only the declared workload, use the automatically assigned hostname, and return externally verified connection details.",
        "prompt": _VM_PROMPT,
        "command": """curl -sS -X POST https://cloud.hyrule.host/v1/vm/quote \\
  -H 'Content-Type: application/json' \\
  -d '{"order_payload":{"duration_days":45,"size":"xs","os":"debian-13","ssh_pubkey":"<SSH_PUBLIC_KEY>","domain_mode":"auto","open_ports":[22,<WORKLOAD_PORTS>]},"client_order_id":"<HIGH_ENTROPY_ID>"}'""",
        "cost": "45 times the live xs daily price; numeric example withheld when the catalog is unavailable. Hard cap: $12.00.",
        "elapsed": "Quote, payment, provisioning, DNS, and outside-in verification are measured separately in the real canary.",
        "steps": [
            "Replace <WORKLOAD_PORTS> with the workload's comma-separated numeric ports; keep SSH port 22, and quote an xs Debian 13 VM for 45 days.",
            "Use the returned automatic hostname; never expose the private SSH key.",
            "Poll to ready, attach the hostname, then verify DNS and public IPv6 reachability.",
            "Return SSH/service connection details, exact cost, measured time, and expiry date.",
        ],
        "result": [
            (
                "Run status",
                "Production VM/domain canary pending — no connection result is claimed yet.",
            ),
            ("VM", "vm_<redacted> · Debian 13 · xs"),
            ("Connection", "ssh root@<redacted-hostname> (published only after outside-in proof)"),
            ("Settled cost", "$— (no production payment claimed)"),
            ("Elapsed", "— seconds by phase (no production run claimed)"),
        ],
        "variants": _variants(
            _VM_PROMPT,
            "curl -sS https://cloud.hyrule.host/v1/products/vms",
            "hyrule-customer-journeys",
        ),
    },
)

JOURNEYS_BY_SLUG = {journey["slug"]: journey for journey in JOURNEYS}
