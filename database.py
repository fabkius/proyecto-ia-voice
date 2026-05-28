import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Optional

class ConversationDatabase:
    """Maneja la persistencia de conversaciones usando SQLite"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            from config_loader import config
            db_path = config.get('database.path', '/home/fabian/.assistant.db')
        
        self.db_path = db_path
        self.max_messages = config.get('database.max_context_messages', 50)
        self.init_database()
    
    def init_database(self):
        """Inicializa la base de datos y crea las tablas necesarias"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Tabla de sesiones
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                session_name TEXT,
                created_at TEXT NOT NULL,
                last_updated TEXT NOT NULL,
                message_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        # Tabla de mensajes
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            )
        ''')
        
        # Índices para búsquedas rápidas
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_session_id ON messages(session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_active_sessions ON sessions(is_active)')
        
        conn.commit()
        conn.close()
        
        print(f"✅ Base de datos inicializada: {self.db_path}")
    
    def create_session(self, session_name: str = None) -> str:
        """Crea una nueva sesión y retorna su ID"""
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        session_name = session_name or f"Conversación {session_id}"
        now = datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO sessions (session_id, session_name, created_at, last_updated, message_count, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session_id, session_name, now, now, 0, 1))
        conn.commit()
        conn.close()
        
        print(f"📝 Nueva sesión creada: {session_name} ({session_id})")
        return session_id
    
    def save_message(self, session_id: str, role: str, content: str):
        """Guarda un mensaje en la base de datos"""
        timestamp = datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Insertar mensaje
        cursor.execute('''
            INSERT INTO messages (session_id, role, content, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (session_id, role, content, timestamp))
        
        # Actualizar contador y timestamp de la sesión
        cursor.execute('''
            UPDATE sessions 
            SET message_count = message_count + 1,
                last_updated = ?
            WHERE session_id = ?
        ''', (timestamp, session_id))
        
        conn.commit()
        conn.close()
    
    def load_session_messages(self, session_id: str, limit: int = None) -> List[Dict]:
        """Carga los mensajes de una sesión"""
        if limit is None:
            limit = self.max_messages
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Cargar mensajes ordenados por timestamp
        cursor.execute('''
            SELECT role, content, timestamp FROM messages 
            WHERE session_id = ? 
            ORDER BY id ASC
            LIMIT ?
        ''', (session_id, limit))
        
        messages = []
        for row in cursor.fetchall():
            messages.append({
                "role": row[0],
                "content": row[1],
                "timestamp": row[2]
            })
        
        conn.close()
        return messages
    
    def get_recent_messages(self, session_id: str, limit: int = None) -> List[Dict]:
        """Obtiene los mensajes recientes (sin timestamps para la API)"""
        messages = self.load_session_messages(session_id, limit)
        # Eliminar timestamps para enviar a la API
        return [{"role": m["role"], "content": m["content"]} for m in messages]
    
    def list_sessions(self) -> List[Dict]:
        """Lista todas las sesiones disponibles"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT session_id, session_name, created_at, last_updated, message_count, is_active
            FROM sessions 
            ORDER BY last_updated DESC
        ''')
        
        sessions = []
        for row in cursor.fetchall():
            sessions.append({
                "session_id": row[0],
                "session_name": row[1],
                "created_at": row[2],
                "last_updated": row[3],
                "message_count": row[4],
                "is_active": row[5]
            })
        
        conn.close()
        return sessions
    
    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """Obtiene información de una sesión específica"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT session_id, session_name, created_at, last_updated, message_count, is_active
            FROM sessions WHERE session_id = ?
        ''', (session_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "session_id": row[0],
                "session_name": row[1],
                "created_at": row[2],
                "last_updated": row[3],
                "message_count": row[4],
                "is_active": row[5]
            }
        return None
    
    def delete_session(self, session_id: str) -> bool:
        """Elimina una sesión y todos sus mensajes"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Verificar si existe
        cursor.execute('SELECT session_id FROM sessions WHERE session_id = ?', (session_id,))
        if not cursor.fetchone():
            conn.close()
            return False
        
        # Eliminar (CASCADE eliminará los mensajes automáticamente)
        cursor.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
        conn.commit()
        conn.close()
        
        return True
    
    def clear_session(self, session_id: str) -> bool:
        """Limpia los mensajes de una sesión pero mantiene la sesión"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Eliminar mensajes
        cursor.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
        
        # Resetear contador
        cursor.execute('''
            UPDATE sessions 
            SET message_count = 0, last_updated = ?
            WHERE session_id = ?
        ''', (datetime.now().isoformat(), session_id))
        
        conn.commit()
        conn.close()
        return True
    
    def rename_session(self, session_id: str, new_name: str) -> bool:
        """Renombra una sesión"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE sessions 
            SET session_name = ?
            WHERE session_id = ?
        ''', (new_name, session_id))
        
        conn.commit()
        conn.close()
        return True
    
    def backup_database(self, backup_path: str = None) -> str:
        """Crea un respaldo de la base de datos"""
        if backup_path is None:
            backup_path = f"{self.db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        import shutil
        shutil.copy2(self.db_path, backup_path)
        print(f"💾 Respaldo creado: {backup_path}")
        return backup_path
    
    def export_session_to_json(self, session_id: str, output_path: str = None) -> str:
        """Exporta una sesión a JSON"""
        messages = self.load_session_messages(session_id, limit=None)
        session_info = self.get_session_info(session_id)
        
        export_data = {
            "session_info": session_info,
            "messages": messages
        }
        
        if output_path is None:
            output_path = f"session_{session_id}.json"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        print(f"📄 Sesión exportada a: {output_path}")
        return output_path
    
    def import_session_from_json(self, json_path: str) -> str:
        """Importa una sesión desde un archivo JSON"""
        with open(json_path, 'r', encoding='utf-8') as f:
            import_data = json.load(f)
        
        session_info = import_data["session_info"]
        messages = import_data["messages"]
        
        # Crear nueva sesión
        session_id = self.create_session(session_info["session_name"])
        
        # Importar mensajes
        for msg in messages:
            self.save_message(session_id, msg["role"], msg["content"])
        
        print(f"📥 Sesión importada: {session_id}")
        return session_id

# Crear instancia global
db = ConversationDatabase()