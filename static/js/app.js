// Estado de la aplicación
let currentSessionId = null;
let currentVoice = 'es_MX-claude-high';
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

// Elementos DOM
const sessionsContainer = document.getElementById('sessionsContainer');
const chatMessages = document.getElementById('chatMessages');
const textInput = document.getElementById('textInput');
const sendBtn = document.getElementById('sendBtn');
const voiceInputBtn = document.getElementById('voiceInputBtn');
const voiceSelect = document.getElementById('voiceSelect');
const newSessionBtn = document.getElementById('newSessionBtn');
const backupBtn = document.getElementById('backupBtn');
const sessionTitle = document.getElementById('sessionTitle');
const statusText = document.getElementById('statusText');
const recordingIndicator = document.getElementById('recordingIndicator');
const audioPlayer = document.getElementById('audioPlayer');

// Inicializar
document.addEventListener('DOMContentLoaded', () => {
    loadSessions();
    loadVoices();
    setupEventListeners();
});

function setupEventListeners() {
    sendBtn.addEventListener('click', sendMessage);
    textInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    voiceInputBtn.addEventListener('click', toggleRecording);
    newSessionBtn.addEventListener('click', createNewSession);
    backupBtn.addEventListener('click', createBackup);
    voiceSelect.addEventListener('change', (e) => {
        currentVoice = e.target.value;
        updateStatus('Voz cambiada');
    });
}

async function loadSessions() {
    try {
        const response = await fetch('/api/sessions');
        const sessions = await response.json();
        
        sessionsContainer.innerHTML = '';
        sessions.forEach(session => {
            const sessionEl = createSessionElement(session);
            sessionsContainer.appendChild(sessionEl);
        });
        
        if (sessions.length > 0 && !currentSessionId) {
            loadSession(sessions[0].session_id);
        } else if (sessions.length === 0) {
            createNewSession();
        }
    } catch (error) {
        console.error('Error cargando sesiones:', error);
    }
}

function createSessionElement(session) {
    const div = document.createElement('div');
    div.className = 'session-item';
    if (currentSessionId === session.session_id) {
        div.classList.add('active');
    }
    div.innerHTML = `
        <div class="session-name">${escapeHtml(session.session_name)}</div>
        <div class="session-info">${session.message_count} mensajes</div>
    `;
    div.addEventListener('click', () => loadSession(session.session_id));
    
    // Botón de eliminar
    const deleteBtn = document.createElement('button');
    deleteBtn.textContent = '🗑️';
    deleteBtn.style.cssText = `
        float: right;
        background: none;
        border: none;
        cursor: pointer;
        font-size: 14px;
        opacity: 0.5;
    `;
    deleteBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if (confirm('¿Eliminar esta conversación?')) {
            await fetch(`/api/session/delete/${session.session_id}`, { method: 'DELETE' });
            loadSessions();
            if (currentSessionId === session.session_id) {
                createNewSession();
            }
        }
    });
    div.appendChild(deleteBtn);
    
    return div;
}

async function loadSession(sessionId) {
    try {
        const response = await fetch(`/api/session/load/${sessionId}`);
        const data = await response.json();
        
        currentSessionId = sessionId;
        sessionTitle.textContent = data.session_name;
        
        // Limpiar mensajes
        chatMessages.innerHTML = '';
        
        // Mostrar mensajes
        data.messages.forEach(msg => {
            if (msg.role !== 'system') {
                addMessageToChat(msg.role, msg.content);
            }
        });
        
        // Actualizar sesiones activas
        document.querySelectorAll('.session-item').forEach(el => {
            el.classList.remove('active');
        });
        loadSessions();
        
        updateStatus('Sesión cargada');
    } catch (error) {
        console.error('Error cargando sesión:', error);
    }
}

async function createNewSession() {
    const name = prompt('Nombre de la conversación:', `Conversación ${new Date().toLocaleString()}`);
    if (name) {
        const response = await fetch('/api/session/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name })
        });
        const data = await response.json();
        await loadSession(data.session_id);
    }
}

async function loadVoices() {
    try {
        const response = await fetch('/api/voices');
        const data = await response.json();
        
        if (data.error) {
            console.error('Error cargando voces:', data.error);
            return;
        }
        
        const voices = data.voices;
        const defaultVoice = data.default;
        
        voiceSelect.innerHTML = '<option value="">Seleccionar voz...</option>';
        
        let hasAvailableVoice = false;
        
        for (const [key, voice] of Object.entries(voices)) {
            const option = document.createElement('option');
            option.value = key;
            option.textContent = `${voice.name} ${voice.exists ? '✅' : '❌ (no descargada)'}`;
            option.disabled = !voice.exists;
            
            if (voice.exists) {
                hasAvailableVoice = true;
                if (key === defaultVoice) {
                    option.selected = true;
                    currentVoice = key;
                }
            }
            
            voiceSelect.appendChild(option);
        }
        
        if (!hasAvailableVoice) {
            console.warn('No hay voces disponibles. Descarga un modelo de voz.');
            updateStatus('⚠️ No hay voces disponibles. Descarga un modelo primero.');
        } else {
            updateStatus('Voces cargadas correctamente');
        }
        
    } catch (error) {
        console.error('Error cargando voces:', error);
        updateStatus('❌ Error cargando las voces');
    }
}

