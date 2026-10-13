() => {
  if (!window.__jevRefs) window.__jevRefs = {map:new WeakMap(),next:1,
    document:crypto.randomUUID?.() || Array.from(crypto.getRandomValues(new Uint32Array(4)),n=>n.toString(16)).join('-')};
  const registry=window.__jevRefs;
  const roots=[document];
  const nodes=[];
  for(let i=0;i<roots.length;i++){
    for(const el of roots[i].querySelectorAll('*')){
      if(el.hasAttribute('data-jev-overlay'))continue;
      if(el.shadowRoot)roots.push(el.shadowRoot);
      if(el.matches('a[href],button,input,select,textarea,[role="button"],[role="link"],[role="textbox"],[role="combobox"],[role="option"],[role="checkbox"],[contenteditable="true"]'))nodes.push(el);
    }
  }
  // Limit choices to this viewport, excluding controls hidden behind a dialog.
  const visible=el=>{
    const box=el.getBoundingClientRect(),style=getComputedStyle(el);
    return box.width>0 && box.height>0 && box.bottom>0 && box.right>0 && box.top<innerHeight && box.left<innerWidth
      && style.visibility!=='hidden' && style.display!=='none';
  };
  const reachable=el=>{
    const box=el.getBoundingClientRect();
    const x=(Math.max(0,box.left)+Math.min(innerWidth,box.right))/2;
    const y=(Math.max(0,box.top)+Math.min(innerHeight,box.bottom))/2;
    let hit=document.elementFromPoint(x,y);
    while(hit?.shadowRoot){const child=hit.shadowRoot.elementFromPoint(x,y);if(!child||child===hit)break;hit=child;}
    return hit===el || el.contains(hit);
  };
  const elements=[];
  let challenge='';
  const labelText=el=>{const node=el.labels?.[0];if(!node)return '';const copy=node.cloneNode(true);copy.querySelectorAll('input,select,textarea,button').forEach(child=>child.remove());return copy.textContent.trim()};
  for(const el of nodes){
    if(!visible(el)||!reachable(el)||el.disabled||el.getAttribute('aria-disabled')==='true'||el.type==='hidden')continue;
    const label=(el.getAttribute('aria-label')||labelText(el)||el.getAttribute('placeholder')||el.innerText||el.getAttribute('title')||el.getAttribute('name')||el.getAttribute('value')||el.tagName).trim().slice(0,220);
    const type=(el.type||'').toLowerCase();
    const sensitive=type==='password'||el.autocomplete==='one-time-code'||/password|passcode|\botp\b|verification code|card number|cvv|cvc/i.test(label);
    if(sensitive)challenge='Please complete the login, verification, or payment details in the browser, then resume.';
    if(!registry.map.has(el))registry.map.set(el,'e'+registry.next++);
    const ref=registry.map.get(el);el.setAttribute('data-jev-ref',ref);
    elements.push({ref,tag:el.tagName.toLowerCase(),role:el.getAttribute('role')||'',label,type,sensitive,editable:!el.readOnly,
      value:sensitive?'':String(el.value??'').slice(0,400),href:el.tagName==='A'?el.href:'',
      options:el.tagName==='SELECT'?Array.from(el.options).map(o=>({value:o.value,label:o.text})).slice(0,100):[]});
    if(elements.length>=120)break;
  }
  if(Array.from(document.querySelectorAll('iframe')).some(el=>visible(el)&&/captcha|recaptcha|hcaptcha/i.test(el.src+' '+el.title)))challenge='Complete the CAPTCHA in the browser, then resume.';
  const text=(document.body?.innerText||'').slice(0,18000);
  if(/verify (that )?you are human|checking your browser|complete the captcha/i.test(text))challenge='Complete the website verification in the browser, then resume.';
  return {url:location.href,title:document.title,text,elements,document:registry.document,challenge};
}
