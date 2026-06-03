#!/usr/bin/env node

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const packageDir = path.resolve(__dirname);

function findPython() {
    const pythonCommands = ['python', 'python3', 'py'];

    for (const cmd of pythonCommands) {
        try {
            const result = require('child_process').spawnSync(cmd, ['--version']);
            if (result.status === 0) {
                return cmd;
            }
        } catch (e) {
        }
    }
    return null;
}

const pythonCmd = findPython();

if (!pythonCmd) {
    console.error('\x1b[31mError: Python no está instalado o no se encuentra en el PATH.\x1b[0m');
    console.error('Por favor, instala Python desde https://www.python.org/downloads/');
    process.exit(1);
}

const mainPy = path.join(packageDir, 'main.py');
const child = spawn(pythonCmd, [mainPy], {
    stdio: 'inherit',
    env: { ...process.env, PYTHONPATH: packageDir }
});

child.on('exit', (code) => {
    process.exit(code || 0);
});
