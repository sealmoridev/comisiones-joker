# odoo_client.py
import json
import requests
import os
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time

class OdooClient:
    def __init__(self):
        # Cargar variables de entorno
        load_dotenv()

        # Obtener configuración
        self.url = os.getenv('ODOO_URL', '').rstrip('/')  # Remover trailing slash
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
            if not parsed_url.scheme:
                # Si no hay esquema, asumir https
                self.url = f"https://{self.url}"
                parsed_url = urlparse(self.url)
            
            # Si no hay puerto, agregar el puerto por defecto
            if not parsed_url.port:
                netloc = parsed_url.netloc
                if parsed_url.scheme == 'https':
                    netloc = f"{netloc}:443"
                else:
                    netloc = f"{netloc}:8069"
                parsed_url = parsed_url._replace(netloc=netloc)
            
            self.base_url = urlunparse(parsed_url)
            
            # Configurar la sesión con reintentos
            self.session = requests.Session()
            retry_strategy = Retry(
                total=3,  # número total de reintentos
                backoff_factor=1,  # tiempo de espera entre reintentos
                status_forcelist=[500, 502, 503, 504],  # códigos HTTP para reintentar
                allowed_methods=["POST"]  # permitir reintentos en POST
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)
            self.session.verify = False
            requests.packages.urllib3.disable_warnings()

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

    def fields_get(self, model, attributes=None):
        """Obtiene metadatos de campos del modelo (útil para compatibilidad entre versiones)."""
        if attributes is None:
            attributes = ['string', 'type', 'relation']

        try:
            return self._jsonrpc('/web/dataset/call_kw', {
                'model': model,
                'method': 'fields_get',
                'args': [],
                'kwargs': {
                    'attributes': attributes,
                },
                'context': {'lang': 'es_ES'}
            })
        except Exception as e:
            print(f"Error en fields_get para modelo {model}: {str(e)}")
            raise

    def _jsonrpc(self, endpoint, params=None):
        """Ejecuta una llamada JSON-RPC a Odoo con reintentos"""
        headers = {
            'Content-Type': 'application/json',
        }

        data = {
            'jsonrpc': '2.0',
            'method': 'call',
            'params': params or {},
            'id': None
        }

        url = f"{self.base_url}{endpoint}"
        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                response = self.session.post(
                    url,
                    headers=headers,
                    data=json.dumps(data),
                    timeout=60  # Aumentado el timeout
                )
                response.raise_for_status()
                result = response.json()
                
                if result.get('error'):
                    error_data = result['error']
                    error_message = error_data.get('message', 'Unknown error')
                    error_data = error_data.get('data', {})
                    debug = error_data.get('debug', '')
                    
                    raise Exception(
                        f"Error en la llamada RPC: {error_message}\n"
                        f"Debug: {debug}"
                    )
                
                return result.get('result', {})

            except (requests.exceptions.ChunkedEncodingError, 
                    requests.exceptions.ConnectionError,
                    requests.exceptions.ReadTimeout) as e:
                if attempt == max_retries - 1:  # Último intento
                    print(f"Error después de {max_retries} intentos: {str(e)}")
                    raise
                print(f"Intento {attempt + 1} falló, reintentando en {retry_delay} segundos...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Backoff exponencial
            except Exception as e:
                print(f"Error inesperado en la solicitud HTTP: {str(e)}")
                raise

    def search_read(self, model, domain=None, fields=None, batch_size=1000):
        """Ejecuta search_read con manejo de errores mejorado"""
        if domain is None:
            domain = []
        if fields is None:
            fields = []

        try:
            # Realizar una sola consulta sin paginación
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