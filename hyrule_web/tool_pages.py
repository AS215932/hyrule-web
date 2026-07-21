"""Intent-led public pages for Hyrule's strongest network evidence products."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolPage:
    slug: str
    title: str
    meta_description: str
    headline: str
    summary: str
    category: str
    capability_id: str
    method: str
    path: str
    questions: tuple[str, ...]
    evidence: tuple[str, ...]
    workflow: tuple[str, ...]
    related: tuple[str, ...]

    @property
    def url(self) -> str:
        return f"/tools/{self.slug}"

    @property
    def absolute_url(self) -> str:
        return f"https://hyrule.host{self.url}"


TOOL_PAGES: tuple[ToolPage, ...] = (
    ToolPage(
        slug="dns-lookup-api",
        title="DNS Lookup API for AI Agents — Hyrule Cloud",
        meta_description=(
            "Resolve public DNS records through an agent-readable x402 API with resolver, "
            "DNSSEC, timing, and source evidence."
        ),
        headline="Resolve DNS with evidence an agent can act on.",
        summary=(
            "Ask for A, AAAA, MX, TXT, NS, CAA, PTR, or other public records and receive "
            "structured answers instead of screen-scraped troubleshooting output."
        ),
        category="DNS",
        capability_id="hyrule.dns.lookup",
        method="POST",
        path="/v1/dns/lookup",
        questions=(
            "What addresses does this hostname resolve to?",
            "Which MX, TXT, or CAA records are currently public?",
            "Did DNSSEC validation succeed for this answer?",
        ),
        evidence=(
            "Normalized record answers and TTLs",
            "Resolver and response timing context",
            "DNSSEC, truncation, and partial-result state",
        ),
        workflow=(
            "Choose the record name, type, and optional resolver controls.",
            "Validate the payload against the complete OpenAPI contract.",
            "Call the capability with an x402 v2 client and preserve the returned evidence.",
        ),
        related=("dns-propagation-checker", "rdap-domain-ip-lookup", "email-deliverability-check"),
    ),
    ToolPage(
        slug="dns-propagation-checker",
        title="DNS Propagation Checker API — Hyrule Cloud",
        meta_description=(
            "Compare DNS answers across recursive and authoritative resolvers with a paid API "
            "built for automated change verification."
        ),
        headline="Verify where a DNS change has—and has not—arrived.",
        summary=(
            "Compare expected records across named recursive resolvers and authoritative servers "
            "so an agent can distinguish cache lag from an incorrect zone."
        ),
        category="DNS",
        capability_id="hyrule.dns.propagation",
        method="POST",
        path="/v1/dns/propagation",
        questions=(
            "Why is a new record visible from one resolver but not another?",
            "Do authoritative servers agree on the current answer?",
            "Has the previous TTL window actually elapsed?",
        ),
        evidence=(
            "Per-resolver answers and errors",
            "Expected-value comparisons",
            "Authoritative versus recursive disagreement",
        ),
        workflow=(
            "Provide the record name, type, expected values, and resolver set.",
            "Review each vantage independently; do not collapse timeouts into negative answers.",
            "Recheck after the observed TTL when caches legitimately retain the old value.",
        ),
        related=("dns-lookup-api", "website-reachability-check", "email-deliverability-check"),
    ),
    ToolPage(
        slug="bgp-route-lookup",
        title="BGP Route and RPKI Lookup API — Hyrule Cloud",
        meta_description=(
            "Investigate prefix origins, AS paths, RPKI validity, and route visibility through a "
            "structured x402 BGP API."
        ),
        headline="Trace who originates a route and whether the announcement is valid.",
        summary=(
            "Inspect a prefix, IP address, or ASN using public routing evidence and "
            "explicit source "
            "state—useful for reachability incidents, origin changes, and RPKI checks."
        ),
        category="Routing",
        capability_id="hyrule.bgp.lookup",
        method="POST",
        path="/v1/bgp/lookup",
        questions=(
            "Which ASN currently originates this prefix?",
            "Is the observed route valid under RPKI?",
            "How visible is this announcement across public collectors?",
        ),
        evidence=(
            "Observed origin ASNs and route views",
            "RPKI validity and assertion results",
            "Source timestamps, partial states, and collector context",
        ),
        workflow=(
            "Submit a prefix, IP, or ASN subject and select the evidence views needed.",
            "Compare observations with any expected origin or RPKI assertions.",
            "Escalate mismatches with timestamps and sources rather than an inferred diagnosis.",
        ),
        related=("ip-asn-lookup", "port-reachability-check", "website-reachability-check"),
    ),
    ToolPage(
        slug="ip-asn-lookup",
        title="IP Address and ASN Intelligence API — Hyrule Cloud",
        meta_description=(
            "Enrich a public IP with ASN, reverse DNS, registry, routing, and provider-backed "
            "geographic context through one agent API."
        ),
        headline="Turn an IP address into routing and ownership context.",
        summary=(
            "Combine IP-to-ASN, reverse DNS, RDAP/WHOIS, BGP, and configured provider evidence in "
            "one structured response while keeping unavailable views explicit."
        ),
        category="IP intelligence",
        capability_id="hyrule.ip.lookup",
        method="POST",
        path="/v1/ip/lookup",
        questions=(
            "Which network and organization announce this address?",
            "What reverse DNS and registry records identify it?",
            "Which requested evidence views were unavailable or partial?",
        ),
        evidence=(
            "ASN, prefix, and network ownership",
            "Reverse DNS and registry context",
            "Provider-specific confidence and source state",
        ),
        workflow=(
            "Submit one public IP and only the views required for the task.",
            "Check source and partial flags before relying on enrichment fields.",
            "Use BGP or RDAP detail pages when the incident needs deeper evidence.",
        ),
        related=("bgp-route-lookup", "rdap-domain-ip-lookup", "port-reachability-check"),
    ),
    ToolPage(
        slug="rdap-domain-ip-lookup",
        title="RDAP Domain, IP, and ASN Lookup API — Hyrule Cloud",
        meta_description=(
            "Fetch structured RDAP registration data for domains, IPs, prefixes, ASNs, and "
            "entities through an x402 API."
        ),
        headline="Query authoritative registry data without parsing a web page.",
        summary=(
            "Use RDAP when ownership, registrar, delegation, allocation, status, or abuse-contact "
            "context matters and the result needs to remain machine-readable."
        ),
        category="Registry",
        capability_id="hyrule.rdap.lookup",
        method="POST",
        path="/v1/rdap/lookup",
        questions=(
            "Which registrar or registry owns this domain record?",
            "Who received this IP prefix or ASN allocation?",
            "Which status, event, nameserver, and contact fields are published?",
        ),
        evidence=(
            "Normalized RDAP object and event data",
            "Nameserver, entity, and public contact relationships",
            "Bootstrap source, response status, and redaction state",
        ),
        workflow=(
            "Choose the subject type—domain, IP, prefix, ASN, or entity—and supply its value.",
            "Treat redacted or absent contact data as unknown, not proof that no contact exists.",
            "Use legacy WHOIS only when RDAP does not expose the required registry context.",
        ),
        related=("whois-lookup-api", "dns-lookup-api", "ip-asn-lookup"),
    ),
    ToolPage(
        slug="whois-lookup-api",
        title="WHOIS Lookup API for Domains and Networks — Hyrule Cloud",
        meta_description=(
            "Run legacy WHOIS lookups for domains, IPs, prefixes, and ASNs with parsed, redacted, "
            "agent-readable results."
        ),
        headline="Use legacy WHOIS when RDAP does not tell the whole story.",
        summary=(
            "Query registry WHOIS and receive both bounded raw context and parsed fields, with "
            "redaction and upstream failure represented honestly."
        ),
        category="Registry",
        capability_id="hyrule.whois.lookup",
        method="POST",
        path="/v1/whois/lookup",
        questions=(
            "Does the legacy registry publish a field absent from RDAP?",
            "Which nameservers, dates, or status values appear in WHOIS?",
            "Did referral chasing reach an authoritative WHOIS service?",
        ),
        evidence=(
            "Parsed registration and delegation fields",
            "Bounded raw response for audit context",
            "Referral, redaction, timeout, and source state",
        ),
        workflow=(
            "Try RDAP first for structured standards-based data.",
            "Submit the same subject to WHOIS only when legacy context is needed.",
            "Preserve the registry source and never infer private data from redaction markers.",
        ),
        related=("rdap-domain-ip-lookup", "dns-lookup-api", "ip-asn-lookup"),
    ),
    ToolPage(
        slug="website-reachability-check",
        title="Website Reachability Check API — Hyrule Cloud",
        meta_description=(
            "Check public DNS, HTTP, HTTPS, certificates, headers, and CDN/WAF behavior through a "
            "structured website diagnostics API."
        ),
        headline="Find out why a public website is unreachable or behaving differently.",
        summary=(
            "Collect connected DNS, HTTP, TLS, certificate, header, and CDN/WAF evidence for one "
            "public target instead of guessing from a single local browser."
        ),
        category="Web",
        capability_id="hyrule.web.check",
        method="POST",
        path="/v1/web/check",
        questions=(
            "Is the failure in DNS, TCP/TLS, HTTP, or application behavior?",
            "Does HTTPS present the expected hostname and certificate chain?",
            "Are a CDN, WAF, redirect, or security header changing the result?",
        ),
        evidence=(
            "DNS and connection observations",
            "HTTP status, redirect, and selected header details",
            "TLS/certificate and CDN/WAF signals with timestamps",
        ),
        workflow=(
            "Submit a public URL and select only the checks relevant to the incident.",
            "Separate unreachable evidence from provider or vantage unavailability.",
            "Use the deep TLS audit when protocol and cipher grading is required.",
        ),
        related=("tls-certificate-audit", "dns-propagation-checker", "port-reachability-check"),
    ),
    ToolPage(
        slug="tls-certificate-audit",
        title="TLS Certificate and Cipher Audit API — Hyrule Cloud",
        meta_description=(
            "Audit public TLS protocols, ciphers, certificate chains, OCSP, HSTS, CAA, and headers "
            "with an agent-readable API."
        ),
        headline="Audit a public TLS endpoint beyond a simple certificate expiry check.",
        summary=(
            "Inspect protocol support, cipher posture, certificate chain and hostname validity, "
            "revocation signals, HSTS, CAA, and related web security evidence."
        ),
        category="TLS",
        capability_id="hyrule.web.tls.deep",
        method="POST",
        path="/v1/web/tls/deep",
        questions=(
            "Which TLS versions and cipher families does this host accept?",
            "Is the certificate chain valid for the requested hostname?",
            "Do OCSP, HSTS, CAA, and security headers expose deployment gaps?",
        ),
        evidence=(
            "Protocol, cipher, and key-exchange observations",
            "Certificate identity, chain, date, and revocation context",
            "HSTS, CAA, and related header findings",
        ),
        workflow=(
            "Run the quick website check first unless a deep cryptographic audit is requested.",
            "Submit the public host, port, and supported scan profile.",
            "Report observed evidence and grade rationale without claiming SSL Labs affiliation.",
        ),
        related=("website-reachability-check", "port-reachability-check", "dns-lookup-api"),
    ),
    ToolPage(
        slug="email-deliverability-check",
        title="Email Deliverability and MX Check API — Hyrule Cloud",
        meta_description=(
            "Diagnose MX, SPF, DKIM, DMARC, SMTP, TLS, blocklist, and bounce problems through a "
            "structured mail-delivery API."
        ),
        headline="Diagnose why mail is missing, rejected, delayed, or filtered.",
        summary=(
            "Run one focused MX-style check or build toward a broader delivery report using DNS "
            "authentication, SMTP reachability, TLS, reputation, and bounce evidence."
        ),
        category="Mail",
        capability_id="hyrule.mx.check",
        method="POST",
        path="/v1/mx/check",
        questions=(
            "Are MX, SPF, DKIM, and DMARC records coherent for this sender?",
            "Can public SMTP endpoints be reached and negotiate STARTTLS?",
            "Does a bounce or blocklist result point to a specific remediation?",
        ),
        evidence=(
            "DNS authentication and alignment checks",
            "SMTP, TLS, reverse-DNS, and reputation observations",
            "Finding-specific recommendations based on observed data",
        ),
        workflow=(
            "Start with the exact failure: a bounce, one DNS control, or SMTP reachability.",
            "Run the matching focused tool against the public sender or receiver context.",
            "Recommend records only when the evidence contains enough customer-specific data.",
        ),
        related=("dns-lookup-api", "port-reachability-check", "website-reachability-check"),
    ),
    ToolPage(
        slug="port-reachability-check",
        title="Public Port Reachability Check API — Hyrule Cloud",
        meta_description=(
            "Check one declared public TCP or UDP service from an outside vantage with strict "
            "target and port safety controls."
        ),
        headline="Check whether one public service is reachable from outside.",
        summary=(
            "Probe a declared service port from Hyrule's external diagnostic surface. This is a "
            "bounded support tool—not a general port scanner or range scan."
        ),
        category="Reachability",
        capability_id="hyrule.ports.check",
        method="POST",
        path="/v1/ports/check",
        questions=(
            "Can the public internet reach this HTTPS, SMTP, SSH, or SIP port?",
            "Did the connection time out, refuse, or return an allowed banner?",
            "Does outside-in evidence disagree with the server's local listener state?",
        ),
        evidence=(
            "Resolved public target and selected vantage",
            "Connection result, latency, and bounded banner context",
            "Explicit safety rejection for private or unsupported targets",
        ),
        workflow=(
            "Declare one public target, one allowed port, protocol, and service profile.",
            "Compare outside-in evidence with local firewall and listener state.",
            "Use web, mail, or SIP diagnostics when the application protocol needs inspection.",
        ),
        related=("nat-port-forward-check", "website-reachability-check", "sip-diagnostics"),
    ),
    ToolPage(
        slug="nat-port-forward-check",
        title="NAT Port Forwarding Check API — Hyrule Cloud",
        meta_description=(
            "Verify a declared public port forward from an external vantage and distinguish basic "
            "NAT/CGNAT symptoms from service failures."
        ),
        headline="Verify a port forward from the side of the internet that must reach it.",
        summary=(
            "Test one customer-declared mapping and combine the result with server-observed IP "
            "classification. Precise NAT type still requires client-assisted STUN evidence."
        ),
        category="NAT",
        capability_id="hyrule.nat.port-forward.check",
        method="POST",
        path="/v1/nat/port-forward/check",
        questions=(
            "Is the forwarded public TCP or UDP service reachable?",
            "Could CGNAT explain why router forwarding rules never receive traffic?",
            "Is the result a timeout, refusal, unsafe target, or successful connection?",
        ),
        evidence=(
            "Outside-in connection outcome",
            "Public target resolution and service profile",
            "Bounded NAT/CGNAT interpretation without fabricated NAT typing",
        ),
        workflow=(
            "Compare the customer's WAN address with the free server-observed IP endpoint.",
            "Submit one declared public target and forwarded port for the external check.",
            "Treat a CGNAT hint as a lead, not proof of the customer's exact NAT topology.",
        ),
        related=("port-reachability-check", "ip-asn-lookup", "sip-diagnostics"),
    ),
    ToolPage(
        slug="sip-diagnostics",
        title="SIP DNS and TLS Diagnostics API — Hyrule Cloud",
        meta_description=(
            "Test public SIP DNS, SRV, TLS, OPTIONS, and STUN/TURN context for PBX, trunk, and "
            "softphone troubleshooting."
        ),
        headline="Trace SIP failures across DNS, transport, and TLS.",
        summary=(
            "Investigate hosted PBX, SIP trunk, and softphone reachability with public DNS, SRV, "
            "TLS, OPTIONS, and STUN/TURN evidence selected for the incident."
        ),
        category="VoIP",
        capability_id="hyrule.voip.check",
        method="POST",
        path="/v1/voip/check",
        questions=(
            "Do SIP NAPTR/SRV records lead to a reachable service?",
            "Does the SIP TLS endpoint present a valid certificate?",
            "Can an allowed SIP OPTIONS check reach the declared public target?",
        ),
        evidence=(
            "SIP DNS and service selection",
            "TLS identity and transport reachability",
            "Check-specific source, timeout, and partial states",
        ),
        workflow=(
            "Select SIP DNS, TLS, OPTIONS, or STUN/TURN checks relevant to the ticket.",
            "Submit only a public customer-declared target and supported SIP port.",
            "Use the single-port checker when no SIP protocol interpretation is required.",
        ),
        related=("port-reachability-check", "nat-port-forward-check", "dns-lookup-api"),
    ),
)


TOOL_PAGES_BY_SLUG = {page.slug: page for page in TOOL_PAGES}
