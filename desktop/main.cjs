const {app, BaseWindow, WebContentsView, ipcMain, dialog} = require('electron');
const {spawn} = require('node:child_process');
const {join, resolve} = require('node:path');
const {createServer} = require('node:net');
const {mkdirSync, writeFileSync, unlinkSync, existsSync} = require('node:fs');

const root = resolve(__dirname, '..');
const runtime = join(root, '.runtime');
mkdirSync(runtime, {recursive: true});
app.setName('Jev Browser');
app.setPath('userData', process.env.JEV_DESKTOP_PROFILE || join(runtime, 'electron-profile'));
// Port zero lets Chromium choose a free debugging port on loopback.
app.commandLine.appendSwitch('remote-debugging-address', '127.0.0.1');
app.commandLine.appendSwitch('remote-debugging-port', '0');
let window, ui, website, backend, origin, closing = false, loadError = '';

function webUrl(value) {
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw Error('Enter an http(s) website address.');
  return url.href;
}
function trusted(event) {
  if (event.sender !== ui?.webContents || !event.senderFrame || event.senderFrame.url !== origin + '/') throw Error('Untrusted desktop command.');
}
function state() {
  return {url: website.webContents.getURL(), title: website.webContents.getTitle(), loading: website.webContents.isLoading(), error: loadError};
}
function publish() {
  if (ui && !ui.webContents.isDestroyed()) ui.webContents.send('browser:state', state());
}
async function freePort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {const port = server.address().port; server.close(() => resolvePort(port));});
  });
}
async function waitForBackend() {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (backend.exitCode !== null) throw Error('The Python backend exited before it was ready. Check .venv and the project dependencies.');
    try {if ((await fetch(origin + '/api/agent/config')).ok) return;} catch {}
    await new Promise(resolveWait => setTimeout(resolveWait, 150));
  }
  throw Error('The Python backend did not become ready.');
}
async function cdpEndpoint() {
  const {readFile} = require('node:fs/promises');
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      const [port] = (await readFile(join(app.getPath('userData'), 'DevToolsActivePort'), 'utf8')).trim().split('\n');
      if (/^\d+$/.test(port)) return `http://127.0.0.1:${port}`;
    } catch {}
    await new Promise(resolveWait => setTimeout(resolveWait, 100));
  }
  throw Error('The embedded browser did not expose its local control connection.');
}

