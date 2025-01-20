import streamlit as st
import requests
import os
from PIL import Image
import io

# Configuración de Bunny.net
BUNNY_STORAGE_ZONE = "your-storage-zone"
BUNNY_API_KEY = "your-api-key"
BUNNY_HOSTNAME = f"https://{BUNNY_STORAGE_ZONE}.b-cdn.net"
BUNNY_API_URL = f"https://storage.bunnycdn.com/{BUNNY_STORAGE_ZONE}/"

def upload_to_bunny(file, filename):
    """
    Sube un archivo a Bunny.net y devuelve la URL pública.
    """
    headers = {
        "AccessKey": BUNNY_API_KEY,
        "Content-Type": "application/octet-stream"
    }

    response = requests.put(
        f"{BUNNY_API_URL}{filename}",
        data=file,
        headers=headers
    )

    if response.status_code == 201:
        return f"{BUNNY_HOSTNAME}/{filename}"
    else:
        st.error(f"Error al subir: {response.text}")
        return None

def main():
    st.title("Subir Imágenes a Bunny.net")

    uploaded_file = st.file_uploader("Elige una imagen", type=["png", "jpg", "jpeg"])

    if uploaded_file is not None:
        # Mostrar la imagen
        image = Image.open(uploaded_file)
        st.image(image, caption="Imagen subida", use_column_width=True)

        # Botón para subir
        if st.button("Subir a Bunny.net"):
            with st.spinner("Subiendo..."):
                # Generar un nombre único para el archivo
                file_extension = os.path.splitext(uploaded_file.name)[1]
                unique_filename = f"{uploaded_file.name}_{hash(uploaded_file.name)}{file_extension}"

                # Subir el archivo
                file_bytes = uploaded_file.getvalue()
                public_url = upload_to_bunny(file_bytes, unique_filename)

                if public_url:
                    st.success("¡Imagen subida con éxito!")
                    st.write(f"URL pública: {public_url}")

                    # Mostrar la imagen desde Bunny.net
                    st.image(public_url, caption="Imagen desde Bunny.net", use_column_width=True)

if __name__ == "__main__":
    main()
