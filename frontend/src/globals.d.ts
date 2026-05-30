import type { Eip1193Provider, HyrulePaymentNativeNS, HyrulePaymentsNS } from "./types";

declare global {
  interface Window {
    ethereum?: Eip1193Provider;
    HyrulePayments?: HyrulePaymentsNS;
    HyrulePaymentNative?: HyrulePaymentNativeNS;
    // qrcode-svg UMD global, loaded lazily from a CDN by payment-native.
    QRCode?: new (opts: Record<string, unknown>) => { svg(): string };
  }
}
