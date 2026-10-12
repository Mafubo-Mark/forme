(() => {
'use strict';
const page=document.body.dataset.page, $=s=>document.querySelector(s);
const t=(en,zh)=>window.FormeI18n?.locale==='zh-Hant'?zh:en;
const e=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const messages={INVALID_CREDENTIALS:['Email/account or password is incorrect.','郵箱／帳號或密碼不正確。'],EMAIL_OR_USERNAME_EXISTS:['Email or account already exists.','郵箱或帳號已被註冊。'],PASSWORD_TOO_SHORT:['Use at least 8 characters.','密碼至少需要 8 個字元。'],INVALID_EMAIL:['Enter a valid email address.','請輸入有效郵箱。'],INVALID_USERNAME:['Use 3–40 letters, numbers, underscores or Chinese characters.','帳號需為 3–40 個字母、數字、底線或中文字。'],TOO_MANY_ATTEMPTS:['Too many attempts. Please try later.','嘗試次數過多，請稍後重試。'],DESIGN_NOT_READY_FOR_ORDER:['Your design needs approval and a quote first.','設計需先獲批並確認報價。'],INVALID_PROOF_CONTENT:['Use a JPG, PNG, WebP or PDF receipt.','請使用 JPG、PNG、WebP 或 PDF 憑證。']};
const readable=err=>messages[err.message]?t(...messages[err.message]):t('Unable to save. Please retry.','儲存失敗，請重試。')+` (${err.message})`;
const api=async(path,options={})=>{const response=await fetch(path,{credentials:'same-origin',cache:'no-store',...options});const data=await response.json().catch(()=>({}));if(!response.ok){if(response.status===401&&page!=='login'&&page!=='register')location.assign('login.html?next='+page+'.html');throw Error(data.detail?.code||`HTTP ${response.status}`);}return data;};
const post=(path,data,method='POST')=>api(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
$('.menu-toggle')?.addEventListener('click',event=>{const open=$('.nav-links').classList.toggle('open');event.currentTarget.setAttribute('aria-expanded',String(open));});
if(page==='home'){
 const model=$('.hero-model'),motion=matchMedia('(prefers-reduced-motion: reduce)');let visible=true;
 const update=()=>model?.toggleAttribute('auto-rotate',visible&&!motion.matches);motion.addEventListener?.('change',update);
 if(model&&'IntersectionObserver'in window)new IntersectionObserver(([entry])=>{visible=entry.isIntersecting;update();},{threshold:.1}).observe(model);else update();
}
if(page==='login'||page==='register'){
 const register=page==='register',form=$('#login-form');
 form.addEventListener('submit',async event=>{event.preventDefault();const error=$('#login-error'),button=form.querySelector('button[type=submit]');error.hidden=true;button.disabled=true;
 try{const d=Object.fromEntries(new FormData(form));if(register&&d.password!==d.confirm_password)throw Error(t('Passwords do not match.','兩次密碼不一致。'));await post('/api/customer/'+(register?'register':'login'),d);const next=new URLSearchParams(location.search).get('next');location.assign(next&&/^[a-z-]+\.html$/.test(next)?next:'account.html');}
 catch(err){error.textContent=readable(err);error.hidden=false;}finally{button.disabled=false;}});
}
if(page==='account'){
 const host=$('#account-content');
 api('/api/customer/session').then(async result=>{const user=result.user,designs=await api('/api/customer/submissions'),orders=await api('/api/customer/orders');
 host.innerHTML=`<div class="account-card"><h2>${e(user.username)}</h2><p>${e(user.email)}</p><p>${designs.items.length} ${t('designs','個設計')} · ${orders.items.length} ${t('orders','筆訂單')}</p><form id="profile-form"><label>${t('Name','姓名')}<input name="full_name" maxlength="120" value="${e(user.full_name)}"></label><label>${t('Phone','電話')}<input name="phone" maxlength="40" value="${e(user.phone)}"></label><button class="button button-dark" type="submit">${t('Save profile','儲存資料')}</button><p id="profile-message" role="status"></p></form><p><a href="prosthetic.html">${t('View your designs','查看設計紀錄')}</a> · <a href="order.html">${t('View orders','查看訂單')}</a></p><button id="sign-out" type="button">${t('Sign out','登出')}</button></div>`;
 $('#profile-form').onsubmit=async event=>{event.preventDefault();try{await post('/api/customer/profile',Object.fromEntries(new FormData(event.currentTarget)),'PATCH');$('#profile-message').textContent=t('Saved.','已儲存。');}catch(err){$('#profile-message').textContent=readable(err);}};
 $('#sign-out').onclick=async()=>{await api('/api/customer/logout',{method:'POST'});location.assign('index.html');};
 }).catch(err=>{host.innerHTML=`<div class="empty-state"><p>${e(readable(err))}</p><a href="login.html">${t('Sign in','登入')}</a></div>`;});
}
const statuses={placed:['Placed','已下單'],modeling:['Modeling','建模中'],printing:['In production','製作中'],shipped:['Shipped','已寄出'],delivered:['Delivered','已送達'],cancelled:['Cancelled','已取消'],pending:['Pending','待處理'],submitted:['Awaiting payment review','付款待審核'],paid:['Payment confirmed','付款已確認'],confirmed:['Confirmed','已確認'],rejected:['Rejected','已拒絕'],preparing:['Preparing','準備中']};
const label=x=>statuses[x]?t(...statuses[x]):x;
function orderCard(order){const d=order.delivery||{},canPay=order.payment_status!=='paid'&&order.order_status!=='cancelled';return `<article class="account-card order-card" data-order="${e(order.id)}"><h2>${e(order.order_number)}</h2><p>HK$ ${e(order.amount_hkd)} · ${e(label(order.order_status))} · ${e(label(order.payment_status))}</p><p>${e(d.recipient_name)} · ${e(d.recipient_phone)}<br>${e(d.region)} ${e(d.district)} ${e(d.address_line)}</p><p>${t('Carrier / tracking','物流／追蹤號')}：${e(d.carrier||'—')} / ${e(d.tracking_number||'—')}</p>${d.confirmed_at?`<p>${t('Receipt confirmed','已確認收貨')}：${e(d.confirmed_at)}</p>`:''}${['shipped','delivered'].includes(order.order_status)&&!d.confirmed_at?`<button class="button button-dark confirm-receipt" type="button">${t('Confirm receipt','確認收貨')}</button>`:''}<details><summary>${t('Payment history','付款紀錄')} (${order.payments.length})</summary>${order.payments.map(p=>`<p>${e(p.method)} · ${e(p.reference)} · ${e(label(p.status))} ${p.proof_url?`<a href="${e(p.proof_url)}">${t('Download proof','下載憑證')}</a>`:''}<br>${e(p.review_note||'')}</p>`).join('')}</details>${canPay?`<form class="payment-form"><h3>${t('Submit payment proof','提交付款憑證')}</h3><p>${t('Pay only using instructions confirmed directly by Forme. Uploading a receipt does not charge your account.','請按 Forme 確認的收款資料付款。上傳憑證不會自動扣款。')}</p><label>${t('Payment method','付款方式')}<input name="method" placeholder="FPS / Bank transfer" maxlength="80" required></label><label>${t('Transaction reference','交易參考編號')}<input name="reference" maxlength="120" required></label><label>${t('Receipt (image / PDF, max 20 MB)','憑證（圖片／PDF，最大 20 MB）')}<input name="proof" type="file" accept="image/jpeg,image/png,image/webp,application/pdf" required></label><button class="button button-dark" type="submit">${t('Submit for review','提交審核')}</button></form>`:''}<p class="order-message" role="status"></p></article>`;}
if(page==='order'||page==='delivery'){
 const host=page==='order'?$('#order-list'):$('#delivery-list');
 async function load(){try{const result=await api('/api/customer/orders');host.innerHTML=result.items.length?result.items.map(orderCard).join(''):`<div class="empty-state"><h2>${t('No orders yet','尚未有訂單')}</h2><p>${t('Order from an approved design after your quote is confirmed.','設計獲批並確認報價後即可下單。')}</p><a href="prosthetic.html">${t('View designs','查看設計')}</a></div>`;
 host.querySelectorAll('.order-card').forEach(card=>{const id=card.dataset.order;
 card.querySelector('.confirm-receipt')?.addEventListener('click',async event=>{event.currentTarget.disabled=true;try{await api(`/api/customer/orders/${id}/confirm-receipt`,{method:'POST'});await load();}catch(err){card.querySelector('.order-message').textContent=readable(err);event.currentTarget.disabled=false;}});
 card.querySelector('.payment-form')?.addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,button=form.querySelector('button'),file=form.elements.proof.files[0];button.disabled=true;try{if(!file||file.size>20*1024**2)throw Error('INVALID_PROOF_CONTENT');const result=await post(`/api/customer/orders/${id}/payments`,{method:form.elements.method.value,reference:form.elements.reference.value});await api(`/api/customer/payments/${result.paymentId}/proof`,{method:'PUT',headers:{'Content-Type':file.type||'application/octet-stream','X-File-Name':encodeURIComponent(file.name)},body:file});await load();}catch(err){card.querySelector('.order-message').textContent=readable(err);button.disabled=false;}});
 });}catch(err){host.textContent=readable(err);}}
 load();
}
if(page==='checkout'){
 const host=$('.checkout-grid'),id=new URLSearchParams(location.search).get('design');
 if(!id){host.innerHTML=`<div class="empty-state"><a href="prosthetic.html">${t('Choose a reviewed design first','請先選擇已審核設計')}</a></div>`;return;}
 api('/api/customer/submissions/'+encodeURIComponent(id)).then(design=>{
 if(design.status!=='ready'||!design.quote_hkd)throw Error('DESIGN_NOT_READY_FOR_ORDER');
 $('.page-heading h1').textContent=t('Place your order.','提交訂單。');$('.page-heading p').textContent=t('Confirm your quote and delivery details.','確認報價與收件資料。');
 host.innerHTML=`<div class="account-card"><h2>${t('Design','設計')} ${e(design.id.slice(0,8))}</h2><p>${e(design.material)} · ${e(design.color)}</p><strong>HK$ ${e(design.quote_hkd)}</strong><p>${t('Payment is submitted separately for manual review.','下單後另行提交付款憑證，由管理員審核。')}</p><form id="checkout-form">${[['recipient_name',t('Recipient','收件人'),120],['recipient_phone',t('Phone','電話'),40],['region',t('Region','地區'),100],['district',t('District / city','區域／城市'),100],['address_line',t('Delivery address','收件地址'),500]].map(([key,title,size])=>`<label>${title}<input name="${key}" maxlength="${size}" required></label>`).join('')}<label>${t('Delivery note','配送備註')}<textarea name="delivery_note" maxlength="1000"></textarea></label><button class="button button-dark" type="submit">${t('Create order','建立訂單')}</button><p id="checkout-error" role="alert"></p></form></div>`;
 $('#checkout-form').onsubmit=async event=>{event.preventDefault();const form=event.currentTarget,button=form.querySelector('button');button.disabled=true;try{await post('/api/customer/orders',{...Object.fromEntries(new FormData(form)),submission_id:id});location.assign('order.html');}catch(err){$('#checkout-error').textContent=readable(err);button.disabled=false;}};
 }).catch(err=>{host.textContent=readable(err);});
}
})();
