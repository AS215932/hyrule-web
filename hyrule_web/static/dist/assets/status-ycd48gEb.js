var e=2e3,t=6e4,n={expired:[`EXPIRED`,`Your VM has expired.`,`Renew before the grace period ends to avoid deletion.`],deletion_eligible:[`GRACE PERIOD ENDED`,`The grace period has ended.`,`This VM is eligible for deletion. Contact support immediately for recovery options.`],deleting:[`DELETION STARTED`,`VM deletion has started.`,`Contact support for the remaining recovery options.`],suspended:[`SUSPENDED`,`Your VM is suspended.`,`Check the expiry information below and contact support for recovery.`],destroyed:[`DESTROYED`,`Your VM is destroyed.`,`Contact support if you need assistance.`]};function r(e){return Object.prototype.hasOwnProperty.call(n,e)}function i(e){if(r(e))return[n[e][1],n[e][2]];switch(e){case`provisioned`:return[`Your VM is online.`,`Connection details are below.`];case`failed`:return[`Provisioning failed.`,`See the failure message and support path below.`];case`rolled_back`:return[`Order rolled back.`,`See the status card for details.`];case`payment_required`:return[`Payment required.`,`Complete payment to begin the build.`];default:return[`Your VM is being provisioned.`,`This page checks for provisioning updates automatically.`]}}function a(e){let t=/[T ]/.test(e)&&!/(Z|[+-]\d{2}:?\d{2})$/i.test(e)?`${e}Z`:e,n=new Date(t);return Number.isNaN(n.getTime())?`Unavailable`:`${n.toISOString().slice(0,16).replace(`T`,` `)} UTC`}function o(e){let t=e.status!==`destroyed`&&e.status!==`failed`&&[`active`,`expired`,`deletion_eligible`].includes(e.expiry?.state??``)?e.expiry?.grace_ends_at:null;return!e.expires_at&&!t?``:`<div class="kv-block mt-4">
    ${e.expires_at?`<div class="kv"><span class="k">Term expires</span><span class="v">${l(a(e.expires_at))}</span></div>`:``}
    ${t?`<div class="kv"><span class="k">Grace period ends</span><span class="v">${l(a(t))}</span></div><p class="text-text-soft mt-2">After this deadline, the VM is eligible for deletion. Recovery is not guaranteed.</p>`:``}
  </div>`}function s(e){if(e.status===`destroyed`||e.expiry?.state===`destroyed`)return`destroyed`;if(e.expiry?.state===`deleting`)return`deleting`;if(e.status===`failed`)return e.launch_proof_status===`rolled_back`?`rolled_back`:`failed`;if(e.expiry?.state===`expired`||e.expiry?.state===`deletion_eligible`)return e.expiry.state;if(e.status===`suspended`)return`suspended`;if(e.launch_proof_status)return e.launch_proof_status;switch(e.status){case`ready`:case`running`:return`provisioned`;default:return`provisioning`}}function c(e){return e===`failed`||e===`rolled_back`||e===`destroyed`}function l(e){let t=document.createElement(`div`);return t.textContent=e,t.innerHTML}function u(){return`
    <div class="status-card pending">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">PAYMENT REQUIRED</span>
      </div>
      <div class="mt-4">
        <p class="text-text-soft">Your VM is reserved. Complete payment to begin provisioning.</p>
        <a href="/order" class="btn btn-primary mt-3">Pay now</a>
      </div>
    </div>
  `}function d(){return`
    <div class="status-card pending">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">PROVISIONING</span>
      </div>
      <div class="mt-4">
        <p class="text-text-soft">Building your VM. Most builds finish in under 60 seconds.</p>
        <div class="progress-bar"><div class="progress-fill"></div></div>
      </div>
    </div>
  `}function f(e){let t=e.hostname??`—`,n=e.ipv6??`—`,r=t===`—`?`—`:`ssh root@${t}`,i=e.resources?`${e.resources.vcpu}C / ${e.resources.ram_mb/1024}G RAM / ${e.resources.disk_gb}G SSD`:`—`;return`
    <div class="status-card ok">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">PROVISIONED</span>
      </div>
      <div class="kv-block mt-4">
        <div class="kv"><span class="k">hostname</span><span class="v"><code>${l(t)}</code></span><button class="copy" data-copy="${l(t)}">copy</button></div>
        <div class="kv"><span class="k">ipv6</span><span class="v"><code>${l(n)}</code></span><button class="copy" data-copy="${l(n)}">copy</button></div>
        <div class="kv"><span class="k">connect</span><span class="v"><code>${l(r)}</code></span><button class="copy" data-copy="${l(r)}">copy</button></div>
        <div class="kv"><span class="k">resources</span><span class="v"><code>${l(i)}</code></span></div>
      </div>
      ${o(e)}
    </div>
  `}function p(e){return`
    <div class="status-card error">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">FAILED</span>
      </div>
      <div class="mt-4">
        <p>${l(e.customer_message??`Something went wrong during provisioning.`)}</p>
        <p class="mt-2 text-text-soft">Contact <a href="mailto:support@hyrule.host">support@hyrule.host</a> for help.</p>
      </div>
    </div>
  `}function m(e){return`
    <div class="status-card error">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">ROLLED BACK</span>
      </div>
      <div class="mt-4">
        <p>${l(e.customer_message??`Your order has been rolled back and any payment will be refunded.`)}</p>
        <p class="mt-2 text-text-soft">Contact <a href="mailto:support@hyrule.host">support@hyrule.host</a> if you need assistance.</p>
      </div>
    </div>
  `}function h(e){let t=s(e);if(r(t)){let[r,,i]=n[t];return`<div class="status-card error"><div class="status-row"><span class="status-dot"></span><span class="status-label">${r}</span></div>
      <div class="mt-4"><p>${i}</p><p class="mt-2">VM status: ${l(e.status??`unknown`)}</p>
      ${o(e)}<p class="mt-2">Contact <a href="mailto:support@hyrule.host">support@hyrule.host</a> for help.</p></div></div>`}switch(t){case`payment_required`:return u();case`provisioned`:return f(e);case`failed`:return p(e);case`rolled_back`:return m(e);default:return d()}}function g(e){e.querySelectorAll(`[data-copy]`).forEach(e=>{e.addEventListener(`click`,()=>{let t=e.getAttribute(`data-copy`);if(t&&t!==`—`){navigator.clipboard.writeText(t);let n=e.textContent;e.textContent=`copied`,window.setTimeout(()=>{e.textContent===`copied`&&(e.textContent=n)},2e3)}})})}function _(n){let r=n.getAttribute(`data-vm-id`)??``;if(!r)return()=>{};let a=!1,o=null,u=e;async function d(){if(!a){try{let o=await fetch(`/api/v1/vm/${encodeURIComponent(r)}/status`);if(a)return;if(o.ok){let a=await o.json(),d=document.createElement(`div`);d.innerHTML=h(a).trim();let p=s(a),m=document.querySelector(`[data-status-title]`),_=document.querySelector(`[data-status-blurb]`),v=document.querySelector(`#status-connections`);v&&(v.hidden=p!==`provisioned`,v.style.display=p===`provisioned`?``:`none`,v.innerHTML=p===`provisioned`?`
            <div class="terminal">
              <div class="terminal-bar"><span class="terminal-title">SSH</span><span class="terminal-tag">online</span></div>
              <div class="terminal-body">
                <div class="t-line"><span class="prompt">$</span><span class="output">ssh root@${l(a.hostname??``)}</span></div>
                <div class="t-line"><span class="prompt">✓</span><span class="output">authenticating with your public key</span></div>
              </div>
            </div>
            <div class="mini-card p-[18px]">
              <h4>Management</h4>
              <p>Lifecycle mutations require the save-once management URL or an account that owns this VM. The public status URL intentionally cannot reboot, extend, snapshot, or destroy it.</p>
            </div>`:``);let[y,b]=i(p);m&&(m.textContent=y),_&&(_.textContent=b);let x=document.querySelector(`[data-status-step]`);if(x){x.textContent=p===`provisioned`?`running`:p===`payment_required`?`payment`:p===`accepted`?`provisioning`:p.replaceAll(`_`,` `);let e=x.closest(`.stp`),t=p!==`deleting`&&p!==`provisioning`&&p!==`accepted`&&p!==`payment_required`;e?.classList.toggle(`done`,t),e?.classList.toggle(`active`,!t);let n=e?.querySelector(`.num`);n&&(n.textContent=t?`✓`:`4`)}let S=d.firstElementChild;if(S instanceof HTMLElement&&(S.id=`status-card`,S.dataset.vmId=r,S.dataset.status=p,n.replaceWith(S),n=S),g(n),c(p)){f();return}u=p===`provisioning`||p===`accepted`||p===`payment_required`?e:t}}catch(e){console.error(`status poll failed`,e)}o=window.setTimeout(()=>void d(),u)}}function f(){a=!0,o!==null&&(window.clearTimeout(o),o=null)}return d(),f}function v(){let e=document.querySelector(`#management-access`);if(!e)return;let t=e.dataset.vmId??``,n=e.dataset.managementToken??``;if(!n&&t)try{let e=JSON.parse(sessionStorage.getItem(`hyr_vm_mgmt:${t}`)??`null`);e?.token?.startsWith(`hyr_vm_`)&&(n=e.token)}catch{n=``}n&&!e.querySelector(`.management-card`)&&(e.innerHTML=`
      <div class="mini-card management-card">
        <span class="panel-label">Save once</span>
        <h3>VM management token</h3>
        <p>This credential is required to reboot, extend, inspect, or destroy an order that is not attached to an account. Save it now.</p>
        <div class="credential-row">
          <code id="mgmt-token">${l(n)}</code>
          <button type="button" class="btn btn-secondary btn-xs" data-copy="${l(n)}">Copy</button>
          <a class="btn btn-ghost btn-xs" href="data:text/plain;charset=utf-8,${encodeURIComponent(n)}" download="hyrule-${l(t)}-management-token.txt">Download .txt</a>
        </div>
      </div>`),g(e)}var y=document.querySelector(`#status-card`);y&&_(y),v();