var e=2e3;function t(e){let t=document.createElement(`div`);return t.textContent=e,t.innerHTML}function n(){return`
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
  `}function r(){return`
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
  `}function i(e){let n=e.fqdn??`—`,r=e.ipv6??`—`,i=n===`—`?`—`:`ssh root@${n}`,a=e.resources?`${e.resources.vcpu}C / ${e.resources.ram_mb/1024}G RAM / ${e.resources.disk_gb}G SSD`:`—`;return`
    <div class="status-card ok">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">PROVISIONED</span>
      </div>
      <div class="kv-block mt-4">
        <div class="kv"><span class="k">hostname</span><span class="v"><code>${t(n)}</code></span><button class="copy" data-copy="${t(n)}">copy</button></div>
        <div class="kv"><span class="k">ipv6</span><span class="v"><code>${t(r)}</code></span><button class="copy" data-copy="${t(r)}">copy</button></div>
        <div class="kv"><span class="k">connect</span><span class="v"><code>${t(i)}</code></span><button class="copy" data-copy="${t(i)}">copy</button></div>
        <div class="kv"><span class="k">resources</span><span class="v"><code>${t(a)}</code></span></div>
      </div>
    </div>
  `}function a(e){return`
    <div class="status-card error">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">FAILED</span>
      </div>
      <div class="mt-4">
        <p>${t(e.customer_message??`Something went wrong during provisioning.`)}</p>
        <p class="mt-2 text-text-soft">Contact <a href="mailto:support@hyrule.host">support@hyrule.host</a> for help.</p>
      </div>
    </div>
  `}function o(e){return`
    <div class="status-card error">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">ROLLED BACK</span>
      </div>
      <div class="mt-4">
        <p>${t(e.customer_message??`Your order has been rolled back and any payment will be refunded.`)}</p>
        <p class="mt-2 text-text-soft">Contact <a href="mailto:support@hyrule.host">support@hyrule.host</a> if you need assistance.</p>
      </div>
    </div>
  `}function s(e){switch(e.status){case`payment_required`:return n();case`provisioning`:return r();case`provisioned`:return i(e);case`failed`:return a(e);case`rolled_back`:return o(e);default:return r()}}function c(e){e.querySelectorAll(`[data-copy]`).forEach(e=>{e.addEventListener(`click`,()=>{let t=e.getAttribute(`data-copy`);if(t&&t!==`—`){navigator.clipboard.writeText(t);let n=e.textContent;e.textContent=`copied`,window.setTimeout(()=>{e.textContent===`copied`&&(e.textContent=n)},2e3)}})})}function l(t){let n=t.getAttribute(`data-vm-id`)??``;if(!n)return()=>{};let r=!1,i=null;async function a(){if(!r){try{let e=await fetch(`/api/v1/vm/${encodeURIComponent(n)}/status`);if(e.ok){let r=await e.json(),i=document.createElement(`div`);i.innerHTML=s(r).trim();let a=i.firstElementChild;if(a instanceof HTMLElement&&(a.id=`status-card`,a.dataset.vmId=n,a.dataset.status=r.status,t.replaceWith(a),t=a),c(t),r.status===`provisioned`||r.status===`failed`||r.status===`rolled_back`){o();return}}}catch(e){console.error(`status poll failed`,e)}i=window.setTimeout(()=>void a(),e)}}function o(){r=!0,i!==null&&(window.clearTimeout(i),i=null)}return a(),o}function u(){let e=document.querySelector(`#management-access`);if(!e)return;let n=e.dataset.vmId??``,r=e.dataset.managementUrl??``;if(!r&&n)try{let e=JSON.parse(sessionStorage.getItem(`hyr_vm_mgmt:${n}`)??`null`);e?.token?.startsWith(`hyr_vm_`)&&(r=e.url??`/api/v1/vm/${encodeURIComponent(n)}?token=${encodeURIComponent(e.token)}`)}catch{r=``}r&&!e.querySelector(`.management-card`)&&(e.innerHTML=`
      <div class="mini-card management-card">
        <span class="panel-label">Save once</span>
        <h3>VM management URL</h3>
        <p>This credential is required to reboot, extend, inspect, or destroy an order that is not attached to an account. Save it now.</p>
        <div class="credential-row">
          <code id="mgmt-url">${t(r)}</code>
          <button type="button" class="btn btn-secondary btn-xs" data-copy="${t(r)}">Copy</button>
          <a class="btn btn-ghost btn-xs" href="data:text/plain;charset=utf-8,${encodeURIComponent(r)}" download="hyrule-${t(n)}-management-url.txt">Download .txt</a>
        </div>
      </div>`),c(e)}var d=document.querySelector(`#status-card`);d&&l(d),u();