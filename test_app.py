import os
import sys
import streamlit as st

# Configurar para que muestre información de depuración
os.environ['STREAMLIT_LOG_LEVEL'] = 'debug'

# Imprimir información para depuración
print("Iniciando prueba de la aplicación...")
print(f"Python version: {sys.version}")
print(f"Streamlit version: {st.__version__}")

# Importar el contenido de Home.py
try:
    print("Importando Home.py...")
    from Home import *
    print("Home.py importado correctamente")
except Exception as e:
    print(f"Error al importar Home.py: {e}")
    sys.exit(1)

print("Aplicación iniciada correctamente")
