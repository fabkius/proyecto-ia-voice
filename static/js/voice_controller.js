// voice_controller.js - Conversación fluida SIN modificar tu diseño
let mediaRecorderConversacion = null;
let audioChunksConversacion = [];
let isConversacionActiva = false;
let isSpeakingConversacion = false;
let silenceTimerConversacion = null;
let audioContextConversacion = null;

let thresholdVolumen = 0.015;
let delaySilencio = 1500;

// Iniciar modo conversación continua
async function iniciarConversacionFluida() {
    if (isConversacionActiva) return;
    
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        
        audioContextConversacion = new AudioContext();
        const source = audioContextConversacion.createMediaStreamSource(stream);
        const processor = audioContextConversacion.createScriptProcessor(4096, 1, 1);
        
        source.connect(processor);
        processor.connect(audioContextConversacion.destination);
        
        mediaRecorderConversacion = new MediaRecorder(stream);
        mediaRecorderConversacion.ondataavailable = (event) => {
            if (event.data.size > 0) {
                audioChunksConversacion.push(event.data);
            }
        };
        
        mediaRecorderConversacion.onstop = () => {
            if (audioChunksConversacion.length > 0) {
                const audioBlob = new Blob(audioChunksConversacion, { type: 'audio/wav' });
                enviarAudioVoz(audioBlob);
                audioChunksConversacion = [];
            }
        };
        
        let lastVolumeTime = Date.now();
        
        processor.onaudioprocess = (event) => {
            if (!isConversacionActiva) return;
            
            const inputData = event.inputBuffer.getChannelData(0);
            let volume = 0;
            for (let i = 0; i < inputData.length; i++) {
                volume += Math.abs(inputData[i]);
            }
            volume = volume / inputData.length;
            
            if (volume > thresholdVolumen) {
                lastVolumeTime = Date.now();
                if (silenceTimerConversacion) {
                    clearTimeout(silenceTimerConversacion);
                    silenceTimerConversacion = null;
                }
                if (!isSpeakingConversacion) {
                    isSpeakingConversacion = true;
                    audioChunksConversacion = [];
                    mediaRecorderConversacion.start(100);
                    mostrarNotificacion('🎙️ Hablando...');
                }
            } else if (isSpeakingConversacion && !silenceTimerConversacion && (Date.now() - lastVolumeTime) > 200) {
                silenceTimerConversacion = setTimeout(() => {
                    if (isSpeakingConversacion) {
                        mediaRecorderConversacion.stop();
                        isSpeakingConversacion = false;
                        mostrarNotificacion('🔄 Procesando...');
                    }
                    silenceTimerConversacion = null;
                }, delaySilencio);
            }
        };
        
        await audioContextConversacion.resume();
        isConversacionActiva = true;
        mostrarNotificacion('🎤 Modo conversación activado - Habla libremente');
        
    } catch (error) {
        console.error('Error:', error);
        mostrarNotificacion('❌ Error: Permiso de micrófono denegado');
    }
}

function detenerConversacionFluida() {
    isConversacionActiva = false;
    
    if (silenceTimerConversacion) {
        clearTimeout(silenceTimerConversacion);
        silenceTimerConversacion = null;
    }
    
    if (mediaRecorderConversacion && mediaRecorderConversacion.state === 'recording') {
        mediaRecorderConversacion.stop();
    }
    
    if (audioContextConversacion) {
        audioContextConversacion.close();
    }
    
    mostrarNotificacion('🔇 Modo conversación desactivado');
}

async function enviarAudioVoz(audioBlob) {
    const formData = new FormData();
    formData.append('audio', audioBlob);
    
    try {
        // Usar tu ruta EXISTENTE de transcripción
        const response = await fetch('/transcribir', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.texto && data.texto.trim()) {
            // Simular que se escribió en el input y se envió
            const inputElement = document.querySelector('input[type="text"], textarea, #user-input');
            if (inputElement) {
                inputElement.value = data.texto;
                // Disparar el evento de envío de tu interfaz
                const botonEnviar = document.querySelector('button[type="submit"], #send-btn, .enviar');
                if (botonEnviar) {
                    botonEnviar.click();
                }
            }
        }
    } catch (error) {
        console.error('Error:', error);
    }
}

function mostrarNotificacion(mensaje) {
    // Crear notificación flotante temporal (no afecta tu diseño)
    let notif = document.getElementById('voiceNotification');
    if (!notif) {
        notif = document.createElement('div');
        notif.id = 'voiceNotification';
        notif.style.cssText = `
            position: fixed;
            bottom: 20px;
            left: 20px;
            background: #333;
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 12px;
            z-index: 10000;
            font-family: monospace;
            opacity: 0.9;
            pointer-events: none;
        `;
        document.body.appendChild(notif);
    }
    notif.textContent = mensaje;
    notif.style.opacity = '0.9';
    setTimeout(() => {
        notif.style.opacity = '0';
    }, 2000);
}

// Exponer funciones globalmente
window.iniciarConversacionFluida = iniciarConversacionFluida;
window.detenerConversacionFluida = detenerConversacionFluida;