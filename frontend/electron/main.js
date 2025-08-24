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
      pythonProcess = spawn(pythonPath, [backendPath, '--port', '8000'], {
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

// Start CLI tracking process with production-grade safeguards
async function startCliTracking() {
  // Step 1: Prevent multiple instances
  if (isCliRunning) {
    console.log('CLI tracking already running');
    return { success: false, message: 'Already running' };
  }

  try {
    console.log('Starting CLI tracking...');
    
    // Step 2: Clean up any existing processes first
    await killAllGumProcesses();
    await new Promise(resolve => setTimeout(resolve, 1000)); // Wait 1 second
    
    // Step 3: Verify no processes are running
    const stillRunning = await checkForRunningGumProcesses();
    if (stillRunning) {
      console.warn('Warning: Found existing processes, attempting cleanup...');
      await killAllGumProcesses();
      await new Promise(resolve => setTimeout(resolve, 2000)); // Wait longer
    }
    
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

// Production-grade CLI process killer
async function killProcessTree(pid, signal = 'SIGTERM') {
  return new Promise((resolve) => {
    if (process.platform === 'win32') {
      // Windows: Kill process tree including all child processes
      const killCommand = spawn('taskkill', ['/pid', pid, '/f', '/t'], { 
        stdio: 'pipe',
        shell: true 
      });
      
      killCommand.on('close', (code) => {
        console.log(`Process tree kill completed with code: ${code}`);
        resolve(code === 0);
      });
      
      killCommand.on('error', (error) => {
        console.error('Kill command error:', error);
        resolve(false);
      });
      
      // Timeout after 5 seconds
      setTimeout(() => {
        killCommand.kill();
        resolve(false);
      }, 5000);
      
    } else {
      // Unix/Linux/macOS: Kill process group
      try {
        process.kill(-pid, signal);
        resolve(true);
      } catch (error) {
        console.error('Kill process group error:', error);
        resolve(false);
      }
    }
  });
}

// Kill only GUM CLI processes (NOT the backend!)
async function killAllGumProcesses() {
  return new Promise((resolve) => {
    if (process.platform === 'win32') {
      // Windows: Use WMIC to find and kill only processes running gum.cli
      const findCommand = spawn('wmic', [
        'process', 'where', 
        'CommandLine like "%gum.cli%" or CommandLine like "%gum\\cli%"',
        'get', 'ProcessId', '/format:value'
      ], { 
        stdio: 'pipe',
        shell: true 
      });
      
      let output = '';
      findCommand.stdout.on('data', (data) => {
        output += data.toString();
      });
      
      findCommand.on('close', (code) => {
        // Extract PIDs from WMIC output
        const pids = output.match(/ProcessId=(\d+)/g);
        
        if (pids && pids.length > 0) {
          console.log(`Found ${pids.length} GUM CLI processes to kill`);
          
          // Kill each PID individually
          const killPromises = pids.map(pidMatch => {
            const pid = pidMatch.replace('ProcessId=', '');
            return new Promise(killResolve => {
              const killCmd = spawn('taskkill', ['/pid', pid, '/f', '/t'], { 
                stdio: 'pipe',
                shell: true 
              });
              killCmd.on('close', () => killResolve());
              killCmd.on('error', () => killResolve());
              setTimeout(() => killResolve(), 2000);
            });
          });
          
          Promise.all(killPromises).then(() => {
            console.log('Selective GUM CLI process kill completed');
            resolve(true);
          });
          
        } else {
          console.log('No GUM CLI processes found to kill');
          resolve(true);
        }
      });
      
      findCommand.on('error', (error) => {
        console.log('WMIC command failed, falling back to basic kill');
        // Fallback: try to kill by window title or command line
        const fallbackKill = spawn('taskkill', ['/f', '/fi', 'WINDOWTITLE eq *gum*'], { 
          stdio: 'pipe',
          shell: true 
        });
        fallbackKill.on('close', () => resolve(true));
        fallbackKill.on('error', () => resolve(true));
        setTimeout(() => resolve(true), 3000);
      });
      
    } else {
      // Unix: Kill processes containing 'gum.cli' (this was already correct)
      const killCommand = spawn('pkill', ['-f', 'gum.cli'], { 
        stdio: 'pipe' 
      });
      
      killCommand.on('close', (code) => {
        console.log(`GUM CLI process kill completed with code: ${code}`);
        resolve(true);
      });
      
      killCommand.on('error', () => {
        resolve(true);
      });
    }
    
    // Timeout after 8 seconds (increased for WMIC)
    setTimeout(() => resolve(true), 8000);
  });
}

// Stop CLI tracking process with production-grade cleanup
async function stopCliTracking() {
  console.log('Stopping CLI tracking...');
  
  try {
    // Step 1: Graceful shutdown attempt
    if (cliProcess && !cliProcess.killed) {
      console.log('Attempting graceful shutdown...');
      
      if (process.platform === 'win32') {
        // Send Ctrl+C to gracefully stop the process
        cliProcess.kill('SIGINT');
      } else {
        cliProcess.kill('SIGTERM');
      }
      
      // Wait up to 3 seconds for graceful shutdown
      await new Promise(resolve => setTimeout(resolve, 3000));
    }
    
    // Step 2: Force kill process tree if still running
    if (cliProcess && !cliProcess.killed) {
      console.log('Graceful shutdown failed, force killing process tree...');
      await killProcessTree(cliProcess.pid, 'SIGKILL');
    }
    
    // Step 3: Nuclear option - kill all Python processes (backup)
    console.log('Ensuring all GUM processes are terminated...');
    await killAllGumProcesses();
    
    // Step 4: Clean up state
    isCliRunning = false;
    cliProcess = null;
    
    // Step 5: Verify no processes are running
    setTimeout(async () => {
      const stillRunning = await checkForRunningGumProcesses();
      if (stillRunning) {
        console.warn('Warning: Some GUM processes may still be running');
      } else {
        console.log('All CLI processes successfully terminated');
      }
    }, 1000);
    
    if (mainWindow && mainWindow.webContents) {
      mainWindow.webContents.send('cli-status', { running: false, message: 'Tracking stopped' });
    }
    
  } catch (error) {
    console.error('Error stopping CLI tracking:', error);
    // Even if there's an error, ensure state is clean
    isCliRunning = false;
    cliProcess = null;
  }
}

// Check if any GUM CLI processes are still running (NOT backend!)
async function checkForRunningGumProcesses() {
  return new Promise((resolve) => {
    if (process.platform === 'win32') {
      // Windows: Use WMIC to check specifically for gum.cli processes
      const checkCommand = spawn('wmic', [
        'process', 'where', 
        'CommandLine like "%gum.cli%" or CommandLine like "%gum\\cli%"',
        'get', 'ProcessId', '/format:value'
      ], { 
        stdio: 'pipe',
        shell: true 
      });
      
      let output = '';
      checkCommand.stdout.on('data', (data) => {
        output += data.toString();
      });
      
      checkCommand.on('close', () => {
        // Check if any ProcessId entries exist
        const hasGumProcesses = /ProcessId=\d+/.test(output);
        resolve(hasGumProcesses);
      });
      
      checkCommand.on('error', () => {
        // Fallback: check for any python processes and assume they might be CLI
        const fallbackCheck = spawn('tasklist', ['/fi', 'imagename eq python.exe'], { 
          stdio: 'pipe',
          shell: true 
        });
        
        let fallbackOutput = '';
        fallbackCheck.stdout.on('data', (data) => {
          fallbackOutput += data.toString();
        });
        
        fallbackCheck.on('close', () => {
          // Conservative check - if there are multiple python processes, assume CLI might be running
          const pythonCount = (fallbackOutput.match(/python\.exe/g) || []).length;
          resolve(pythonCount > 1); // More than just the backend
        });
        
        fallbackCheck.on('error', () => resolve(false));
      });
      
      setTimeout(() => resolve(false), 3000);
      
    } else {
      // Unix: Check specifically for gum.cli processes (this was already correct)
      const checkCommand = spawn('pgrep', ['-f', 'gum.cli'], { stdio: 'pipe' });
      checkCommand.on('close', (code) => resolve(code === 0));
      checkCommand.on('error', () => resolve(false));
      setTimeout(() => resolve(false), 2000);
    }
  });
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

app.on('before-quit', async () => {
  console.log('App quitting, cleaning up processes...');
  
  // Clean up all processes before quitting
  try {
    if (cliProcess || isCliRunning) {
      console.log('Stopping CLI tracking...');
      await stopCliTracking();
    }
    
    if (pythonProcess || isBackendRunning) {
      console.log('Stopping backend...');
      stopBackend();
    }
    
    // Selective cleanup - only kill CLI processes, preserve backend
    console.log('Final cleanup - killing any remaining CLI processes...');
    await killAllGumProcesses();
    
  } catch (error) {
    console.error('Error during app cleanup:', error);
  }
});

// Handle app quit with emergency cleanup
app.on('quit', async () => {
  console.log('App quit event - emergency cleanup...');
  
  try {
    // Emergency cleanup - only CLI processes, preserve backend
    await killAllGumProcesses();
    console.log('Emergency CLI cleanup completed');
  } catch (error) {
    console.error('Emergency cleanup failed:', error);
  }
});

// Production-grade IPC handlers for CLI tracking
ipcMain.handle('start-cli-tracking', async () => {
  try {
    console.log('IPC: Starting CLI tracking...');
    const result = await startCliTracking();
    console.log('IPC: CLI tracking start result:', result);
    return result || { success: true };
  } catch (error) {
    console.error('IPC: Failed to start CLI tracking:', error);
    return { success: false, message: error.message };
  }
});

ipcMain.handle('stop-cli-tracking', async () => {
  try {
    console.log('IPC: Stopping CLI tracking...');
    await stopCliTracking();
    console.log('IPC: CLI tracking stopped successfully');
    return { success: true };
  } catch (error) {
    console.error('IPC: Failed to stop CLI tracking:', error);
    return { success: false, message: error.message };
  }
});

ipcMain.handle('get-cli-status', async () => {
  try {
    // Also check for actual running processes, not just our flag
    const actuallyRunning = await checkForRunningGumProcesses();
    const reported = { running: isCliRunning, actualProcesses: actuallyRunning };
    
    // If there's a mismatch, correct our state
    if (isCliRunning && !actuallyRunning) {
      console.warn('State mismatch: CLI marked as running but no processes found');
      isCliRunning = false;
      cliProcess = null;
    } else if (!isCliRunning && actuallyRunning) {
      console.warn('State mismatch: CLI marked as stopped but processes still running');
      // Don't auto-correct this one, let user handle it
    }
    
    return { 
      running: isCliRunning, 
      verified: actuallyRunning,
      consistent: isCliRunning === actuallyRunning
    };
  } catch (error) {
    console.error('IPC: Failed to get CLI status:', error);
    return { running: false, error: error.message };
  }
});
