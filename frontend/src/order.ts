/**
 * Order-page entry (order.html). Issue #14.
 *
 * Progressive enhancement: intercept the order-form submit, create a durable
 * quote, and send the browser to the reload-safe review URL
 * (/order/review/{quote_id}). That URL survives the mobile wallet handoff
 * reload that previously lost the POSTed order. If the quote call fails, fall
 * back to the form's native POST to /order/review (server-rendered, non-durable
 * — fine for the no-wallet case).
 */

const form = document.querySelector<HTMLFormElement>("[data-order-form]");

if (form) {
  let submitting = false;

  form.addEventListener("submit", (e) => {
    if (submitting) return; // let the native fallback submit through
    e.preventDefault();

    const fd = new FormData(form);
    const orderPayload: Record<string, unknown> = {
      os: fd.get("os"),
      size: fd.get("size"),
      duration_days: parseInt(String(fd.get("duration")), 10),
      ssh_pubkey: fd.get("ssh_pubkey"),
      domain_mode: fd.get("domain_mode") || "auto",
    };
    if (fd.get("domain") && fd.get("domain_mode") === "custom") {
      orderPayload.domain = fd.get("domain");
    }

    const fallback = (): void => {
      submitting = true;
      form.submit();
    };

    void (async () => {
      try {
        const resp = await fetch("/api/v1/vm/quote", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ order_payload: orderPayload }),
        });
        if (resp.ok) {
          const body = await resp.json();
          if (body.quote_id) {
            window.location.href = "/order/review/" + encodeURIComponent(body.quote_id);
            return;
          }
        }
      } catch (err) {
        console.error("quote create failed; falling back to server render", err);
      }
      fallback();
    })();
  });
}
