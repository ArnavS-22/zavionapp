const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('api', {
  // Backend now runs automatically, no manual control needed
  
  // CLI tracking control
  startCliTracking: () => ipcRenderer.invoke('start-cli-tracking'),
  stopCliTracking: () => ipcRenderer.invoke('stop-cli-tracking'),
  getCliStatus: () => ipcRenderer.invoke('get-cli-status'),
  
  // CLI status updates
  onCliStatus: (callback) => {
    ipcRenderer.on('cli-status', (event, data) => callback(data));
  },
  
  // Remove listeners
  removeAllListeners: (channel) => {
    ipcRenderer.removeAllListeners(channel);
  }
});
