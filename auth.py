import streamlit as st
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Obtener la contraseña del portal desde variables de entorno
PASS_PORTAL = os.getenv("PASS_PORTAL")

def check_password():
    """Retorna `True` si el usuario ha ingresado la contraseña correcta del portal."""
    
    # Inicializar estado de sesión para autenticación si no existe
    if 'authentication_status' not in st.session_state:
        st.session_state['authentication_status'] = False
    
    # Si ya está autenticado, retornar True
    if st.session_state['authentication_status']:
        return True
    
    # Crear un formulario de inicio de sesión
    st.title('Acceso al Portal')
    
    with st.form("login_form"):
        password = st.text_input("Contraseña de Acceso", type="password")
        submit = st.form_submit_button("Acceder")
    
    # Verificar contraseña cuando se envía el formulario
    if submit:
        if password == PASS_PORTAL:
            st.session_state['authentication_status'] = True
            st.success("Acceso concedido!")
            st.rerun()
        else:
            st.error("Contraseña incorrecta")
    
    return False

def logout():
    """Cierra la sesión del usuario."""
    st.session_state['authentication_status'] = False
