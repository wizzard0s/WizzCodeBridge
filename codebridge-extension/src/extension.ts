import * as vscode from 'vscode';
import { spawn } from 'child_process';
import * as path from 'path';

export function activate(context: vscode.ExtensionContext) {
    console.log('✨ CodeBridge interface cockpit extension is now active!');

    let webviewProvider = new CodeBridgeWebViewProvider(context.extensionUri);
    let planProcess: ReturnType<typeof spawn> | undefined;
    let executionProcess: ReturnType<typeof spawn> | undefined;
    let activeRunId: string | undefined = vscode.workspace.getConfiguration('codebridge').get<string>('activeRunId');
    const bridgeMain = path.resolve(context.extensionUri.fsPath, '..', 'codebridge', 'main.py');
    const bridgeRoot = path.dirname(bridgeMain);

    const terminalMode = () => vscode.workspace.getConfiguration('codebridge').get<string>('terminalApproval', 'prompt');
    const roles = ['researcher', 'requirements', 'architect', 'implementer', 'verifier'];
    const childEnvironment = () => {
        const env: NodeJS.ProcessEnv = { ...process.env, CODEBRIDGE_TERMINAL_APPROVAL: terminalMode() };
        const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        const projectTarget = vscode.workspace.getConfiguration('codebridge').get<string>('projectTarget');
        if (workspaceRoot) env.CODEBRIDGE_WORKSPACE_ROOT = workspaceRoot;
        if (projectTarget) env.CODEBRIDGE_PROJECT_TARGET = projectTarget;
        for (const role of roles) {
            const routing = vscode.workspace.getConfiguration(`codebridge.roles.${role}`);
            const provider = routing.get<string>('provider');
            const model = routing.get<string>('model');
            if (provider) env[`CODEBRIDGE_ROLE_${role.toUpperCase()}_PROVIDER`] = provider;
            if (model) env[`CODEBRIDGE_ROLE_${role.toUpperCase()}_MODEL`] = model;
        }
        return env;
    };

    // 1. Registered Architect command routing lines to the "plan" tab zone
    let planCommand = vscode.commands.registerCommand('codebridge.runPlan', async (promptText: string) => {
        if (!promptText) return;
        webviewProvider.clearTerminal('plan');
        webviewProvider.logToTerminal('plan', "🧠 Starting researcher, requirements interview, and architect...\n");
        webviewProvider.setPromptValue('');

        if (planProcess && !planProcess.killed) {
            webviewProvider.logToTerminal('plan', '\n⚠️ A planning interview is already running. Answer or finish it first.');
            return;
        }
        activeRunId = undefined;
        void vscode.workspace.getConfiguration('codebridge').update('activeRunId', '', vscode.ConfigurationTarget.Workspace);
        const child = spawn('python3', [bridgeMain, 'plan', promptText], { cwd: bridgeRoot, env: childEnvironment(), stdio: ['pipe', 'pipe', 'pipe'] });
        planProcess = child;

        child.stdout.on('data', (data) => {
            const output = data.toString();
            const runMatch = output.match(/run(?: ID)?:\s*([\w-]+)/i);
            if (runMatch) {
                activeRunId = runMatch[1];
                void vscode.workspace.getConfiguration('codebridge').update('activeRunId', activeRunId, vscode.ConfigurationTarget.Workspace);
            }
            webviewProvider.logToTerminal('plan', output);
        });
        child.stderr.on('data', (data) => webviewProvider.logToTerminal('plan', `❌ Error: ${data.toString()}`));
        
        child.on('close', (code) => {
            if (planProcess === child) planProcess = undefined;
            if (code === 0) {
                vscode.window.showInformationMessage('CodeBridge: planning run finished.');
            } else {
                webviewProvider.logToTerminal('plan', `\n❌ Planning phase exited with error code ${code}`);
            }
        });
    });

    // 2. Registered Muscle execution command routing lines to the "muscle" tab zone
    let executeCommand = vscode.commands.registerCommand('codebridge.runExecute', () => {
        webviewProvider.clearTerminal('muscle');
        webviewProvider.logToTerminal('muscle', "🪃 Starting the accepted implementation and verification plan...\n");

        if (!activeRunId) {
            webviewProvider.logToTerminal('muscle', 'Start and accept a plan first.');
            return;
        }
        const child = spawn('python3', [bridgeMain, 'execute', activeRunId], { cwd: bridgeRoot, env: childEnvironment(), stdio: ['pipe', 'pipe', 'pipe'] });
        executionProcess = child;

        child.stdout.on('data', (data) => webviewProvider.logToTerminal('muscle', data.toString()));
        child.stderr.on('data', (data) => webviewProvider.logToTerminal('muscle', `⚠️ Error: ${data.toString()}`));
        
        child.on('close', (code) => {
            if (executionProcess === child) executionProcess = undefined;
            webviewProvider.logToTerminal('muscle', `\n🛑 Process terminated with exit code ${code}`);
        });
    });

    let sendPlanInput = vscode.commands.registerCommand('codebridge.sendPlanInput', async (text: string) => {
        if (planProcess && !planProcess.killed) {
            planProcess.stdin?.write(`${text}\n`);
            webviewProvider.logToTerminal('plan', `\nYou: ${text}\n`);
        } else if (executionProcess && !executionProcess.killed) {
            executionProcess.stdin?.write(`${text}\n`);
            webviewProvider.logToTerminal('muscle', `\nYou approved/responded: ${text}\n`);
        } else {
            webviewProvider.logToTerminal('plan', '\nNo active interview is waiting for input. Start a new plan.');
        }
    });

    let revisePlan = vscode.commands.registerCommand('codebridge.revisePlan', async (reason: string) => {
        if (!activeRunId || !reason || (planProcess && !planProcess.killed)) {
            webviewProvider.logToTerminal('plan', '\nAccept a plan first and provide a revision reason.');
            return;
        }
        const child = spawn('python3', [bridgeMain, 'revise', activeRunId, reason], { cwd: bridgeRoot, env: childEnvironment(), stdio: ['pipe', 'pipe', 'pipe'] });
        planProcess = child;
        child.stdout.on('data', data => {
            const output = data.toString();
            const runMatch = output.match(/run(?: ID)?:\s*([\w-]+)/i);
            if (runMatch) {
                activeRunId = runMatch[1];
                void vscode.workspace.getConfiguration('codebridge').update('activeRunId', activeRunId, vscode.ConfigurationTarget.Workspace);
            }
            webviewProvider.logToTerminal('plan', output);
        });
        child.stderr.on('data', data => webviewProvider.logToTerminal('plan', `❌ Error: ${data.toString()}`));
        child.on('close', code => {
            if (planProcess === child) planProcess = undefined;
            webviewProvider.logToTerminal('plan', `\nRevision process finished (${code}).`);
        });
    });

    let setTerminalMode = vscode.commands.registerCommand('codebridge.setTerminalMode', async (mode: string) => {
        if (mode !== 'prompt' && mode !== 'auto') return;
        await vscode.workspace.getConfiguration('codebridge').update('terminalApproval', mode, vscode.ConfigurationTarget.Workspace);
        webviewProvider.logToTerminal('muscle', `\nTerminal approval mode set to ${mode === 'prompt' ? 'Prompt' : 'Auto'}.`);
    });

    let saveRoleRouting = vscode.commands.registerCommand('codebridge.saveRoleRouting', async (role: string, provider: string, model: string) => {
        if (!roles.includes(role) || !model.trim() || !['ollama', 'openrouter'].includes(provider)) return;
        const routing = vscode.workspace.getConfiguration(`codebridge.roles.${role}`);
        await routing.update('provider', provider, vscode.ConfigurationTarget.Workspace);
        await routing.update('model', model.trim(), vscode.ConfigurationTarget.Workspace);
        webviewProvider.logToTerminal('plan', `\n${role} routing saved: ${provider}/${model.trim()}. New runs will use it.`);
    });

    context.subscriptions.push(
        planCommand,
        executeCommand,
        sendPlanInput,
        revisePlan,
        setTerminalMode,
        saveRoleRouting,
        vscode.window.registerWebviewViewProvider('codebridge-actions', webviewProvider)
    );
}
// 🎛️ The Visual Dashboard Interface Engine Class (With Multi-Tab Scrolling Logger Panel)
class CodeBridgeWebViewProvider implements vscode.WebviewViewProvider {
    private _view?: vscode.WebviewView;

