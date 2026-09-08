# VM expiry presentation

The order status page and its browser updates distinguish suspension, expiry,
elapsed grace, deletion in progress and destruction from historical launch proof.
The page shows the term expiry and the API-provided grace deadline in UTC. It
does not invent a grace period when the API omits it, and does not show a future
deletion deadline for failed or destroyed VMs.

Both the initial server-rendered page and browser view use the same state
precedence. Browsers update the heading, status card and step label together;
stale online/SSH panels are hidden when the VM is no longer provisioned.
Provisioning, retention verification and recovery poll every two seconds.
Retained and other existing VMs poll once a minute to catch
expiry and renewal while the page remains open; failed, rolled-back and destroyed
states stop polling. No lifecycle mutation or payment is initiated by polling.

Retention states from cloud PR119 distinguish verification pending, data retained
and recovery in progress. Their API-provided minimum retention date is shown in
UTC, without stale grace dates or a promise of automatic deletion. Recovery
remains a support action; the page does not start a stopped VM. Connection
instructions return only when the API reports that the VM is ready.

Deploy the expiry API contract from AS215932/hyrule-cloud PR117 first and verify
its live public response. Retention presentation additionally requires the
contract in cloud PR119. Older API responses remain supported for runtime status,
but cannot supply the new grace information. Build with the CI Node 24/npm 11
toolchain and commit the generated `hyrule_web/static/dist` bundle and manifest.
Use the infrastructure repository's reviewed SHA promotion workflow for rollout.

This is owner-visible status, not scheduled delivery of expiry notices. Admin
recovery operations, proactive notices, retained storage and grace-policy changes from
hyrule-cloud issue110 remain separate requirements.
