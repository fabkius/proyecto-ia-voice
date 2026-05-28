from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import subprocess
import os
import json
import tempfile
from datetime import datetime
import requests
import threading
import base64

# Importar módulos existentes
from config_loader import config
from database import db

app = Flask(__name__)
app.config['SECRET_KEY'] = 'tu-clave-secreta-aqui'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Variable global para el historial de conversación actual
conversation_histories = {}

class WebConversationHistory:
    """Adaptador del historial para la web"""
    def __init__(self, session_id=None, session_name=None):
        self.session_id = session_id
        self.session_name = session_name
        self.messages = []
        
        if self.session_id:
            # Cargar historial existente
            self.messages = db.get_recent_messages(self.session_id, 50)
        else:
            # Crear nueva sesión
            self.session_id = db.create_session(session_name)
    
    def add_message(self, role, content):
        self.messages.append({"role": role, "content": content})
        db.save_message(self.session_id, role, content)
    
    def get_messages(self):
        return self.messages
    
    def clear(self):
        db.clear_session(self.session_id)
        system_prompt = config.get('system_prompt')
        self.messages = [{"role": "system", "content": system_prompt}]

@app.route('/')
def index():
    """Página principal"""
    return render_template('index.html')

@app.route('/api/sessions')
def get_sessions():
    """Obtener todas las sesiones"""
    sessions = db.list_sessions()
    return jsonify(sessions)

