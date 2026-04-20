// JAN v2.0 — Frontend Application
// Connects to FastAPI backend at /chat, /agents, etc.

const API_BASE = window.location.origin;

// ── DOM References ──────────────────────────────
const $messages    = document.getElementById('messages');
const $input       = document.getElementById('chat-input');
const $sendBtn     = document.getElementById('btn-send');
const $statusDot   = document.getElementById('status-indicator');
const $statusText  = document.getElementById('status-text');
const $agentPanel  = document.getElementById('agent-panel');
const $agentList   = document.getElementById('agent-list');
const $agentBadge  = document.getElementById('agent-badge');
const $agentBadgeName = document.getElementById('agent-badge-name');
const $agentBadgeDismiss = document.getElementById('agent-badge-dismiss');
const $modalOverlay = document.getElementById('modal-overlay');
const $modal       = document.getElementById('modal');
const $modalTitle  = document.getElementById('modal-title');
const $modalBody   = document.getElementById('modal-body');

// ── State ───────────────────────────────────────
let agents = {};
let targetAgent = null;   // if user picks a specific agent
let isSending = false;
let voiceEnabled = true;

// ── Init ────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    checkHealth();
    loadAgents();
    setupEventListeners();
    $input.focus();
});

// ── Health Check ────────────────────────────────
async function checkHealth() {
    try {
        const resp = await fetch(`${API_BASE}/health`);
        const data = await resp.json();
        setStatus('online', `ONLINE — ${data.agents || 0} agents`);
        voiceEnabled = data.auto_voice;
        updateVoiceBtn();
    } catch {
        setStatus('offline', 'OFFLINE');
    }
}

function setStatus(state, text) {
    $statusDot.className = `status ${state}`;
    $statusText.textContent = text;
}

// ── Load Agents ─────────────────────────────────
async function loadAgents() {
    try {
        const resp = await fetch(`${API_BASE}/agents`);
        const data = await resp.json();
        agents = data.agents || {};
        renderAgentList();
    } catch {
        $agentList.innerHTML = '<p style="color:var(--text-muted);padding:16px;">Could not load agents</p>';
    }
}

function renderAgentList() {
    $agentList.innerHTML = '';
    const descriptions = {
        chat: 'Casual conversation, Q&A, personality',
        browser: 'Navigate websites, click, fill forms',
        media: 'YouTube, Spotify, playback control',
        communication: 'Email, WhatsApp, Discord',
        research: 'Deep web research, summarize',
        memory: 'Remember, recall, preferences',
        productivity: 'Reminders, todos, briefings',
        file: 'File management, organize, search',
        system: 'Open/close apps, volume, settings',
        coding: 'Write code, debug, scripts',
        creative: 'Write emails, essays, content',
        automation: 'Multi-step workflows, chains',
        vision: 'Screen analysis, OCR, camera',
        self_improvement: 'Create modules, learn, evolve',
    };

    for (const [name, info] of Object.entries(agents)) {
        const card = document.createElement('div');
        card.className = 'agent-card';
        card.innerHTML = `
            <div class="agent-card-header">
                <span class="agent-name">${name}</span>
                <span class="agent-model">${info.model.split(':')[0]}</span>
            </div>
            <div class="agent-tools">${descriptions[name] || 'Specialized agent'}</div>
            <div class="agent-steps">max ${info.max_steps} steps · ${info.tools.length} tools</div>
        `;
        card.addEventListener('click', () => showAgentDetail(name, info));
        $agentList.appendChild(card);
    }
}

// ── Agent Detail Modal ──────────────────────────
function showAgentDetail(name, info) {
    $modalTitle.textContent = name.toUpperCase() + ' AGENT';
    $modalBody.innerHTML = `
        <div class="detail-row">
            <span class="detail-label">Model</span>
            <span class="detail-value">${info.model}</span>
        </div>
        <div class="detail-row">
            <span class="detail-label">Max Steps</span>
            <span class="detail-value">${info.max_steps}</span>
        </div>
        <div class="detail-row">
            <span class="detail-label">Screen Reader</span>
            <span class="detail-value">${info.has_screen_reader ? '✓ Yes' : '✗ No'}</span>
        </div>
        <div class="detail-row">
            <span class="detail-label">Tools</span>
            <span class="detail-value">
                ${info.tools.map(t => `<span class="tool-tag">${t}</span>`).join('')}
            </span>
        </div>
        <div style="margin-top:16px;text-align:center;">
            <button onclick="selectAgent('${name}')" style="
                background: var(--accent);
                border: none;
                color: var(--bg-primary);
                padding: 8px 24px;
                border-radius: var(--radius-sm);
                cursor: pointer;
                font-weight: 600;
                font-size: 13px;
            ">Target this agent</button>
        </div>
    `;
    $modalOverlay.classList.remove('hidden');
}

