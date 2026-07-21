"""Project payable operations from Hyrule's complete OpenAPI document.

The canonical ``/openapi.json`` documents the whole API. Only operations with
``x-payment-info`` belong in the browser toolbox and paid marketing tables.
Keeping that projection here makes HTML, llms.txt, and WebMCP consume the same
annotations without mistaking free or authenticated operations for x402 tools.
"""

from __future__ import annotations

import re
from typing import Any

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})
_REF_PREFIX = "#/components/schemas/"
_TITLE_WORDS = {
    "bgp": "BGP",
    "bgpstream": "BGPStream",
    "cgnat": "CGNAT",
    "dns": "DNS",
    "ip": "IP",
    "mx": "MX",
    "nat": "NAT",
    "rdap": "RDAP",
    "sip": "SIP",
    "tls": "TLS",
    "voip": "VoIP",
    "vm": "VM",
    "whois": "WHOIS",
}
_CATALOG_PRESENTATION: dict[str, tuple[str, str]] = {
    "/v1/bgp/lookup": (
        "BGP",
        "Inspect origins, paths, RPKI validity, and route visibility for a prefix, IP, or ASN.",
    ),
    "/v1/dns/lookup": (
        "DNS",
        "Resolve DNS records with resolver, DNSSEC, trace, and timeout controls.",
    ),
    "/v1/dns/propagation": (
        "PROP",
        "Compare DNS answers across recursive and authoritative resolvers.",
    ),
    "/v1/ip/lookup": (
        "IP",
        "Collect ownership, reverse DNS, registry, reputation, and BGP context for an address.",
    ),
    "/v1/mx/jobs": (
        "MX JOB",
        "Run a bundled mail-delivery or domain-health diagnostic and retrieve a durable report.",
    ),
    "/v1/mx/check": (
        "MX",
        "Test one mail or DNS concern such as MX, SPF, DKIM, SMTP, TLS, or blocklists.",
    ),
    "/v1/mx/bounce/parse": (
        "BOUNCE",
        "Classify a mail bounce into probable causes and recommended actions.",
    ),
    "/v1/nat/port-forward/check": (
        "NAT",
        "Check whether a forwarded TCP or UDP port is reachable from an outside vantage point.",
    ),
    "/v1/ports/check": (
        "PORT",
        "Probe a TCP or UDP service from an outside vantage point, with optional banner capture.",
    ),
    "/v1/rdap/lookup": (
        "RDAP",
        "Fetch structured registration data for a domain, IP, prefix, ASN, or entity.",
    ),
    "/v1/whois/lookup": (
        "WHOIS",
        "Query registry WHOIS data with a parsed, redacted response.",
    ),
    "/v1/voip/check": (
        "SIP",
        "Test SIP DNS, OPTIONS, TLS, STUN/TURN, number intelligence, and reputation.",
    ),
    "/v1/web/tls/deep": (
        "TLS",
        "Audit protocol versions, ciphers, certificates, OCSP, HSTS, CAA, and security headers.",
    ),
    "/v1/web/check": (
        "WEB",
        "Check DNS, HTTP, HTTPS, TLS, certificates, headers, CDN/WAF, and availability.",
    ),
    "/v1/vm/create": (
        "VM",
        "Configure and deploy prepaid compute through the dedicated order flow.",
    ),
    "/v1/network/request": (
        "PROXY",
        "Send an outbound HTTP request over direct, Tor, I2P, or Yggdrasil egress.",
    ),
}
_BROWSER_TOOL_FIELDS = frozenset(
    {
        "operation_id",
        "capability_id",
        "method",
        "path",
        "title",
        "description",
        "catalog_blurb",
        "tool_code",
        "search_terms",
        "intents",
        "capabilities",
        "category",
        "executable",
        "input_schema",
        "input_example",
        "parameters",
        "price_display",
    }
)


def _resolve_schema(
    value: Any,
    schemas: dict[str, Any],
    seen: frozenset[str] = frozenset(),
) -> Any:
    """Inline local component references while preserving recursive schemas."""
    if isinstance(value, list):
        return [_resolve_schema(item, schemas, seen) for item in value]
    if not isinstance(value, dict):
        return value

    ref = value.get("$ref")
    if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
        name = ref.removeprefix(_REF_PREFIX)
        if name in seen:
            return {"type": "object", "title": name}
        target = schemas.get(name)
        if isinstance(target, dict):
            resolved = _resolve_schema(target, schemas, seen | {name})
            if isinstance(resolved, dict):
                overlay = {
                    key: _resolve_schema(item, schemas, seen)
                    for key, item in value.items()
                    if key != "$ref"
                }
                return {**resolved, **overlay}

    return {key: _resolve_schema(item, schemas, seen) for key, item in value.items()}


def _operation_group(path: str, tags: list[str]) -> str:
    if path.startswith("/v1/vm"):
        return "compute"
    if path.startswith("/v1/domains"):
        return "domains"
    if path.startswith("/v1/network"):
        return "proxy"
    return "intel" if tags else "other"


