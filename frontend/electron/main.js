const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');

let mainWindow;
let pythonProcess = null;
let cliProcess = null;
let isBackendRunning = false;
let isCliRunning = false;

// Path to Python backend
const getBackendPath = () => {
  if (app.isPackaged) {
    // In packaged app, use resources
    return path.join(process.resourcesPath, 'controller.py');
  } else {
    // In development, use relative path
    return path.join(__dirname, '..', '..', 'controller.py');
  }
};

// Path to Python executable
const getPythonPath = () => {
  if (app.isPackaged) {
    // In packaged app, use bundled Python
    return path.join(process.resourcesPath, 'python', 'python.exe');
  } else {
    // In development, use system Python
    return 'python';
  }
};

// Spawn Python backend process
function startBackend() {
  if (isBackendRunning) {
    console.log('Backend already running');
    return;
  }

  try {
    const backendPath = getBackendPath();
    const pythonPath = getPythonPath();
    
    console.log(`Starting backend with: ${pythonPath} ${backendPath}`);
    
    // Check if backend file exists
    if (!fs.existsSync(backendPath)) {
      console.error(`Backend file not found: ${backendPath}`);
      return;
    }

    // Check if port 8000 is already in use
    const net = require('net');
    const server = net.createServer();
    server.listen(8000, () => {
      server.close();
      // Port is available, proceed with starting backend
      spawnBackendProcess();
    });
    
    server.on('error', (err) => {
      if (err.code === 'EADDRINUSE') {
        console.log('Port 8000 is already in use, backend may already be running');
        isBackendRunning = true;
        return;
      }
    });

    function spawnBackendProcess() {
      // Spawn Python process
      pythonProcess = spawn(pythonPath, [backendPath], {
        stdio: ['pipe', 'pipe', 'pipe'],
        detached: false,
        shell: true
      });

      // Handle process events
      pythonProcess.stdout.on('data', (data) => {
        console.log(`Backend stdout: ${data}`);
        if (data.toString().includes('Uvicorn running on') || data.toString().includes('INFO:     Started server process')) {
          isBackendRunning = true;
          console.log('Backend started successfully');
        }
      });

      pythonProcess.stderr.on('data', (data) => {
        console.error(`Backend stderr: ${data}`);
        // Look for FastAPI server startup messages
        if (data.toString().includes('INFO:     Started server process') || 
            data.toString().includes('INFO:     Uvicorn running on') ||
            data.toString().includes('INFO:     Application startup complete')) {
          isBackendRunning = true;
          console.log('Backend started successfully');
        }
        if (data.toString().includes('Address already in use')) {
          console.log('Port already in use, backend may already be running');
          isBackendRunning = true;
        }
      });

      pythonProcess.on('error', (error) => {
        console.error('Failed to start backend:', error);
      });

      pythonProcess.on('close', (code) => {
        console.log(`Backend process exited with code ${code}`);
        isBackendRunning = false;
        pythonProcess = null;
      });

      // Wait a bit to see if process starts successfully
      setTimeout(async () => {
        if (!isBackendRunning) {
          console.log('Backend startup timeout, checking if running...');
          // Add health check
          const isHealthy = await checkBackendHealth();
          if (isHealthy) {
            isBackendRunning = true;
            console.log('Backend health check passed');
          }
        }
      }, 3000);
    }

  } catch (error) {
    console.error('Error starting backend:', error);
  }
}

