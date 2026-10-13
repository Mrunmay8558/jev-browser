// LCG-style intent-before-effect overlay. CSSOM styles work under strict page CSP
// without adding a style sheet or weakening the site's security policy.
(() => {
  if (window.__jevCursor) return;
  let host, root, pointer, caption;
  function ensure() {
    if (host?.isConnected) return;
    if (!document.documentElement) return;
    host=document.createElement('div');host.setAttribute('data-jev-overlay','');
    host.style.cssText='position:fixed;inset:0;z-index:2147483647;pointer-events:none';
    root=host.attachShadow({mode:'closed'});
    pointer=document.createElementNS('http://www.w3.org/2000/svg','svg');
    pointer.setAttribute('viewBox','0 0 20 26');pointer.setAttribute('width','24');pointer.setAttribute('height','30');
    pointer.style.cssText='position:fixed;width:24px;height:30px;left:24px;top:24px;filter:drop-shadow(0 2px 3px #0006);pointer-events:none';
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d','M2 2V21L7 16L12 25L16 23L11 14L19 13Z');path.setAttribute('fill','white');path.setAttribute('stroke','#133e32');path.setAttribute('stroke-width','2');pointer.append(path);
    caption=document.createElement('div');caption.textContent='Jev agent';
    caption.style.cssText='position:fixed;left:24px;top:24px;transform:translate(25px,20px);max-width:340px;padding:7px 11px;background:#133e32;color:white;border-radius:7px;font:13px/1.4 system-ui;pointer-events:none';
    if(!matchMedia('(prefers-reduced-motion: reduce)').matches){pointer.style.transition='left .28s,top .28s';caption.style.transition='left .28s,top .28s'}
    root.append(pointer,caption);document.documentElement.append(host);
  }
  window.__jevCursor={
    move(x,y,text){ensure();if(!pointer)return;for(const el of [pointer,caption]){el.style.left=x+'px';el.style.top=y+'px'}caption.textContent=text;host.style.display='block'},
    ring(x,y){ensure();const ring=document.createElement('div');ring.style.cssText=`position:fixed;width:32px;height:32px;left:${x}px;top:${y}px;border:3px solid #20b080;border-radius:50%;transform:translate(-50%,-50%);pointer-events:none`;root.append(ring);ring.animate([{opacity:1,scale:1},{opacity:0,scale:2}],{duration:500});setTimeout(()=>ring.remove(),550)},
    hide(){if(host)host.style.display='none'},
    bounds(){return pointer?{width:pointer.getBoundingClientRect().width,height:pointer.getBoundingClientRect().height}:null}
  };
})();
