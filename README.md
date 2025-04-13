# Comisiones Joker

Aplicación web para gestionar comisiones de ventas de Joker Travel.

## Requisitos

- Python 3.8+
- Odoo Server
- Virtualenv (recomendado)

## Configuración

1. Clonar el repositorio:
```bash
git clone https://github.com/sealmoridev/comisiones-joker.git
cd comisiones-joker
```

2. Crear y activar entorno virtual:
```bash
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
```

3. Instalar dependencias:
```bash
pip install -r requirements.txt
```

4. Configurar variables de entorno:
Crear un archivo `.env` con las siguientes variables:
```
ODOO_URL=vte.jokertravel.cl
ODOO_DB=bitnami_odoo
ODOO_USERNAME=your_username
ODOO_PASSWORD=your_password
```

Notas sobre la configuración:
- `ODOO_URL`: Puede ser el dominio sin protocolo (ej: `vte.jokertravel.cl`) o la URL completa (ej: `https://vte.jokertravel.cl`)
- El cliente manejará automáticamente los puertos y protocolos necesarios

## Ejecución Local

```bash
streamlit run main.py
```

La aplicación estará disponible en `http://localhost:8501`

## Despliegue en Railway

1. Conectar el repositorio a Railway
2. Configurar las variables de entorno en Railway:
   - `ODOO_URL`
   - `ODOO_DB`
   - `ODOO_USERNAME`
   - `ODOO_PASSWORD`
3. Railway detectará automáticamente el `Procfile` y desplegará la aplicación

## Características

- Visualización de órdenes de venta
- Cálculo de comisiones
- Filtros por fecha y vendedor
- Integración con Odoo ERP
- Interfaz web intuitiva con Streamlit

## Solución de Problemas

Si encuentras problemas de conexión con Odoo:
1. Verifica que las credenciales sean correctas
2. Asegúrate de que el servidor Odoo esté accesible
3. Revisa los logs de la aplicación para más detalles

## Tecnologías

- [Streamlit](https://streamlit.io/) - Framework web
- [Python Requests](https://requests.readthedocs.io/) - Cliente HTTP
- [Python-dotenv](https://github.com/theskumar/python-dotenv) - Manejo de variables de entorno
- [Pandas](https://pandas.pydata.org/) - Análisis de datos