@app.route('/api/session/create', methods=['POST'])
def create_session():
    """Crear una nueva sesión"""
    data = request.json
    session_name = data.get('name', f"Sesión {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    session_id = db.create_session(session_name)
    return jsonify({"session_id": session_id, "session_name": session_name})

@app.route('/api/session/load/<session_id>')
def load_session(session_id):
    """Cargar una sesión existente"""
    messages = db.get_recent_messages(session_id, 50)
    session_info = db.get_session_info(session_id)
    return jsonify({
        "session_id": session_id,
        "session_name": session_info['session_name'],
        "messages": messages
    })

@app.route('/api/session/delete/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    """Eliminar una sesión"""
    success = db.delete_session(session_id)
    return jsonify({"success": success})

@app.route('/api/voices')
def get_voices():
    """Obtener lista de voces disponibles"""
    try:
        voices = {}
        voices_dir = config.get('piper.voices_dir')
        
        for voice_key, voice_info in config.get('piper.voices', {}).items():
            # Verificar si el archivo existe
            onnx_path = os.path.join(voices_dir, voice_info['files'][0])
            exists = os.path.exists(onnx_path)
            
            voices[voice_key] = {
                "name": voice_info['name'],
                "exists": exists,
                "file": voice_info['files'][0]
            }
        
        # También añadir la voz por defecto
        default_voice = config.get('piper.default_voice')
        
        return jsonify({
            "voices": voices,
            "default": default_voice
        })
        
    except Exception as e:
        print(f"Error en /api/voices: {e}")
        return jsonify({"error": str(e), "voices": {}}), 500

@app.route('/api/transcribe', methods=['POST'])
def transcribe_audio():
    """Transcribir audio usando Whisper"""
    if 'audio' not in request.files:
        return jsonify({"error": "No se recibió audio"}), 400
    
    audio_file = request.files['audio']
    session_id = request.form.get('session_id')
    
    # Guardar archivo temporal
    temp_dir = tempfile.mkdtemp()
    audio_path = os.path.join(temp_dir, "audio.wav")
    audio_file.save(audio_path)
    
    try:
        # Configuración de Whisper
        whisper_lang = config.get('whisper.language')
        whisper_model = config.get('whisper.model')
        
        # Transcribir
        transcribe_command = [
            'whisper', audio_path,
            '--language', whisper_lang,
            '--model', whisper_model,
            '--output_format', 'txt',
            '--output_dir', temp_dir
        ]
        
        result = subprocess.run(transcribe_command, capture_output=True, text=True)
        
        # Leer transcripción
        txt_output = os.path.join(temp_dir, "audio.txt")
        if os.path.exists(txt_output):
            with open(txt_output, 'r', encoding='utf-8') as f:
                transcription = f.read().strip()
        else:
            transcription = result.stdout.strip()
        
        # Limpiar archivos temporales
        import shutil
        shutil.rmtree(temp_dir)
        
        return jsonify({"text": transcription})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    """Enviar mensaje a Ollama y obtener respuesta"""
    data = request.json
    message = data.get('message')
    session_id = data.get('session_id')
    voice = data.get('voice', config.get('piper.default_voice'))
    
    if not message:
        return jsonify({"error": "Mensaje vacío"}), 400
    
    # Obtener o crear historial
    if session_id not in conversation_histories:
        history = WebConversationHistory(session_id=session_id)
        conversation_histories[session_id] = history
    else:
        history = conversation_histories[session_id]
    
    # Agregar mensaje del usuario
    history.add_message("user", message)
    
    # Preparar payload para Ollama
    api_url = config.get('ollama.api_url')
    ollama_model = config.get('ollama.model')
    
    payload = {
        "model": ollama_model,
        "messages": history.get_messages(),
        "stream": False,
        "options": {
            "temperature": config.get('ollama.temperature'),
            "top_p": config.get('ollama.top_p'),
            "top_k": config.get('ollama.top_k')
        }
    }
    
    try:
        response = requests.post(api_url, json=payload, timeout=60)
        response.raise_for_status()
        
        data = response.json()
        result_text = data.get("message", {}).get("content", "No se recibió respuesta")
        
        # Agregar respuesta del asistente
        history.add_message("assistant", result_text)
        
        # Generar audio si está habilitado
        audio_data = None
        if data.get('speak', True):
            audio_data = generate_speech(result_text, voice)
        
        return jsonify({
            "response": result_text,
            "audio": audio_data,
            "session_id": history.session_id
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def generate_speech(text, voice_name):
    """Generar audio a partir de texto usando Piper"""
    try:
        voice_info = config.get_voice_info(voice_name)
        voice_model_path = voice_info['onnx_path']
        
        if not os.path.exists(voice_model_path):
            return None
        
        # Crear archivo temporal
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
            wav_file = tmp_file.name
        
        # Generar WAV con Piper
        cmd = ['piper', '--model', voice_model_path, '--output_file', wav_file]
        process = subprocess.run(cmd, input=text, text=True, capture_output=True)
        
        if process.returncode == 0 and os.path.exists(wav_file):
            # Leer el archivo y convertirlo a base64
            with open(wav_file, 'rb') as f:
                audio_bytes = f.read()
            
            # Limpiar archivo temporal
            os.unlink(wav_file)
            
            # Convertir a base64
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            return audio_base64
        
        return None
        
    except Exception as e:
        print(f"Error generando audio: {e}")
        return None

@app.route('/api/tts', methods=['POST'])
def text_to_speech():
    """Convertir texto a audio"""
    data = request.json
    text = data.get('text')
    voice = data.get('voice', config.get('piper.default_voice'))
    
    if not text:
        return jsonify({"error": "Texto vacío"}), 400
    
    audio_base64 = generate_speech(text, voice)
    if audio_base64:
        return jsonify({"audio": audio_base64})
    else:
        return jsonify({"error": "Error generando audio"}), 500

@app.route('/api/backup', methods=['POST'])
def backup_database():
    """Crear respaldo de la base de datos"""
    backup_path = db.backup_database()
    return jsonify({"backup_path": backup_path})

@socketio.on('connect')
def handle_connect():
    """Manejar conexión WebSocket"""
    print('Cliente conectado')

@socketio.on('disconnect')
def handle_disconnect():
    """Manejar desconexión WebSocket"""
    print('Cliente desconectado')

if __name__ == '__main__':
    print("="*60)
    print("🌐 INICIANDO SERVIDOR WEB")
    print("="*60)
    print(f"📱 Accede a la interfaz en: http://localhost:5000")
    print(f"🛑 Presiona Ctrl+C para detener el servidor")
    print("="*60)
    socketio.run(app, debug=True, port=5000)