import json
import os

class Config:
    """Clase para manejar la configuración de la aplicación"""
    
    def __init__(self, config_file='config.json'):
        self.config_file = config_file
        self.data = self.load_config()
    
    def load_config(self):
        """Carga la configuración desde el archivo JSON"""
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(f"Archivo de configuración no encontrado: {self.config_file}")
        
        with open(self.config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get(self, key, default=None):
        """Obtiene un valor de configuración usando notación de puntos (ej: 'ollama.model')"""
        keys = key.split('.')
        value = self.data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value
    
    def get_voice_info(self, voice_name=None):
        """Obtiene la información de una voz específica"""
        if voice_name is None:
            voice_name = self.get('piper.default_voice')
        
        voices = self.get('piper.voices', {})
        if voice_name not in voices:
            raise ValueError(f"Voz '{voice_name}' no encontrada. Voces disponibles: {list(voices.keys())}")
        
        voice_info = voices[voice_name].copy()  # Crear una copia para no modificar el original
        voice_info['name_key'] = voice_name
        
        # Construir rutas completas
        voices_dir = self.get('piper.voices_dir')
        voice_info['onnx_path'] = os.path.join(voices_dir, voice_info['files'][0])
        voice_info['json_path'] = os.path.join(voices_dir, voice_info['files'][1])
        
        return voice_info
    
    def list_available_voices(self):
        """Lista todas las voces disponibles"""
        voices = self.get('piper.voices', {})
        print("\n📢 Voces disponibles:")
        print("="*50)
        for voice_key, voice_info in voices.items():
            # Verificar si el archivo existe
            onnx_path = os.path.join(self.get('piper.voices_dir'), voice_info['files'][0])
            exists = "✅" if os.path.exists(onnx_path) else "❌"
            print(f"  {exists} {voice_key}: {voice_info['name']}")
        print("="*50)
        return list(voices.keys())
    
    def reload(self):
        """Recarga la configuración desde el archivo"""
        self.data = self.load_config()

# Crear una instancia global de configuración
config = Config()