// Start CLI tracking process
function startCliTracking() {
  if (isCliRunning) {
    console.log('CLI tracking already running');
    return;
  }

  try {
    console.log('Starting CLI tracking...');
    
    // Get the correct working directory for CLI
    const cliWorkingDir = path.join(__dirname, '..', '..'); // Go up to gum root directory
    
    // Spawn CLI process with correct working directory
    cliProcess = spawn(`python -m gum.cli --user-name "Arnav Sharma" --model gpt-4o-mini`, {
      stdio: ['pipe', 'pipe', 'pipe'],
      detached: false,
      shell: true,
      cwd: cliWorkingDir // Set working directory to where gum module is located
    });

    // Handle CLI process events
    cliProcess.stdout.on('data', (data) => {
      console.log(`CLI stdout: ${data}`);
      const output = data.toString();
      
      // Look for CLI startup success messages
      if (output.includes('Monitoring started') || 
          output.includes('GUM CLI initialized') ||
          output.includes('Starting monitoring') ||
          output.includes('Behavior tracking active') ||
          output.includes('GUM CLI') ||
          output.includes('Starting')) {
        isCliRunning = true;
        console.log('CLI tracking started successfully');
        if (mainWindow && mainWindow.webContents) {
          mainWindow.webContents.send('cli-status', { running: true, message: 'Tracking started' });
        }
      }
    });

    cliProcess.stderr.on('data', (data) => {
      console.error(`CLI stderr: ${data}`);
      const output = data.toString();
      
      // Look for CLI startup success messages in stderr too
      if (output.includes('Monitoring started') || 
          output.includes('GUM CLI initialized') ||
          output.includes('Starting monitoring') ||
          output.includes('Behavior tracking active') ||
          output.includes('GUM CLI') ||
          output.includes('Starting')) {
        isCliRunning = true;
        console.log('CLI tracking started successfully');
        if (mainWindow && mainWindow.webContents) {
          mainWindow.webContents.send('cli-status', { running: true, message: 'Tracking started' });
        }
      }
      
      // Check for specific error messages
      if (output.includes('ModuleNotFoundError') || output.includes('No module named')) {
        console.error('CLI module not found - check working directory');
        if (mainWindow && mainWindow.webContents) {
          mainWindow.webContents.send('cli-status', { running: false, message: 'Module not found - check paths' });
        }
      }
    });

    cliProcess.on('error', (error) => {
      console.error('Failed to start CLI tracking:', error);
      if (mainWindow && mainWindow.webContents) {
        mainWindow.webContents.send('cli-status', { running: false, message: `Failed: ${error.message}` });
      }
    });

    cliProcess.on('close', (code) => {
      console.log(`CLI process exited with code ${code}`);
      isCliRunning = false;
      cliProcess = null;
      if (mainWindow && mainWindow.webContents) {
        mainWindow.webContents.send('cli-status', { running: false, message: 'Tracking stopped' });
      }
    });

    // Wait a bit to see if process starts successfully
    setTimeout(() => {
      if (!isCliRunning) {
        console.log('CLI startup timeout, checking if running...');
        // Check if process is still alive
        if (cliProcess && !cliProcess.killed) {
          isCliRunning = true;
          console.log('CLI process appears to be running');
          if (mainWindow && mainWindow.webContents) {
            mainWindow.webContents.send('cli-status', { running: true, message: 'Tracking active' });
          }
        }
      }
    }, 3000);

  } catch (error) {
    console.error('Error starting CLI tracking:', error);
    if (mainWindow && mainWindow.webContents) {
      mainWindow.webContents.send('cli-status', { running: false, message: `Error: ${error.message}` });
    }
  }
}

// Stop CLI tracking process
function stopCliTracking() {
  if (!isCliRunning || !cliProcess) {
    console.log('CLI tracking not running');
    return;
  }

  try {
    console.log('Stopping CLI tracking...');
    
    // Kill the process
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', cliProcess.pid, '/f', '/t']);
    } else {
      cliProcess.kill('SIGTERM');
    }
    
    isCliRunning = false;
    cliProcess = null;
    
    if (mainWindow && mainWindow.webContents) {
      mainWindow.webContents.send('cli-status', { running: false, message: 'Tracking stopped' });
    }
    
    console.log('CLI tracking stopped');
    
  } catch (error) {
    console.error('Error stopping CLI tracking:', error);
  }
}

// Stop Python backend process
function stopBackend() {
  if (!isBackendRunning || !pythonProcess) {
    console.log('Backend not running');
    return { success: false, message: 'Backend not running' };
  }

  try {
    console.log('Stopping backend...');
    
    // Kill the process
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', pythonProcess.pid, '/f', '/t']);
    } else {
      pythonProcess.kill('SIGTERM');
    }
    
    isBackendRunning = false;
    pythonProcess = null;
    
    mainWindow.webContents.send('backend-status', { running: false, message: 'Backend stopped' });
    return { success: true, message: 'Backend stopped' };

  } catch (error) {
    console.error('Error stopping backend:', error);
    return { success: false, message: `Error: ${error.message}` };
  }
}

// Health check function to verify backend is responding
function checkBackendHealth() {
  return new Promise((resolve) => {
    const req = http.get('http://localhost:8000/health', (res) => {
      if (res.statusCode === 200) {
        resolve(true);
      } else {
        resolve(false);
      }
    });
    
    req.on('error', () => {
      resolve(false);
    });
    
    req.setTimeout(2000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

// Create main window
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    },
    icon: path.join(__dirname, '..', 'assets', 'icon.png'),
    title: 'GUM - General User Models'
  });

  // Load the app
  if (app.isPackaged) {
    mainWindow.loadFile(path.join(__dirname, '..', 'index.html'));
  } else {
    // Load the main HTML file directly
    mainWindow.loadFile(path.join(__dirname, '..', 'index.html'));
  }

  // Open DevTools in development
  if (!app.isPackaged) {
    mainWindow.webContents.openDevTools();
  }

  // Handle window closed
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// App event handlers
app.whenReady().then(() => {
  createWindow();
  
  // Auto-start backend when app launches
  setTimeout(() => {
    startBackend();
  }, 1000);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  // Clean up backend process before quitting
  if (pythonProcess) {
    stopBackend();
  }
});

// Handle app quit
app.on('quit', () => {
  if (pythonProcess) {
    stopBackend();
  }
  if (cliProcess) {
    stopCliTracking();
  }
});

// IPC handlers for CLI tracking
ipcMain.handle('start-cli-tracking', () => {
  startCliTracking();
  return { success: true };
});

ipcMain.handle('stop-cli-tracking', () => {
  stopCliTracking();
  return { success: true };
});

ipcMain.handle('get-cli-status', () => {
  return { running: isCliRunning };
});
