const {contextBridge, ipcRenderer} = require('electron');
contextBridge.exposeInMainWorld('jevDesktop', {
  setBounds: bounds => ipcRenderer.send('browser:bounds', bounds),
  navigate: url => ipcRenderer.invoke('browser:navigate', url),
  control: action => ipcRenderer.invoke('browser:control', action),
  state: () => ipcRenderer.invoke('browser:state'),
  onState: callback => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on('browser:state', listener);
    return () => ipcRenderer.removeListener('browser:state', listener);
  }
});