async function boot() {
  window = new BaseWindow({width:1450,height:960,minWidth:1080,minHeight:700,title:'Jev Browser',backgroundColor:'#f7f7f2',show:false});
  ui = new WebContentsView({webPreferences:{preload:join(__dirname,'preload.cjs'),contextIsolation:true,sandbox:true,nodeIntegration:false,webviewTag:false}});
  website = new WebContentsView({webPreferences:{partition:'persist:jev-web',contextIsolation:true,sandbox:true,nodeIntegration:false,webviewTag:false}});
  window.contentView.addChildView(ui);
  window.contentView.addChildView(website);
  website.setVisible(false);
  const resize = () => {const {width,height}=window.getContentBounds(); ui.setBounds({x:0,y:0,width,height});};
  resize(); window.on('resize',resize);
  const wc=website.webContents;
  wc.session.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false));
  wc.session.on('will-download',event=>event.preventDefault());
  wc.on('will-navigate',(event,url)=>{try{webUrl(url);}catch{event.preventDefault();}});
  wc.on('will-redirect',(event,url)=>{try{webUrl(url);}catch{event.preventDefault();}});
  wc.setWindowOpenHandler(({url})=>{try{void wc.loadURL(webUrl(url)).catch(()=>{});}catch{} return {action:'deny'};});
  ui.webContents.setWindowOpenHandler(({url})=>{try{void wc.loadURL(webUrl(url)).catch(()=>{});}catch{} return {action:'deny'};});
  ui.webContents.on('will-navigate',(event,url)=>{if(url!==origin+'/')event.preventDefault();});
  for (const event of ['did-navigate','did-navigate-in-page','page-title-updated','did-stop-loading']) wc.on(event,publish);
  wc.on('did-start-loading',()=>{loadError='';publish();});
  wc.on('did-fail-load',(_event,code,description,_url,isMainFrame)=>{if(isMainFrame&&code!==-3){loadError=`The website could not load (${description}). Try another address or reload.`;publish();}});
  await wc.loadURL('about:blank');
  wc.debugger.attach('1.3');
  const {targetInfo}=await wc.debugger.sendCommand('Target.getTargetInfo');
  wc.debugger.detach();
  const endpoint=await cdpEndpoint();
  const port=await freePort();
  origin=`http://127.0.0.1:${port}`;
  const python=process.env.JEV_PYTHON || join(root,'.venv','bin','python');
  if(!existsSync(python))throw Error('Create the Python .venv and install requirements.lock before starting the desktop app.');
  backend=spawn(python,['-m','jev_lab'],{cwd:root,env:{...process.env,PORT:String(port),JEV_CDP_ENDPOINT:endpoint,JEV_BROWSER_TARGET_ID:targetInfo.targetId},stdio:['ignore','pipe','pipe']});
  backend.stdout.on('data',chunk=>process.stdout.write(chunk));
  backend.stderr.on('data',chunk=>process.stderr.write(chunk));
  backend.on('error',()=>{if(!closing)dialog.showErrorBox('Jev Browser','The Python backend could not start.');});
  backend.on('exit',()=>{if(!closing){void dialog.showMessageBox({type:'error',message:'The Python backend stopped. Restart Jev Browser to continue.'});}});
  await waitForBackend();
  // Local diagnostics only; no API keys are written here.
  writeFileSync(join(runtime,'desktop.json'),JSON.stringify({pid:process.pid,origin,cdpEndpoint:endpoint,browserTargetId:targetInfo.targetId}),{mode:0o600});
  ipcMain.on('browser:bounds',(event,bounds)=>{
    try{trusted(event);}catch{return;}
    if(!bounds || !['x','y','width','height'].every(key=>Number.isFinite(bounds[key])))return;
    const size=window.getContentBounds();
    const x=Math.max(0,Math.min(size.width,Math.round(bounds.x))),y=Math.max(0,Math.min(size.height,Math.round(bounds.y)));
    const width=Math.max(0,Math.min(size.width-x,Math.round(bounds.width))),height=Math.max(0,Math.min(size.height-y,Math.round(bounds.height)));
    website.setVisible(bounds.visible!==false && width>0 && height>0);
    website.setBounds({x,y,width,height});
  });
  ipcMain.handle('browser:state',event=>{trusted(event);return state();});
  ipcMain.handle('browser:navigate',async(event,url)=>{trusted(event);await wc.loadURL(webUrl(url));return state();});
  ipcMain.handle('browser:control',(event,action)=>{
    trusted(event);
    if(action==='back'&&wc.navigationHistory.canGoBack())wc.navigationHistory.goBack();
    else if(action==='forward'&&wc.navigationHistory.canGoForward())wc.navigationHistory.goForward();
    else if(action==='reload')wc.reload();
    else if(action==='focus'){window.show();wc.focus();}
    else if(!['back','forward'].includes(action))throw Error('Unsupported browser control.');
    return state();
  });
  await ui.webContents.loadURL(origin+'/');
  window.show();
  window.on('closed',()=>{
    closing=true;
    if(backend&&backend.exitCode===null)backend.kill('SIGINT');
    if(!ui.webContents.isDestroyed())ui.webContents.close();
    if(!wc.isDestroyed())wc.close();
    app.quit();
  });
}
app.on('before-quit',()=>{closing=true;if(backend&&backend.exitCode===null)backend.kill('SIGINT');try{unlinkSync(join(runtime,'desktop.json'));}catch{}});
app.on('window-all-closed',()=>app.quit());
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance',()=>{window?.show();window?.focus();});
  app.whenReady().then(boot).catch(error=>{dialog.showErrorBox('Jev Browser',error.message);app.quit();});
}
