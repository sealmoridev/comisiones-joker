import streamlit as st
import auth

# Configuración de la página principal
st.set_page_config(
    page_title="Sistema de Comisiones Joker",
    page_icon="🏝️",
    layout="wide"
)

# Verificar autenticación
if not auth.check_password():
    st.stop()  # Si no está autenticado, detener la ejecución

# Título y descripción
st.title("Sistema de Comisiones Joker")

st.markdown("""
## Bienvenido al Sistema de Gestión de Comisiones Joker

Este sistema te permite visualizar y analizar información sobre:

- **Ocupación de Paquetes**: Monitorea la ocupación de los diferentes paquetes turísticos
- **Ventas por Destino**: Analiza las ventas clasificadas por destino
- **Venta Agencia**: Gestiona las ventas por agencia

### Instrucciones de uso

Utiliza el menú lateral para navegar entre las diferentes secciones del sistema.
Cada sección cuenta con filtros específicos para personalizar la información mostrada.

---

© 2025 Joker Turismo
""")

# Información adicional en la barra lateral
st.sidebar.title("Navegación")
st.sidebar.info("Selecciona una página del menú para comenzar.")

# Agregar botón de cerrar sesión
if st.sidebar.button("Logout"):
    auth.logout()
    st.rerun()
