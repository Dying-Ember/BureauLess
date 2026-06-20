import { app, BrowserWindow, dialog, ipcMain } from 'electron';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function createWindow() {
  const window = new BrowserWindow({
    height: 980,
    minHeight: 720,
    minWidth: 1100,
    show: false,
    title: 'BureauLess',
    width: 1440,
    webPreferences: {
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  window.once('ready-to-show', () => window.show());

  const devUrl = process.env.BUREAULESS_WEB_URL ?? 'http://127.0.0.1:5173';
  if (process.env.NODE_ENV === 'production') {
    await window.loadFile(path.resolve(__dirname, '../../web/dist/index.html'));
  } else {
    await window.loadURL(devUrl);
  }
}

ipcMain.handle('dialog:openDag', async () => {
  const result = await dialog.showOpenDialog({
    filters: [{ name: 'YAML DAG', extensions: ['yaml', 'yml'] }],
    properties: ['openFile'],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('dialog:openRunsDir', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openDirectory'],
  });
  return result.canceled ? null : result.filePaths[0];
});

app.whenReady().then(createWindow);
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    void createWindow();
  }
});
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