def _display_title(value: str) -> str:
    return " ".join(_TITLE_WORDS.get(word.lower(), word) for word in value.split())


def _catalog_presentation(path: str, title: str, category: str) -> tuple[str, str]:
    """Return a terse drawer label and human catalog copy for a paid route.

    The detailed generated contract remains available in the Configure
    workspace. This layer is deliberately small and path-keyed so unknown
    enabled operations still appear without inventing capabilities.
    """
    known = _CATALOG_PRESENTATION.get(path)
    if known:
        code, blurb = known
        return blurb, code

    label = category or title or path.rsplit("/", 1)[-1]
    words = re.findall(r"[A-Za-z0-9]+", label)
    code = " ".join(words[:2]).upper()[:12] or "TOOL"
    return f"Run {title} with a live x402 quote.", code


def _field_names(schema: Any, limit: int = 6) -> list[str]:
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return []
    names = [str(name).replace("_", " ") for name in properties]
    return [*names[:limit], "and more"] if len(names) > limit else names


def _generated_description(
    input_schema: Any,
    parameters: list[dict[str, Any]],
    output_schema: Any,
) -> str:
    inputs = [str(parameter.get("name", "")).replace("_", " ") for parameter in parameters]
    inputs.extend(name for name in _field_names(input_schema) if name not in inputs)
    outputs = _field_names(output_schema)
    parts: list[str] = []
    if inputs:
        parts.append(f"Inputs: {', '.join(inputs)}.")
    if outputs:
        parts.append(f"Returns: {', '.join(outputs)}.")
    return " ".join(parts) or "Run this enabled paid operation with a live x402 quote."


def _search_terms(
    base: list[str], input_schema: Any, output_schema: Any, example: Any
) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                add(str(key).replace("_", " "))
                add(item)
        elif isinstance(value, list):
            for item in value[:20]:
                add(item)
        elif isinstance(value, str) and 0 < len(value) <= 120:
            normalized = value.strip()
            folded = normalized.lower()
            if normalized and folded not in seen:
                terms.append(normalized)
                seen.add(folded)

    add(base)
    add(_field_names(input_schema, 30))
    add(_field_names(output_schema, 30))
    add(example)
    return terms


def _handoff_url(path: str) -> str:
    if path.startswith("/v1/vm"):
        return "/order"
    if path.startswith("/v1/domains"):
        return "/domains"
    if path.startswith("/v1/network"):
        return "/services#proxy"
    return "https://cloud.hyrule.host/openapi.json"


def _price_fields(operation: dict[str, Any]) -> tuple[dict[str, str], str | None, str]:
    payment = operation.get("x-payment-info")
    raw = payment.get("price") if isinstance(payment, dict) else None
    price = (
        {str(key): str(value) for key, value in raw.items() if value is not None}
        if isinstance(raw, dict)
        else {}
    )

    amount = price.get("amount") or price.get("min")
    if price.get("mode") == "fixed" and amount:
        display = f"${amount}"
    elif amount and price.get("max"):
        display = f"${amount}\N{EN DASH}${price['max']}"
    elif amount:
        display = f"from ${amount}"
    else:
        display = "Live 402 quote"
    return price, amount, display


def _response_contract(
    operation: dict[str, Any], schemas: dict[str, Any]
) -> tuple[list[str], dict[str, Any]]:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return [], {}
    for status in sorted(responses):
        if not str(status).startswith("2"):
            continue
        response = responses.get(status)
        content = response.get("content") if isinstance(response, dict) else None
        if not isinstance(content, dict):
            return [], {}
        media_types = [str(media_type) for media_type in content]
        preferred = content.get("application/json")
        if not isinstance(preferred, dict) and content:
            preferred = next(iter(content.values()))
        schema = preferred.get("schema") if isinstance(preferred, dict) else None
        resolved = _resolve_schema(schema, schemas)
        return media_types, resolved if isinstance(resolved, dict) else {}
    return [], {}


