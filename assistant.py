import subprocess
from datetime import datetime
import requests
import os
import tempfile
import json
from config_loader import config
from database import db

# Función para generar nombre de archivo de audio
def generate_audio_file_name():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = config.get('audio.output_dir')
    # Asegurar que el directorio existe
    os.makedirs(output_dir, exist_ok=True)
    audio_file_path = f"{output_dir}/audio_{timestamp}.wav"
    return audio_file_path

# Función para grabar audio
def record_audio(audio_file_path, duration=None, sample_rate=None, channels=None):
    """
    Graba audio con opciones de calidad
    """
    # Usar valores de configuración si no se proporcionan
    if duration is None:
        duration = config.get('audio.duration')
    if sample_rate is None:
        sample_rate = config.get('audio.sample_rate')
    if channels is None:
        channels = config.get('audio.channels')
    
    quality_params = f"-ar {sample_rate} -ac {channels}"
    audio_input = config.get('audio.ffmpeg_input', 'default')
    
    if duration:
        record_command = f'ffmpeg -f pulse -i {audio_input} {quality_params} -t {duration} {audio_file_path} -y'
    else:
        record_command = f'ffmpeg -f pulse -i {audio_input} {quality_params} {audio_file_path} -y'
    
    print(f"🎙️ Grabando: {sample_rate}Hz, {channels} canales")
    print(f"📁 Archivo: {audio_file_path}")
    
    try:
        result = subprocess.run(record_command, shell=True, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"Error en grabación: {result.stderr}")
            
        print(f"✓ Audio guardado en {audio_file_path}")
        
    except KeyboardInterrupt:
        print("\n✓ Grabación detenida. Archivo guardado.")
    except Exception as e:
        print(f"✗ Error: {e}")
        raise
    
    return audio_file_path

# Función para convertir texto a voz
def speak_text(text, voice_name=None):
    """Convierte texto a audio usando Piper y lo reproduce correctamente."""
    # Obtener información de la voz
    if voice_name is None:
        voice_name = config.get('piper.default_voice')
    
    try:
        voice_info = config.get_voice_info(voice_name)
        voice_model_path = voice_info['onnx_path']
    except ValueError as e:
        print(f"❌ {e}")
        config.list_available_voices()
        return
    
    print(f"🔊 Generando audio con voz: {voice_info['name']}")
    
    # Crear archivo temporal para el WAV
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
        wav_file = tmp_file.name
    
    try:
        # Generar WAV con Piper
        cmd = [
            'piper',
            '--model', voice_model_path,
            '--output_file', wav_file
        ]
        
        # Pasar el texto a Piper
        process = subprocess.run(cmd, input=text, text=True, capture_output=True)
        
        if process.returncode != 0:
            print(f"❌ Error en Piper: {process.stderr}")
            return
        
        # Reproducir el archivo WAV
        subprocess.run(['aplay', wav_file], check=True)
        print("✅ Audio reproducido")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Error al reproducir: {e}")
    except FileNotFoundError as e:
        print(f"❌ Comando no encontrado: {e}")
    finally:
        # Limpiar archivo temporal
        if os.path.exists(wav_file):
            os.unlink(wav_file)

