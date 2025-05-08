# Este archivo es necesario para el despliegue en Railway
# Importa y ejecuta la aplicación desde Home.py

import subprocess
import sys
import os

def main():
    # Obtener la ruta absoluta del directorio actual
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Ejecutar streamlit run Home.py
    try:
        # Usar subprocess para ejecutar streamlit run Home.py
        subprocess.run([sys.executable, "-m", "streamlit", "run", os.path.join(current_dir, "Home.py")], 
                      check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error al ejecutar Streamlit: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