def normalize_openapi(document: dict[str, Any]) -> dict[str, Any]:
    """Return the compact, browser-safe toolbox catalog from OpenAPI 3.x."""
    components = document.get("components")
    schema_map = components.get("schemas") if isinstance(components, dict) else None
    schemas: dict[str, Any] = schema_map if isinstance(schema_map, dict) else {}
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return {"tools": []}

    tools: list[dict[str, Any]] = []
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        path_parameters = path_item.get("parameters")
        inherited = path_parameters if isinstance(path_parameters, list) else []
        for method, raw_operation in path_item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(raw_operation, dict):
                continue
            operation: dict[str, Any] = raw_operation
            if not isinstance(operation.get("x-payment-info"), dict):
                continue
            raw_tags = operation.get("tags")
            tags = (
                [str(tag) for tag in raw_tags if isinstance(tag, str)]
                if isinstance(raw_tags, list)
                else []
            )
            raw_intents = operation.get("x-hyrule-intents")
            intents = (
                [str(value) for value in raw_intents if isinstance(value, str)]
                if isinstance(raw_intents, list)
                else []
            )
            raw_capabilities = operation.get("x-hyrule-capabilities")
            capabilities = (
                [str(value) for value in raw_capabilities if isinstance(value, str)]
                if isinstance(raw_capabilities, list)
                else []
            )
            capability_id = str(operation.get("x-hyrule-capability-id") or "")
            operation_id = str(
                operation.get("operationId")
                or re.sub(r"[^a-z0-9]+", "_", f"{method}_{path}".lower()).strip("_")
            )
            request_body = operation.get("requestBody")
            content = request_body.get("content") if isinstance(request_body, dict) else None
            json_body = content.get("application/json") if isinstance(content, dict) else None
            body_schema = json_body.get("schema") if isinstance(json_body, dict) else None
            body_example = json_body.get("example") if isinstance(json_body, dict) else None

            raw_parameters = operation.get("parameters")
            own_parameters = raw_parameters if isinstance(raw_parameters, list) else []
            parameters: list[dict[str, Any]] = []
            for parameter in [*inherited, *own_parameters]:
                if not isinstance(parameter, dict):
                    continue
                schema = _resolve_schema(parameter.get("schema", {}), schemas)
                parameters.append(
                    {
                        "name": str(parameter.get("name", "")),
                        "in": str(parameter.get("in", "query")),
                        "required": bool(parameter.get("required", False)),
                        "description": str(parameter.get("description", "")),
                        "example": parameter.get("example"),
                        "schema": schema if isinstance(schema, dict) else {},
                    }
                )

            price, min_price, price_display = _price_fields(operation)
            response_media_types, output_schema = _response_contract(operation, schemas)
            input_schema = _resolve_schema(body_schema or {"type": "object"}, schemas)
            summary = _display_title(
                str(operation.get("summary") or operation.get("description") or operation_id)
            )
            explicit_description = operation.get("description")
            description = (
                str(explicit_description)
                if explicit_description and _display_title(str(explicit_description)) != summary
                else _generated_description(input_schema, parameters, output_schema)
            )
            category = tags[0] if tags else _operation_group(path, tags).title()
            catalog_blurb, tool_code = _catalog_presentation(path, summary, category)
            search_terms = _search_terms(
                [
                    summary,
                    catalog_blurb,
                    description,
                    capability_id,
                    path,
                    *tags,
                    *intents,
                    *capabilities,
                ],
                input_schema,
                output_schema,
                body_example,
            )
            executable = bool(tags)
            tools.append(
                {
                    "operation_id": operation_id,
                    "capability_id": capability_id,
                    "method": method.upper(),
                    "path": path,
                    "title": summary,
                    "description": description,
                    "catalog_blurb": catalog_blurb,
                    "tool_code": tool_code,
                    "search_terms": search_terms,
                    "tags": tags,
                    "intents": intents,
                    "capabilities": capabilities,
                    "category": category,
                    "group": _operation_group(path, tags),
                    "executable": executable,
                    "handoff_url": None if executable else _handoff_url(path),
                    "input_schema": input_schema,
                    "input_example": body_example if isinstance(body_example, dict) else {},
                    "parameters": parameters,
                    "output_schema": output_schema,
                    "response_media_types": response_media_types,
                    "price": price,
                    "min_price": min_price,
                    "price_display": price_display,
                }
            )

    tools.sort(
        key=lambda tool: (not bool(tool["executable"]), str(tool["category"]), str(tool["title"]))
    )
    info = document.get("info")
    return {
        "title": str(info.get("title", "Hyrule x402")) if isinstance(info, dict) else "Hyrule x402",
        "version": str(info.get("version", "")) if isinstance(info, dict) else "",
        "tools": tools,
    }


def catalog_resources(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Map normalized tools onto the small row shape used by marketing tables."""
    tools = snapshot.get("tools")
    if not isinstance(tools, list):
        return []
    live = snapshot.get("status") == "live"
    rows: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        rows.append(
            {
                "path": str(tool.get("path", "")),
                "method": str(tool.get("method", "POST")),
                "description": str(tool.get("description", "")),
                "min_price": str(tool.get("min_price")) if live and tool.get("min_price") else None,
                "price_display": str(tool.get("price_display", "Live 402 quote"))
                if live
                else "Unavailable",
                "group": str(tool.get("group", "other")),
            }
        )
    return rows


def browser_catalog(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Drop server-only response schemas and price internals from page JSON."""
    result = {key: value for key, value in snapshot.items() if key != "tools"}
    tools = snapshot.get("tools")
    result["tools"] = (
        [
            {key: value for key, value in tool.items() if key in _BROWSER_TOOL_FIELDS}
            for tool in tools
            if isinstance(tool, dict)
        ]
        if isinstance(tools, list)
        else []
    )
    return result