    constructor(private readonly _extensionUri: vscode.Uri) {}

    public resolveWebviewView(webviewView: vscode.WebviewView) {
        this._view = webviewView;
        webviewView.webview.options = { enableScripts: true };
        const roles = ['researcher', 'requirements', 'architect', 'implementer', 'verifier'];
        const roleSettingsHtml = roles.map(role => {
            const routing = vscode.workspace.getConfiguration(`codebridge.roles.${role}`);
            const provider = routing.get<string>('provider', 'ollama');
            const model = routing.get<string>('model', 'qwen2.5-coder:14b');
            const safeModel = model.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;');
            return `<div class="row role-row"><label>${role}</label><select id="provider-${role}"><option value="ollama" ${provider === 'ollama' ? 'selected' : ''}>Ollama</option><option value="openrouter" ${provider === 'openrouter' ? 'selected' : ''}>OpenRouter</option></select><input id="model-${role}" value="${safeModel}" /><button class="small-btn" onclick="saveRole('${role}')">Save</button></div>`;
        }).join('');
        webviewView.webview.html = `
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <style>
                    body { font-family: sans-serif; padding: 8px; display: flex; flex-direction: column; gap: 7px; background-color: transparent; box-sizing: border-box; height: 100vh; overflow: hidden; }
                    .title { font-size: 11px; opacity: 0.6; text-transform: uppercase; letter-spacing: 0.8px; font-weight: bold; color: var(--vscode-foreground); }
                    
                    .composer { flex: 0 0 auto; border: 1px solid var(--vscode-input-border, #3c3c3c); border-radius: 12px; background: var(--vscode-input-background); padding: 7px; }
                    textarea { display: block; width: 100%; min-height: 38px; max-height: 120px; box-sizing: border-box; background: transparent; color: var(--vscode-input-foreground); border: 0; padding: 3px 5px 7px; font-family: inherit; font-size: 12px; line-height: 1.4; resize: vertical; }
                    textarea:focus { outline: none; }
                    .composer:focus-within { outline: 1px solid var(--vscode-focusBorder); }
                    
                    button { background-color: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; padding: 7px; cursor: pointer; text-align: center; border-radius: 4px; font-weight: bold; font-size: 11px; width: 100%; }
                    button:hover { background-color: var(--vscode-button-hoverBackground); }
                    .execute-btn { background-color: #2ea043; color: white; margin-top: 2px; }
                    .execute-btn:hover { background-color: #3fb950; }
                    .small-btn { width: auto; padding: 4px 7px; font-size: 10px; }
                    .row { display: flex; gap: 6px; align-items: center; }
                    .composer-actions { display: flex; align-items: center; gap: 5px; }
                    .composer-actions .small-btn { padding: 4px 6px; }
                    .composer-actions .action-icon { width: 25px; height: 25px; padding: 0; font-size: 14px; line-height: 25px; border-radius: 50%; }
                    .composer-actions .send-btn { margin-left: auto; background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
                    select { flex: 1; min-width: 0; padding: 6px; background: var(--vscode-dropdown-background); color: var(--vscode-dropdown-foreground); border: 1px solid var(--vscode-dropdown-border); }
                    .role-row { margin: 5px 0; }
                    .role-row label { width: 82px; text-transform: capitalize; }
                    .role-row input { flex: 1; min-width: 0; padding: 6px; background: var(--vscode-input-background); color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border); }
                    
                    /* Tab Selector Panel Bar Layout */
                    .tabs-bar { display: flex; border-bottom: 1px solid #21262d; margin-top: 5px; gap: 4px; }
                    .tab-btn { background: transparent; color: var(--vscode-foreground); border: none; padding: 6px 12px; width: auto; font-size: 11px; font-weight: normal; cursor: pointer; border-radius: 4px 4px 0 0; opacity: 0.6; }
                    .tab-btn:hover { opacity: 1; background: rgba(255,255,255,0.05); }
                    .tab-btn.active { opacity: 1; border-bottom: 2px solid var(--vscode-button-background); font-weight: bold; }
                    
                    /* Tabbed Terminal Panels Configuration */
                    .terminal-zone {
                        display: none; /* Hidden by default */
                        flex: 1 1 auto;
                        min-height: 0;
                        background-color: #0d1117;
                        color: #c9d1d9;
                        border: 1px solid #21262d;
                        border-radius: 0 0 4px 4px;
                        padding: 8px;
                        font-family: 'Courier New', Courier, monospace;
                        font-size: 11px;
                        line-height: 14px;
                        overflow-y: auto;
                        white-space: pre-wrap;
                        height: auto;
                        box-sizing: border-box;
                    }
                    .terminal-zone.active { display: block; } /* Render active log zone exclusively */
                </style>
            </head>
            <body>
                <div class="title">CodeBridge Control Board</div>
                <div class="row">
                    <label for="terminalMode">Terminal commands</label>
                    <select id="terminalMode" onchange="setTerminalMode(this.value)">
                        <option value="prompt">Prompt before each command</option>
                        <option value="auto">Run automatically</option>
                    </select>
                </div>
                <details>
                    <summary>Role model routing</summary>
                    ${roleSettingsHtml}
                    <small>Saved per workspace; the API key remains in your environment or .env.</small>
                </details>
                <button class="execute-btn" onclick="triggerExecute()">Run accepted plan</button>
                
                <!-- The Navigation Tab Headers Bar Grid Layout -->
                <div class="tabs-bar">
                    <button id="tabHead-plan" class="tab-btn active" onclick="switchTab('plan')">📋 Planning and review</button>
                    <button id="tabHead-muscle" class="tab-btn" onclick="switchTab('muscle')">⚙️ Implementation</button>
                </div>
                
                <!-- Tab View 1: Architecture Planning Log Window -->
                <div id="term-plan" class="terminal-zone active">System standing by. Awaiting planning parameters...</div>
                
                <!-- Tab View 2: Local GPU Container Muscle Execution Log Window -->
                <div id="term-muscle" class="terminal-zone">Muscle core standby. Run the execution engine to stream live data logs...</div>

                <div class="composer">
                    <textarea id="promptInput" placeholder="Describe your goal or reply to the active interview..."></textarea>
                    <div class="composer-actions">
                        <button class="small-btn action-icon" title="Start planning" aria-label="Start planning" onclick="triggerPlan()">＋</button>
                        <button class="small-btn" onclick="sendPlanInput()">Send reply</button>
                        <button class="small-btn" title="Revise plan" aria-label="Revise plan" onclick="triggerRevise()">Revise</button>
                        <button class="small-btn send-btn action-icon" title="Run accepted plan" aria-label="Run accepted plan" onclick="triggerExecute()">↑</button>
                    </div>
                </div>

                <script>
                    const vscode = acquireVsCodeApi();
                    
                    function triggerPlan() {
                        const promptText = document.getElementById('promptInput').value.trim();
                        if (!promptText) return;
                        switchTab('plan');
                        vscode.postMessage({ command: 'codebridge.runPlan', text: promptText });
                    }
                    
                    function triggerExecute() {
                        switchTab('muscle');
                        vscode.postMessage({ command: 'codebridge.runExecute' });
                    }

                    function sendPlanInput() {
                        const text = document.getElementById('promptInput').value.trim();
                        if (!text) return;
                        vscode.postMessage({ command: 'codebridge.sendPlanInput', text });
                        document.getElementById('promptInput').value = '';
                    }

                    function triggerRevise() {
                        const reason = document.getElementById('promptInput').value.trim();
                        if (!reason) return;
                        vscode.postMessage({ command: 'codebridge.revisePlan', reason });
                        document.getElementById('promptInput').value = '';
                    }

                    function setTerminalMode(mode) {
                        vscode.postMessage({ command: 'codebridge.setTerminalMode', mode });
                    }

                    function saveRole(role) {
                        const provider = document.getElementById('provider-' + role).value;
                        const model = document.getElementById('model-' + role).value.trim();
                        vscode.postMessage({ command: 'codebridge.saveRoleRouting', role, provider, model });
                    }

                    document.getElementById('terminalMode').value = '${vscode.workspace.getConfiguration('codebridge').get<string>('terminalApproval', 'prompt')}';

                    function switchTab(tabId) {
                        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
                        document.querySelectorAll('.terminal-zone').forEach(zone => zone.classList.remove('active'));
                        
                        document.getElementById('tabHead-' + tabId).classList.add('active');
                        document.getElementById('term-' + tabId).classList.add('active');
                    }

                    window.addEventListener('message', event => {
                        const message = event.data;
                        if (message.action === 'log') {
                            const targetId = 'term-' + message.target;
                            const term = document.getElementById(targetId);
                            
                            if (term.innerText.includes("standing by") || term.innerText.includes("core standby")) {
                                term.innerText = "";
                            }
                            
                            term.innerText += message.data;
                            term.scrollTop = term.scrollHeight;
                        } else if (message.action === 'clear') {
                            document.getElementById('term-' + message.target).innerText = "";
                        } else if (message.action === 'prompt') {
                            document.getElementById('promptInput').value = message.value;
                        }
                    });
                </script>
            </body>
            </html>
        `;

        webviewView.webview.onDidReceiveMessage(message => {
            if (message.command === 'codebridge.runPlan') {
                vscode.commands.executeCommand(message.command, message.text);
            } else if (message.command === 'codebridge.runExecute') {
                vscode.commands.executeCommand(message.command);
            } else if (message.command === 'codebridge.sendPlanInput') {
                vscode.commands.executeCommand(message.command, message.text);
            } else if (message.command === 'codebridge.revisePlan') {
                vscode.commands.executeCommand(message.command, message.reason);
            } else if (message.command === 'codebridge.setTerminalMode') {
                vscode.commands.executeCommand(message.command, message.mode);
            } else if (message.command === 'codebridge.saveRoleRouting') {
                vscode.commands.executeCommand(message.command, message.role, message.provider, message.model);
            }
        });
    }

    public logToTerminal(target: 'plan' | 'muscle', text: string) {
        if (this._view) {
            this._view.webview.postMessage({ action: 'log', target: target, data: text });
        }
    }

    public clearTerminal(target: 'plan' | 'muscle') {
        if (this._view) {
            this._view.webview.postMessage({ action: 'clear', target: target });
        }
    }

    public setPromptValue(value: string) {
        if (this._view) this._view.webview.postMessage({ action: 'prompt', value });
    }
}

export function deactivate() {}
