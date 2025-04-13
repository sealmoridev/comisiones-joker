# odoo_client.py
import json
import requests
import os
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse

class OdooClient:
    def __init__(self):
        # Cargar variables de entorno
        load_dotenv()

        # Obtener configuración
        self.url = os.getenv('ODOO_URL')
        self.db = os.getenv('ODOO_DB')
        self.username = os.getenv('ODOO_USERNAME')
        self.password = os.getenv('ODOO_PASSWORD')

        # Verificar que todas las variables están configuradas
        if not all([self.url, self.db, self.username, self.password]):
            missing = []
            if not self.url: missing.append('ODOO_URL')
            if not self.db: missing.append('ODOO_DB')
            if not self.username: missing.append('ODOO_USERNAME')
            if not self.password: missing.append('ODOO_PASSWORD')
            raise ValueError(f"Faltan variables de entorno: {', '.join(missing)}")

        try:
            # Parsear y normalizar la URL
            parsed_url = urlparse(self.url)
            if not parsed_url.port:
                parsed_url = parsed_url._replace(netloc=f"{parsed_url.netloc}:8069")
            self.base_url = urlunparse(parsed_url)
            
            # Verificar la conexión y obtener la versión
            version = self._jsonrpc('/web/webclient/version_info')
            print(f"Conectado a Odoo versión: {version.get('server_version')}")

            # Autenticación
            auth_response = self._jsonrpc('/web/session/authenticate', {
                'db': self.db,
                'login': self.username,
                'password': self.password,
            })

            if not auth_response.get('uid'):
                raise Exception("Autenticación fallida. Verifica las credenciales.")

            self.uid = auth_response['uid']
            self.session_id = requests.utils.dict_from_cookiejar(self.session.cookies).get('session_id')

        except Exception as e:
            print(f"Error durante la inicialización: {str(e)}")
            raise

    def _jsonrpc(self, endpoint, params=None):
        """Ejecuta una llamada JSON-RPC a Odoo"""
        if not hasattr(self, 'session'):
            self.session = requests.Session()
            self.session.verify = False  # Para permitir certificados auto-firmados

        headers = {
            'Content-Type': 'application/json',
        }

        data = {
            'jsonrpc': '2.0',
            'method': 'call',
            'params': params or {},
            'id': None
        }

        try:
            response = self.session.post(
                f"{self.base_url}{endpoint}",
                headers=headers,
                data=json.dumps(data),
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            
            if result.get('error'):
                raise Exception(
                    f"Error en la llamada RPC: {result['error'].get('message', 'Unknown error')}"
                )
            
            return result.get('result', {})

        except requests.exceptions.RequestException as e:
            print(f"Error en la solicitud HTTP: {str(e)}")
            raise

    def search_read(self, model, domain=None, fields=None):
        """Ejecuta search_read con manejo de errores mejorado"""
        if domain is None:
            domain = []
        if fields is None:
            fields = []

        try:
            result = self._jsonrpc('/web/dataset/search_read', {
                'model': model,
                'domain': domain,
                'fields': fields,
                'context': {'lang': 'es_ES'}
            })
            return result.get('records', [])
        except Exception as e:
            print(f"Error en search_read para modelo {model}: {str(e)}")
            raise

    def create(self, model, values):
        """Crea un nuevo registro con manejo de errores"""
        try:
            return self._jsonrpc('/web/dataset/call_kw', {
                'model': model,
                'method': 'create',
                'args': [values],
                'kwargs': {},
                'context': {'lang': 'es_ES'}
            })
        except Exception as e:
            print(f"Error al crear registro en {model}: {str(e)}")
            raise

    def write(self, model, ids, values):
        """Actualiza registros con manejo de errores"""
        try:
            return self._jsonrpc('/web/dataset/call_kw', {
                'model': model,
                'method': 'write',
                'args': [ids, values],
                'kwargs': {},
                'context': {'lang': 'es_ES'}
            })
        except Exception as e:
            print(f"Error al actualizar registros en {model}: {str(e)}")
            raise

    def unlink(self, model, ids):
        """Elimina registros con manejo de errores"""
        try:
            return self._jsonrpc('/web/dataset/call_kw', {
                'model': model,
                'method': 'unlink',
                'args': [ids],
                'kwargs': {},
                'context': {'lang': 'es_ES'}
            })
        except Exception as e:
            print(f"Error al eliminar registros en {model}: {str(e)}")
            raise