# Función para procesar audio y transcribir
def process_audio_and_transcribe(audio_file_path, conversation_history=None):
    """Transcribe audio con Whisper y procesa con Ollama usando /api/chat"""
    
    # Usar URLs y modelos desde configuración
    api_url = config.get('ollama.api_url')
    ollama_model = config.get('ollama.model')
    
    # Crear historial de conversación si no existe
    if conversation_history is None:
        system_prompt = config.get('system_prompt')
        conversation_history = ConversationHistory(system_prompt=system_prompt)
    
    # Verificar que el archivo existe
    if not os.path.exists(audio_file_path):
        raise FileNotFoundError(f"Archivo de audio no encontrado: {audio_file_path}")
    
    # Verificar que Ollama está corriendo
    try:
        requests.get("http://localhost:11434/api/tags", timeout=2)
    except requests.exceptions.ConnectionError:
        raise Exception("Ollama no está corriendo en http://localhost:11434")
    
    print("\n📝 Transcribiendo audio con Whisper...")
    
    # Configuración de Whisper desde config
    whisper_lang = config.get('whisper.language')
    whisper_model = config.get('whisper.model')
    
    # Usar Whisper con salida solo texto (sin timestamps)
    base_name = os.path.splitext(audio_file_path)[0]
    txt_output = f"{base_name}.txt"
    
    transcribe_command = [
        'whisper', audio_file_path,
        '--language', whisper_lang,
        '--model', whisper_model,
        '--output_format', 'txt',
        '--output_dir', os.path.dirname(audio_file_path)
    ]
    
    try:
        # Ejecutar Whisper
        result = subprocess.run(transcribe_command, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"Whisper failed: {result.stderr}")
        
        # Leer el archivo de texto generado
        if os.path.exists(txt_output):
            with open(txt_output, 'r', encoding='utf-8') as f:
                transcription_text = f.read().strip()
        else:
            # Fallback: intentar capturar desde stdout
            transcription_text = result.stdout.strip()
        
        if not transcription_text:
            raise Exception("No se obtuvo transcripción del audio")
        
        print(f"✓ Transcripción obtenida ({len(transcription_text)} caracteres)")
        print(f"\n--- Transcripción original ---\n{transcription_text}\n--- Fin transcripción ---\n")
        
    except Exception as e:
        print(f"✗ Error en transcripción: {e}")
        raise
    
    print(f"🤖 Enviando a Ollama ({ollama_model}) usando /api/chat...")
    
    # Agregar el mensaje del usuario al historial
    conversation_history.add_user_message(transcription_text)
    
    # Preparar el payload para la API /api/chat
    payload = {
        "model": ollama_model,
        "messages": conversation_history.get_messages(),
        "stream": False,
        "options": {
            "temperature": config.get('ollama.temperature'),
            "top_p": config.get('ollama.top_p'),
            "top_k": config.get('ollama.top_k')
        }
    }
    
    try:
        timeout = config.get('ollama.timeout')
        response = requests.post(api_url, json=payload, timeout=timeout)
        response.raise_for_status()
        
        data = response.json()
        # Para /api/chat, la respuesta está en data["message"]["content"]
        if "message" in data and "content" in data["message"]:
            result_text = data["message"]["content"]
        else:
            result_text = data.get("response", "No se recibió respuesta del modelo")
        
        # Agregar la respuesta del asistente al historial
        conversation_history.add_assistant_message(result_text)
        
        print("✓ Respuesta recibida de Ollama\n")
        return result_text, conversation_history
        
    except requests.exceptions.Timeout:
        raise Exception("Timeout: Ollama tardó demasiado en responder")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Error comunicándose con Ollama: {e}")

# Función para limpiar archivos temporales de Whisper
def cleanup_whisper_files(audio_file_path, keep_audio=True):
    """Limpia archivos temporales creados por Whisper"""
    base_name = os.path.splitext(audio_file_path)[0]
    extensions = ['.txt', '.vtt', '.srt', '.tsv', '.json']
    
    for ext in extensions:
        temp_file = f"{base_name}{ext}"
        if os.path.exists(temp_file):
            os.remove(temp_file)
            print(f"🗑️ Eliminado: {temp_file}")
    
    if not keep_audio and os.path.exists(audio_file_path):
        os.remove(audio_file_path)
        print(f"🗑️ Eliminado archivo de audio: {audio_file_path}")

# Función para descargar modelos de voz
def download_voice_model(voice_name=None):
    """Descarga un modelo de voz desde Hugging Face usando la configuración"""
    if voice_name is None:
        voice_name = config.get('piper.default_voice')
    
    try:
        voice_info = config.get_voice_info(voice_name)
    except ValueError as e:
        print(f"❌ {e}")
        config.list_available_voices()
        return False
    
    voices_dir = config.get('piper.voices_dir')
    os.makedirs(voices_dir, exist_ok=True)
    
    print(f"📥 Descargando modelo '{voice_name}': {voice_info['name']}")
    
    for file_name in voice_info['files']:
        # Determinar la extensión para obtener la URL correcta
        ext = file_name.split('.')[-1]
        url = voice_info['urls'][ext]
        output_path = os.path.join(voices_dir, file_name)
        
        print(f"  Descargando {file_name}...")
        
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"  ✅ Guardado en {output_path}")
            
        except Exception as e:
            print(f"  ❌ Error descargando {file_name}: {e}")
            return False
    
    print(f"✅ Modelo '{voice_name}' descargado correctamente")
    return True