function selectAgent(name) {
    targetAgent = name;
    $agentBadgeName.textContent = `⚡ ${name} agent`;
    $agentBadge.classList.remove('hidden');
    $modalOverlay.classList.add('hidden');
    $input.focus();
}

// ── Event Listeners ─────────────────────────────
function setupEventListeners() {
    // Send
    $sendBtn.addEventListener('click', sendMessage);
    $input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Auto-resize textarea
    $input.addEventListener('input', () => {
        $input.style.height = 'auto';
        $input.style.height = Math.min($input.scrollHeight, 160) + 'px';
    });

    // Agent panel toggle
    document.getElementById('btn-agents').addEventListener('click', () => {
        $agentPanel.classList.toggle('panel-hidden');
        document.getElementById('btn-agents').classList.toggle('active');
    });
    document.getElementById('btn-close-agents').addEventListener('click', () => {
        $agentPanel.classList.add('panel-hidden');
        document.getElementById('btn-agents').classList.remove('active');
    });

    // Voice toggle
    document.getElementById('btn-voice').addEventListener('click', toggleVoice);

    // Agent badge dismiss
    $agentBadgeDismiss.addEventListener('click', () => {
        targetAgent = null;
        $agentBadge.classList.add('hidden');
    });

    // Modal close
    document.getElementById('btn-close-modal').addEventListener('click', () => {
        $modalOverlay.classList.add('hidden');
    });
    $modalOverlay.addEventListener('click', (e) => {
        if (e.target === $modalOverlay) $modalOverlay.classList.add('hidden');
    });

    // Settings button (placeholder)
    document.getElementById('btn-settings').addEventListener('click', () => {
        showSettingsModal();
    });

    // Periodic health check
    setInterval(checkHealth, 30000);
}

// ── Send Message ────────────────────────────────
async function sendMessage() {
    const text = $input.value.trim();
    if (!text || isSending) return;

    // Check for /agent command
    const agentMatch = text.match(/^\/agent\s+(\w+)\s+(.*)/s);
    let message = text;
    let directAgent = targetAgent;

    if (agentMatch) {
        directAgent = agentMatch[1];
        message = agentMatch[2];
    }

    // Add user message
    addMessage('user', message);
    $input.value = '';
    $input.style.height = 'auto';
    isSending = true;
    $sendBtn.disabled = true;
    setStatus('thinking', 'THINKING...');

    // Show thinking indicator
    const thinkingEl = addThinking();

    try {
        let url, body;
        if (directAgent) {
            url = `${API_BASE}/agents/run`;
            body = { agent: directAgent, task: message };
        } else {
            url = `${API_BASE}/chat`;
            body = { message };
        }

        const resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        const data = await resp.json();
        thinkingEl.remove();

        if (data.error && !data.response) {
            addMessage('error', data.error);
        } else {
            addAssistantMessage(data);
        }

        setStatus('online', `ONLINE — ${data.agent || 'chat'} agent`);
    } catch (err) {
        thinkingEl.remove();
        addMessage('error', `Connection failed: ${err.message}`);
        setStatus('offline', 'OFFLINE');
    } finally {
        isSending = false;
        $sendBtn.disabled = false;
        $input.focus();
    }
}

// ── Message Rendering ───────────────────────────
function addMessage(type, text) {
    const div = document.createElement('div');
    div.className = `message ${type}`;

    const labels = {
        user: 'YOU',
        assistant: 'JAN',
        system: 'SYSTEM',
        error: 'ERROR',
    };

    div.innerHTML = `
        <div class="msg-content">
            <span class="msg-label">${labels[type] || type.toUpperCase()}</span>
            <p>${escapeHtml(text)}</p>
        </div>
    `;
    $messages.appendChild(div);
    scrollToBottom();
    return div;
}

