var e=2e3;function t(e){if(e.launch_proof_status)return e.launch_proof_status;switch(e.status){case`ready`:case`running`:case`suspended`:return`provisioned`;case`failed`:case`destroyed`:return`failed`;default:return`provisioning`}}function n(e){return e===`provisioned`||e===`failed`||e===`rolled_back`}function r(e){let t=document.createElement(`div`);return t.textContent=e,t.innerHTML}function i(){return`
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
  `}function a(){return`
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
  `}function o(e){let t=e.hostname??`—`,n=e.ipv6??`—`,i=t===`—`?`—`:`ssh root@${t}`,a=e.resources?`${e.resources.vcpu}C / ${e.resources.ram_mb/1024}G RAM / ${e.resources.disk_gb}G SSD`:`—`;return`
    <div class="status-card ok">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">PROVISIONED</span>
      </div>
      <div class="kv-block mt-4">
        <div class="kv"><span class="k">hostname</span><span class="v"><code>${r(t)}</code></span><button class="copy" data-copy="${r(t)}">copy</button></div>
        <div class="kv"><span class="k">ipv6</span><span class="v"><code>${r(n)}</code></span><button class="copy" data-copy="${r(n)}">copy</button></div>
        <div class="kv"><span class="k">connect</span><span class="v"><code>${r(i)}</code></span><button class="copy" data-copy="${r(i)}">copy</button></div>
        <div class="kv"><span class="k">resources</span><span class="v"><code>${r(a)}</code></span></div>
      </div>
    </div>
  `}function s(e){return`
    <div class="status-card error">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">FAILED</span>
      </div>
      <div class="mt-4">
        <p>${r(e.customer_message??`Something went wrong during provisioning.`)}</p>
        <p class="mt-2 text-text-soft">Contact <a href="mailto:support@hyrule.host">support@hyrule.host</a> for help.</p>
      </div>
    </div>
  `}function c(e){return`
    <div class="status-card error">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">ROLLED BACK</span>
      </div>
      <div class="mt-4">
        <p>${r(e.customer_message??`Your order has been rolled back and any payment will be refunded.`)}</p>
        <p class="mt-2 text-text-soft">Contact <a href="mailto:support@hyrule.host">support@hyrule.host</a> if you need assistance.</p>
      </div>
    </div>
  `}function l(e){switch(t(e)){case`payment_required`:return i();case`provisioned`:return o(e);case`failed`:return s(e);case`rolled_back`:return c(e);default:return a()}}function u(e){e.querySelectorAll(`[data-copy]`).forEach(e=>{e.addEventListener(`click`,()=>{let t=e.getAttribute(`data-copy`);if(t&&t!==`—`){navigator.clipboard.writeText(t);let n=e.textContent;e.textContent=`copied`,window.setTimeout(()=>{e.textContent===`copied`&&(e.textContent=n)},2e3)}})})}function d(r){let i=r.getAttribute(`data-vm-id`)??``;if(!i)return()=>{};let a=!1,o=null;async function s(){if(!a){try{let e=await fetch(`/api/v1/vm/${encodeURIComponent(i)}/status`);if(e.ok){let a=await e.json(),o=document.createElement(`div`);o.innerHTML=l(a).trim();let s=t(a),d=o.firstElementChild;if(d instanceof HTMLElement&&(d.id=`status-card`,d.dataset.vmId=i,d.dataset.status=s,r.replaceWith(d),r=d),u(r),n(s)){c();return}}}catch(e){console.error(`status poll failed`,e)}o=window.setTimeout(()=>void s(),e)}}function c(){a=!0,o!==null&&(window.clearTimeout(o),o=null)}return s(),c}function f(){let e=document.querySelector(`#management-access`);if(!e)return;let t=e.dataset.vmId??``,n=e.dataset.managementToken??``;if(!n&&t)try{let e=JSON.parse(sessionStorage.getItem(`hyr_vm_mgmt:${t}`)??`null`);e?.token?.startsWith(`hyr_vm_`)&&(n=e.token)}catch{n=``}n&&!e.querySelector(`.management-card`)&&(e.innerHTML=`
      <div class="mini-card management-card">
        <span class="panel-label">Save once</span>
        <h3>VM management token</h3>
        <p>This credential is required to reboot, extend, inspect, or destroy an order that is not attached to an account. Save it now.</p>
        <div class="credential-row">
          <code id="mgmt-token">${r(n)}</code>
          <button type="button" class="btn btn-secondary btn-xs" data-copy="${r(n)}">Copy</button>
          <a class="btn btn-ghost btn-xs" href="data:text/plain;charset=utf-8,${encodeURIComponent(n)}" download="hyrule-${r(t)}-management-token.txt">Download .txt</a>
        </div>
      </div>`),u(e)}var p=document.querySelector(`#status-card`);p&&d(p),f();