# Clase para manejar el historial de conversación con SQLite
class ConversationHistory:
    def __init__(self, session_id=None, session_name=None):
        self.session_id = session_id
        self.max_messages = config.get('database.max_context_messages', 50)
        
        # Si no hay session_id, crear una nueva sesión
        if self.session_id is None:
            self.session_id = db.create_session(session_name)
        
        # Verificar que la sesión existe
        session_info = db.get_session_info(self.session_id)
        if not session_info:
            print(f"⚠️ Sesión {self.session_id} no encontrada, creando nueva...")
            self.session_id = db.create_session(session_name)
        
        # Cargar mensajes existentes
        self.messages = db.get_recent_messages(self.session_id, self.max_messages)
        
        # Agregar system prompt si es una sesión nueva (no hay mensajes)
        if len(self.messages) == 0:
            system_prompt = config.get('system_prompt')
            self.messages.insert(0, {"role": "system", "content": system_prompt})
            db.save_message(self.session_id, "system", system_prompt)
            
            # Recargar para incluir el system prompt
            self.messages = db.get_recent_messages(self.session_id, self.max_messages)
        
        session_info = db.get_session_info(self.session_id)
        print(f"📂 Sesión cargada: {session_info['session_name']} ({session_info['message_count']} mensajes)")
    
    def add_user_message(self, content):
        self.messages.append({"role": "user", "content": content})
        db.save_message(self.session_id, "user", content)
        self._trim_history()
    
    def add_assistant_message(self, content):
        self.messages.append({"role": "assistant", "content": content})
        db.save_message(self.session_id, "assistant", content)
        self._trim_history()
    
    def get_messages(self):
        # Devolver solo los mensajes necesarios para la API (sin metadata)
        return self.messages
    
    def get_last_user_message(self):
        for msg in reversed(self.messages):
            if msg["role"] == "user":
                return msg["content"]
        return None
    
    def clear(self):
        """Limpia la conversación actual pero mantiene la sesión"""
        db.clear_session(self.session_id)
        # Recargar solo el system prompt
        system_prompt = config.get('system_prompt')
        self.messages = [{"role": "system", "content": system_prompt}]
        print("✅ Historial limpiado")
    
    def get_context_length(self):
        return len(self.messages)
    
    def get_session_info(self):
        return db.get_session_info(self.session_id)
    
    def _trim_history(self):
        """Recorta el historial si excede el límite máximo"""
        # Mantener el system prompt (primer mensaje)
        if len(self.messages) > self.max_messages:
            self.messages = [self.messages[0]] + self.messages[-(self.max_messages-1):]

# Función principal de conversación interactiva
def interactive_conversation():
    """Función para mantener una conversación continua con el asistente"""
    print("\n" + "="*60)
    print("🎙️ ASISTENTE DE VOZ CON MEMORIA (SQLite)")
    print("="*60)
    
    # Mostrar sesiones disponibles
    sessions = db.list_sessions()
    
    session_id = None
    session_name = None
    
    if sessions:
        print("\n📚 Sesiones disponibles:")
        print("-" * 50)
        for i, session in enumerate(sessions):
            print(f"  {i}. {session['session_name']}")
            print(f"     Mensajes: {session['message_count']} | Último: {session['last_updated'][:19]}")
        print("-" * 50)
        
        print("\nOpciones:")
        print("  'n' - Crear nueva sesión")
        print("  'l' - Cargar sesión existente (ingresa número)")
        print("  'd' - Eliminar una sesión")
        print("  'b' - Crear respaldo de la base de datos")
        print("  ENTER - Continuar con la última sesión")
        
        choice = input("\nOpción: ").strip().lower()
        
        if choice == 'n':
            session_name = input("Nombre para la nueva sesión (opcional): ").strip()
            session_name = session_name if session_name else None
            session_id = db.create_session(session_name)
            
        elif choice == 'l':
            try:
                idx = int(input("Número de sesión a cargar: "))
                if 0 <= idx < len(sessions):
                    session_id = sessions[idx]['session_id']
                else:
                    print("Número inválido. Usando sesión más reciente.")
                    session_id = sessions[0]['session_id']
            except ValueError:
                print("Entrada inválida. Usando sesión más reciente.")
                session_id = sessions[0]['session_id']
                
        elif choice == 'd':
            try:
                idx = int(input("Número de sesión a eliminar: "))
                if 0 <= idx < len(sessions):
                    if db.delete_session(sessions[idx]['session_id']):
                        print("✅ Sesión eliminada")
                        # Recargar sesiones
                        return interactive_conversation()
                else:
                    print("Número inválido")
                    return interactive_conversation()
            except ValueError:
                print("Entrada inválida")
                return interactive_conversation()
                
        elif choice == 'b':
            backup_path = db.backup_database()
            print(f"💾 Respaldo creado en: {backup_path}")
            return interactive_conversation()
            
        else:
            # Usar la sesión más reciente
            session_id = sessions[0]['session_id']
    else:
        print("\n📝 No hay sesiones guardadas. Creando nueva sesión...")
        session_name = input("Nombre para la sesión (opcional): ").strip()
        session_name = session_name if session_name else None
    
    # Crear historial de conversación
    conversation_history = ConversationHistory(session_id=session_id, session_name=session_name)
    session_info = conversation_history.get_session_info()
    
    print(f"\n💬 Sesión actual: {session_info['session_name']}")
    print(f"📊 Mensajes en contexto: {session_info['message_count']}")
    
    print("\nInstrucciones:")
    print("- Presiona ENTER para grabar tu pregunta")
    print("- Escribe 'salir' para terminar")
    print("- Escribe 'nueva sesión' para empezar una conversación nueva")
    print("- Escribe 'borrar historial' para limpiar la conversación actual")
    print("- Escribe 'sesiones' para listar todas las sesiones")
    print("- Escribe 'respaldo' para crear un respaldo de la base de datos")
    print("="*60 + "\n")
    
    current_voice = config.get('piper.default_voice')
    interaction_count = session_info['message_count'] // 2  # Aprox número de intercambios
    
    while True:
        user_input = input("🎤 Presiona ENTER para grabar (o escribe un comando): ").strip().lower()
        
        if user_input == 'salir':
            print("\n👋 ¡Hasta luego!")
            session_info = conversation_history.get_session_info()
            print(f"💾 Conversación guardada: {session_info['session_name']} ({session_info['message_count']} mensajes)")
            break
            
        elif user_input == 'nueva sesión':
            session_name = input("Nombre para la nueva sesión (opcional): ").strip()
            conversation_history = ConversationHistory(session_name=session_name if session_name else None)
            interaction_count = 0
            print("✅ Nueva sesión iniciada")
            continue
            
        elif user_input == 'borrar historial':
            conversation_history.clear()
            continue
            
        elif user_input == 'sesiones':
            sessions = db.list_sessions()
            print("\n📚 Sesiones guardadas:")
            print("-" * 50)
            for session in sessions:
                print(f"  • {session['session_name']}")
                print(f"    ID: {session['session_id']}")
                print(f"    Mensajes: {session['message_count']}")
                print(f"    Último: {session['last_updated'][:19]}")
                print()
            continue
            
        elif user_input == 'respaldo':
            backup_path = db.backup_database()
            print(f"💾 Respaldo creado: {backup_path}")
            continue
            
        elif user_input == 'exportar':
            # Exportar sesión actual a JSON
            export_path = db.export_session_to_json(conversation_history.session_id)
            print(f"📄 Sesión exportada: {export_path}")
            continue
            
        elif user_input == '':
            # Continuar con grabación
            pass
            
        else:
            print("Comando no reconocido. Opciones: 'salir', 'nueva sesión', 'borrar historial', 'sesiones', 'respaldo', 'exportar'")
            continue
        
        try:
            # Grabar audio
            audio_file_path = generate_audio_file_name()
            print("🎙️ Grabando...")
            audio_file_path = record_audio(
                audio_file_path, 
                duration=config.get('audio.duration')
            )
            
            # Procesar y obtener respuesta
            result, conversation_history = process_audio_and_transcribe(
                audio_file_path, 
                conversation_history
            )
            
            # Mostrar resultado
            interaction_count += 1
            print(f"\n💬 Respuesta #{interaction_count}:")
            print("-" * 50)
            print(result)
            print("-" * 50)
            
            # Reproducir respuesta
            speak_text(result, voice_name=current_voice)
            
            # Limpiar archivos temporales
            cleanup_whisper_files(audio_file_path, keep_audio=False)
            
        except KeyboardInterrupt:
            print("\n\n👋 ¡Hasta luego!")
            session_info = conversation_history.get_session_info()
            print(f"💾 Conversación guardada: {session_info['session_name']} ({session_info['message_count']} mensajes)")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            print("Continuando...\n")