function addAssistantMessage(data) {
    const div = document.createElement('div');
    div.className = 'message assistant';

    const response = data.response || 'No response';
    const agent = data.agent || 'unknown';
    const steps = data.steps || [];
    const stepCount = data.steps_taken || steps.length || 0;
    const reason = data.classification_reason || '';

    let stepsHtml = '';
    if (steps.length > 0) {
        const stepId = 'steps-' + Date.now();
        const stepLines = steps.map(s => {
            const tool = s.tool || s.delegated_to || '';
            const thought = s.thought || '';
            return `<div class="step-line">
                <span class="step-num">#${s.step || '?'}</span>
                ${tool ? `<span class="step-tool">${tool}</span>` : ''}
                ${thought ? `<span class="step-thought"> — ${escapeHtml(thought)}</span>` : ''}
            </div>`;
        }).join('');

        stepsHtml = `
            <button class="msg-steps-toggle" onclick="this.nextElementSibling.classList.toggle('expanded')">
                ▸ ${stepCount} step${stepCount !== 1 ? 's' : ''} taken
            </button>
            <div class="msg-steps" id="${stepId}">${stepLines}</div>
        `;
    }

    div.innerHTML = `
        <div class="msg-content">
            <span class="msg-label">JAN</span>
            <p>${formatResponse(response)}</p>
            <div class="msg-agent-info">
                <span class="msg-agent-tag">${agent}</span>
                ${reason ? `<span>${escapeHtml(reason)}</span>` : ''}
            </div>
            ${stepsHtml}
        </div>
    `;
    $messages.appendChild(div);
    scrollToBottom();
}

function addThinking() {
    const div = document.createElement('div');
    div.className = 'message assistant';
    div.innerHTML = `
        <div class="msg-content">
            <span class="msg-label">JAN</span>
            <div class="thinking-dots">
                <span></span><span></span><span></span>
            </div>
        </div>
    `;
    $messages.appendChild(div);
    scrollToBottom();
    return div;
}

// ── Voice Toggle ────────────────────────────────
async function toggleVoice() {
    try {
        const resp = await fetch(`${API_BASE}/voice/toggle`, { method: 'POST' });
        const data = await resp.json();
        voiceEnabled = data.auto_voice;
        updateVoiceBtn();
    } catch {
        // ignore
    }
}

function updateVoiceBtn() {
    const btn = document.getElementById('btn-voice');
    btn.innerHTML = `<span class="icon">${voiceEnabled ? '🔊' : '🔇'}</span>`;
    btn.classList.toggle('active', voiceEnabled);
}

// ── Settings Modal ──────────────────────────────
function showSettingsModal() {
    $modalTitle.textContent = 'SETTINGS';
    $modalBody.innerHTML = `
        <div class="detail-row">
            <span class="detail-label">Voice</span>
            <span class="detail-value">${voiceEnabled ? 'On' : 'Off'}</span>
        </div>
        <div class="detail-row">
            <span class="detail-label">Agents Loaded</span>
            <span class="detail-value">${Object.keys(agents).length}</span>
        </div>
        <div class="detail-row">
            <span class="detail-label">Backend</span>
            <span class="detail-value">${API_BASE}</span>
        </div>
        <div style="margin-top:16px;color:var(--text-muted);font-size:12px;text-align:center;">
            Configure agents and models in <code>config.yaml</code>
        </div>
    `;
    $modalOverlay.classList.remove('hidden');
}

// ── Helpers ─────────────────────────────────────
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatResponse(text) {
    // Basic formatting: convert markdown-ish to HTML
    let html = escapeHtml(text);
    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code style="background:var(--bg-primary);padding:1px 6px;border-radius:4px;font-family:var(--font-mono);font-size:12px;">$1</code>');
    // Line breaks
    html = html.replace(/\n/g, '<br>');
    return html;
}

function scrollToBottom() {
    requestAnimationFrame(() => {
        $messages.scrollTop = $messages.scrollHeight;
    });
}
