#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

console.log('\x1b[36m\x1b[1m╔══════════════════════════════════════════════════════════════╗\x1b[0m');
console.log('\x1b[36m\x1b[1m║              ArquiSysAI - Configuración Inicial              ║\x1b[0m');
console.log('\x1b[36m\x1b[1m╚══════════════════════════════════════════════════════════════╝\x1b[0m\n');

const packageDir = path.resolve(__dirname);
const homeDir = require('os').homedir();

const envPath = path.join(homeDir, '.arquisys-ai.env');

if (!fs.existsSync(envPath)) {
    console.log('\x1b[33mCreando archivo de configuración...\x1b[0m');
    const envContent = `# ArquiSysAI Configuration
# Get your API key from https://opencode.ai

OPENCODE_API_KEY=sk-placeholder-requires-setup
`;
    fs.writeFileSync(envPath, envContent);
    console.log(`\x1b[32m✓ Archivo de configuración creado en: ${envPath}\x1b[0m`);
}

console.log('\x1b[33mVerificando dependencias de Python...\x1b[0m');
const requirementsPath = path.join(packageDir, 'requirements.txt');

if (fs.existsSync(requirementsPath)) {
    try {
        console.log('Instalando dependencias de Python...');
        execSync(`pip install -r "${requirementsPath}"`, { stdio: 'inherit' });
        console.log('\x1b[32m✓ Dependencias instaladas correctamente\x1b[0m');
    } catch (error) {
        console.log('\x1b[33mAdvertencia: No se pudieron instalar automáticamente las dependencias.\x1b[0m');
        console.log('Por favor, ejecuta manualmente: pip install -r ' + requirementsPath);
    }
}

console.log('\n\x1b[32m\x1b[1m╔══════════════════════════════════════════════════════════════╗\x1b[0m');
console.log('\x1b[32m\x1b[1m║           ¡Instalación completada exitosamente!               ║\x1b[0m');
console.log('\x1b[32m\x1b[1m╚══════════════════════════════════════════════════════════════╝\x1b[0m\n');
console.log('Para comenzar, ejecuta: \x1b[36marquisys-ai\x1b[0m\n');