async function sendMessage() {
    const message = textInput.value.trim();
    if (!message) return;
    
    // Agregar mensaje del usuario al chat
    addMessageToChat('user', message);
    textInput.value = '';
    
    // Mostrar indicador de escritura
    showTypingIndicator();
    
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                session_id: currentSessionId,
                voice: currentVoice,
                speak: true
            })
        });
        
        const data = await response.json();
        
        // Ocultar indicador de escritura
        hideTypingIndicator();
        
        if (data.error) {
            addMessageToChat('assistant', `❌ Error: ${data.error}`);
        } else {
            addMessageToChat('assistant', data.response);
            
            // Reproducir audio si está disponible
            if (data.audio) {
                playAudio(data.audio);
            }
            
            // Actualizar sesión
            if (data.session_id !== currentSessionId) {
                currentSessionId = data.session_id;
                loadSessions();
            }
        }
    } catch (error) {
        hideTypingIndicator();
        addMessageToChat('assistant', `❌ Error: ${error.message}`);
    }
}

async function toggleRecording() {
    if (isRecording) {
        stopRecording();
    } else {
        startRecording();
    }
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
        
        mediaRecorder.ondataavailable = (event) => {
            audioChunks.push(event.data);
        };
        
        mediaRecorder.onstop = async () => {
            const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
            await sendAudioToServer(audioBlob);
            stream.getTracks().forEach(track => track.stop());
            isRecording = false;
            voiceInputBtn.classList.remove('recording');
            recordingIndicator.style.display = 'none';
            updateStatus('Procesando audio...');
        };
        
        mediaRecorder.start();
        isRecording = true;
        voiceInputBtn.classList.add('recording');
        recordingIndicator.style.display = 'flex';
        updateStatus('Grabando...');
        
        // Detener después de 10 segundos máximo
        setTimeout(() => {
            if (isRecording) {
                stopRecording();
            }
        }, 10000);
        
    } catch (error) {
        console.error('Error accediendo al micrófono:', error);
        updateStatus('❌ Error con el micrófono');
    }
}

function stopRecording() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
    }
}

async function sendAudioToServer(audioBlob) {
    const formData = new FormData();
    formData.append('audio', audioBlob, 'audio.wav');
    formData.append('session_id', currentSessionId);
    
    addMessageToChat('user', '🎤 [Audio grabado]');
    showTypingIndicator();
    
    try {
        // Transcribir audio
        const transcribeResponse = await fetch('/api/transcribe', {
            method: 'POST',
            body: formData
        });
        
        const transcribeData = await transcribeResponse.json();
        
        if (transcribeData.error) {
            hideTypingIndicator();
            addMessageToChat('assistant', `❌ Error transcribiendo: ${transcribeData.error}`);
            return;
        }
        
        // Reemplazar mensaje de audio con texto transcrito
        const lastMessage = chatMessages.lastElementChild;
        if (lastMessage && lastMessage.querySelector('.message.user')) {
            lastMessage.querySelector('.message-content').innerHTML = `🎤 ${escapeHtml(transcribeData.text)}`;
        }
        
        // Enviar a chat
        const chatResponse = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: transcribeData.text,
                session_id: currentSessionId,
                voice: currentVoice,
                speak: true
            })
        });
        
        const chatData = await chatResponse.json();
        
        hideTypingIndicator();
        
        if (chatData.error) {
            addMessageToChat('assistant', `❌ Error: ${chatData.error}`);
        } else {
            addMessageToChat('assistant', chatData.response);
            
            if (chatData.audio) {
                playAudio(chatData.audio);
            }
        }
        
        updateStatus('Listo');
        
    } catch (error) {
        hideTypingIndicator();
        addMessageToChat('assistant', `❌ Error: ${error.message}`);
        updateStatus('Error');
    }
}

function addMessageToChat(role, content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    messageDiv.innerHTML = `<div class="message-content">${formatMessage(content)}</div>`;
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function showTypingIndicator() {
    const indicator = document.createElement('div');
    indicator.className = 'message assistant typing-indicator';
    indicator.id = 'typingIndicator';
    indicator.innerHTML = '<div class="message-content">🤔 Pensando...</div>';
    chatMessages.appendChild(indicator);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function hideTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) {
        indicator.remove();
    }
}

function playAudio(base64Audio) {
    const audioData = base64ToArrayBuffer(base64Audio);
    const audioBlob = new Blob([audioData], { type: 'audio/wav' });
    const audioUrl = URL.createObjectURL(audioBlob);
    audioPlayer.src = audioUrl;
    audioPlayer.play();
    
    audioPlayer.onended = () => {
        URL.revokeObjectURL(audioUrl);
    };
}

async function createBackup() {
    try {
        const response = await fetch('/api/backup', { method: 'POST' });
        const data = await response.json();
        updateStatus(`💾 Respaldo creado: ${data.backup_path}`);
    } catch (error) {
        console.error('Error creando respaldo:', error);
        updateStatus('❌ Error creando respaldo');
    }
}

function updateStatus(message) {
    statusText.textContent = message;
    setTimeout(() => {
        if (statusText.textContent === message) {
            statusText.textContent = 'Listo';
        }
    }, 3000);
}

function formatMessage(text) {
    // Convertir URLs a enlaces
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    text = text.replace(urlRegex, (url) => `<a href="${url}" target="_blank">${url}</a>`);
    
    // Convertir código en bloque
    text = text.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
        return `<pre><code class="language-${lang}">${escapeHtml(code)}</code></pre>`;
    });
    
    // Convertir inline code
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // Convertir saltos de línea
    text = text.replace(/\n/g, '<br>');
    
    return text;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function base64ToArrayBuffer(base64) {
    const binaryString = atob(base64);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes.buffer;
}