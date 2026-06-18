import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('agentsSwarm', {
  openDag: () => ipcRenderer.invoke('dialog:openDag'),
  openRunsDir: () => ipcRenderer.invoke('dialog:openRunsDir'),
  platform: process.platform,
});
