import xmlrpc.client
import streamlit as st

def test_odoo_connection(url, db, username, password):
    try:
        # Conexión al servicio common
        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')

        # Verificar la versión (esto no requiere autenticación)
        version = common.version()
        print(f"Versión de Odoo: {version['server_version']}")

        # Intentar autenticación
        uid = common.authenticate(db, username, password, {})
        if uid:
            print(f"Autenticación exitosa! UID: {uid}")

            # Probar conexión a los modelos
            models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

            # Verificar acceso a un modelo básico (res.users)
            user_access = models.execute_kw(
                db, uid, password,
                'res.users', 'check_access_rights',
                ['read'], {'raise_exception': False}
            )
            print(f"Acceso a usuarios: {user_access}")

            return True, uid
        else:
            return False, "Autenticación fallida"

    except Exception as e:
        return False, str(e)

# Interfaz de Streamlit para probar diferentes configuraciones
st.title("Test de Conexión Odoo")

url = st.text_input("URL", "http://vte.jokertravel.cl:8069")
db = st.text_input("Base de datos", "bitnami_odoo")
username = st.text_input("Usuario", "admin")  # Probamos con 'admin' por defecto
password = st.text_input("Contraseña", type="password")

if st.button("Probar Conexión"):
    with st.spinner("Probando conexión..."):
        success, result = test_odoo_connection(url, db, username, password)

        if success:
            st.success(f"Conexión exitosa! UID: {result}")
        else:
            st.error(f"Error de conexión: {result}")

            # Sugerencias basadas en el error
            if "Access Denied" in str(result):
                st.warning("""
                Posibles soluciones:
                1. Verifica que el usuario y contraseña sean correctos
                2. Usa la contraseña en texto plano, no el hash
                3. Asegúrate que el usuario tenga permisos de administrador
                """)
            elif "Connection refused" in str(result):
                st.warning("""
                Posibles soluciones:
                1. Verifica que la URL sea correcta
                2. Confirma que el puerto 8069 esté abierto
                3. Verifica que el servidor Odoo esté funcionando
                """)