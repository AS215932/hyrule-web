import { afterEach, describe, expect, it, vi } from "vitest";

import {
  collectWebRTC,
  extractPublicIceAddress,
  isPublicIp,
  parseExpectedResolvers,
} from "./ip-check";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("public-only candidate handling", () => {
  it("accepts global addresses and rejects private, CGNAT, documentation, and mDNS values", () => {
    expect(isPublicIp("8.8.8.8")).toBe(true);
    expect(isPublicIp("2606:4700:4700::1111")).toBe(true);
    for (const address of [
      "10.0.0.1",
      "100.64.0.10",
      "192.168.1.2",
      "203.0.113.9",
      "127.0.0.1",
      "fe80::1",
      "fd00::1",
      "2001:db8::1",
      "host-123.local",
    ]) {
      expect(isPublicIp(address), address).toBe(false);
    }
  });

  it("extracts only the public address field from an ICE candidate", () => {
    expect(extractPublicIceAddress("candidate:1 1 udp 2122260223 8.8.8.8 54400 typ srflx")).toBe(
      "8.8.8.8",
    );
    expect(
      extractPublicIceAddress("candidate:2 1 udp 2122260223 192.168.1.2 54401 typ host"),
    ).toBeNull();
    expect(
      extractPublicIceAddress("candidate:3 1 udp 2122260223 workstation.local 54402 typ host"),
    ).toBeNull();
  });
});

describe("agent/browser probe inputs", () => {
  it("deduplicates resolver expectations from comma and whitespace input", () => {
    expect(parseExpectedResolvers("1.1.1.0/24, 2606:4700::/32\n1.1.1.0/24")).toEqual([
      "1.1.1.0/24",
      "2606:4700::/32",
    ]);
  });

  it("reports WebRTC as unsupported instead of calling it a leak", async () => {
    vi.stubGlobal("RTCPeerConnection", undefined);
    await expect(collectWebRTC(["stun:stun.hyrule.host:3478"])).resolves.toEqual({
      status: "unsupported",
      publicAddresses: [],
    });
  });
});