# ============ AGREGA ESTA FUNCIÓN SI NO EXISTE ============

def transcribir_audio(ruta_audio):
    """
    Transcribe un archivo de audio usando Whisper
    
    Args:
        ruta_audio (str): Ruta al archivo de audio
    
    Returns:
        str: Texto transcrito
    """
    import whisper
    
    # Cargar modelo (puedes ajustar el tamaño)
    model = whisper.load_model("base")
    
    # Transcribir
    result = model.transcribe(ruta_audio, language="es")
    
    return result["text"]
            

# Punto de entrada principal
if __name__ == "__main__":
    # Verificar que los modelos de voz existen
    default_voice = config.get('piper.default_voice')
    voice_info = config.get_voice_info(default_voice)
    voice_model_path = voice_info['onnx_path']
    
    if not os.path.exists(voice_model_path):
        print(f"⚠️ No se encontró el modelo de voz en {voice_model_path}")
        print(f"   Voz requerida: {voice_info['name']}")
        print("\n   ¿Deseas descargarlo automáticamente? (s/n): ")
        respuesta = input().lower()
        
        if respuesta == 's':
            print("\n📥 Iniciando descarga del modelo...")
            if download_voice_model(default_voice):
                print("\n✅ Modelo descargado. Iniciando asistente...\n")
            else:
                print("\n❌ Error al descargar el modelo.")
                print("   Puedes descargarlo manualmente desde:")
                print(f"   {voice_info['urls']['onnx']}")
                exit(1)
        else:
            print("\n⚠️ Continuando sin voz...")
    
    # Modo conversación continua
    try:
        interactive_conversation()
    except Exception as e:
        print(f"\n❌ Error fatal: {e}")