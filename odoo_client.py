# odoo_client.py
import xmlrpc.client
import os
from dotenv import load_dotenv

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
            # Conexión al servicio common para autenticación
            self.common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')

            # Verificar que el servidor está disponible
            version = self.common.version()
            print(f"Conectado a Odoo versión: {version['server_version']}")

            # Autenticación y obtención del uid
            self.uid = self.common.authenticate(self.db, self.username, self.password, {})
            if not self.uid:
                raise Exception("Autenticación fallida. Verifica las credenciales.")

            # Conexión al servicio object para operaciones CRUD
            self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')

            # Verificar permisos básicos
            has_access = self.models.execute_kw(
                self.db, self.uid, self.password,
                'res.users', 'check_access_rights',
                ['read'], {'raise_exception': False}
            )
            if not has_access:
                raise Exception("El usuario no tiene permisos suficientes")

        except Exception as e:
            print(f"Error durante la inicialización: {str(e)}")
            raise

    def search_read(self, model, domain=None, fields=None):
        """Ejecuta search_read con manejo de errores mejorado"""
        if domain is None:
            domain = []
        if fields is None:
            fields = []

        try:
            result = self.models.execute_kw(
                self.db, self.uid, self.password,
                model, 'search_read',
                [domain], {'fields': fields}
            )
            return result
        except Exception as e:
            print(f"Error en search_read para modelo {model}: {str(e)}")
            raise

    def create(self, model, values):
        """Crea un nuevo registro con manejo de errores"""
        try:
            return self.models.execute_kw(
                self.db, self.uid, self.password,
                model, 'create',
                [values]
            )
        except Exception as e:
            print(f"Error al crear registro en {model}: {str(e)}")
            raise

    def write(self, model, ids, values):
        """Actualiza registros con manejo de errores"""
        try:
            return self.models.execute_kw(
                self.db, self.uid, self.password,
                model, 'write',
                [ids, values]
            )
        except Exception as e:
            print(f"Error al actualizar registros en {model}: {str(e)}")
            raise

    def unlink(self, model, ids):
        """Elimina registros con manejo de errores"""
        try:
            return self.models.execute_kw(
                self.db, self.uid, self.password,
                model, 'unlink',
                [ids]
            )
        except Exception as e:
            print(f"Error al eliminar registros en {model}: {str(e)}")
            raise