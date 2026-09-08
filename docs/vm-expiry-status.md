# VM expiry presentation

The order status page and its browser updates distinguish suspension, expiry,
elapsed grace, deletion in progress and destruction from historical launch proof.
The page shows the term expiry and the API-provided grace deadline in UTC. It
does not invent a grace period when the API omits it, and does not show a future
deletion deadline for failed or destroyed VMs.

Both the initial server-rendered page and browser view use the same state
precedence. Browsers update the heading, status card and step label together;
stale online/SSH panels are hidden when the VM is no longer provisioned.
Provisioning polls every two seconds. Existing VMs poll once a minute to catch
expiry and renewal while the page remains open; failed, rolled-back and destroyed
states stop polling. No lifecycle mutation or payment is initiated by polling.

Deploy the expiry API contract from AS215932/hyrule-cloud PR117 first and verify
its live public response. Older API responses remain supported for runtime status,
but cannot supply the new grace information. Build with the CI Node 24/npm 11
toolchain and commit the generated `hyrule_web/static/dist` bundle and manifest.
Use the infrastructure repository's reviewed SHA promotion workflow for rollout.

This is owner-visible status, not scheduled delivery of expiry notices. Admin
recovery, proactive notices, retained storage and grace-policy changes from
hyrule-cloud issue110 remain separate requirements.
