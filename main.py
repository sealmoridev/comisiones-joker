# Este archivo es necesario para el despliegue en Railway

import streamlit as st
import sys
import os

# Configurar la página - DEBE SER LA PRIMERA LLAMADA A STREAMLIT
st.set_page_config(page_title="Joker Travel - Dashboard", layout="wide")

# Importar módulo de autenticación
import auth

# Verificar autenticación
if not auth.check_password():
    st.stop()  # Si no está autenticado, detener la ejecución

# Título principal
st.title("Joker Travel - Dashboard")

# Mensaje de bienvenida
st.markdown("""
## Bienvenido al Dashboard de Joker Travel

Este dashboard te permite visualizar y analizar datos importantes sobre:

- Ocupación de paquetes
- Ventas por destino
- Venta por agencia

Selecciona una de las opciones del menú lateral para comenzar.
""")

# Imagen o logo (opcional)
# st.image("logo.png", width=300)

# Información adicional
st.sidebar.markdown("### Navegación")
st.sidebar.info("Utiliza el menú superior para navegar entre las diferentes secciones del dashboard.")

# Agregar botón de cerrar sesión
if st.sidebar.button("Logout"):
    auth.logout()
    st.rerun()

# Pie de página
st.markdown("---")
st.markdown(" 2025 Joker Travel. Todos los derechos reservados.")
