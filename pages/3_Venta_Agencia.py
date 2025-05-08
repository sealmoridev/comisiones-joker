# main.py

# 1. IMPORTACIONES
import streamlit as st

# Configuración de la página - DEBE SER LA PRIMERA LLAMADA A STREAMLIT
st.set_page_config(page_title="Venta Agencia", layout="wide")

import sys
import os

# Importar módulo de autenticación
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth

# Verificar autenticación
if not auth.check_password():
    st.stop()  # Si no está autenticado, detener la ejecución

# Agregar botón de cerrar sesión en la barra lateral
if st.sidebar.button("Logout"):
    auth.logout()
    st.rerun()

import pandas as pd
from datetime import datetime, timedelta
import io
from odoo_client import OdooClient
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# 2. FUNCIONES DE UTILIDAD
def format_currency(value, decimals=0):
    """Formatea un número como moneda con separadores de miles"""
    try:
        value = float(value)
        formatted = f"{value:,.{decimals}f}"
        return formatted.replace(',', 'X').replace('.', ',').replace('X', '.')
    except (ValueError, TypeError):
        return "0"

def to_csv(df):
    """Convierte DataFrame a CSV"""
    return df.to_csv(index=False).encode('utf-8')


# 3. TÍTULO DE LA PÁGINA
st.title("Venta Agencia")

# 4. CONSTANTES
INVOICE_STATUS = {
    'upselling': 'Oportunidad de Venta Adicional',
    'invoiced': 'Facturado',
    'to invoice': 'Por Facturar',
    'no': 'Nada que Facturar'
}

# 5. CÓDIGO PRINCIPAL
try:
    # Crear cliente Odoo
    odoo = OdooClient()
    st.success("Conexión establecida con Odoo")

    # Obtener equipos de venta (agencias)
    teams = odoo.search_read(
        'crm.team',
        domain=[],
        fields=['id', 'name']
    )
    
    team_names = {team['id']: team['name'] for team in teams}
    # Agregar opción "Todos"
    team_names[0] = "Todos"

    # Filtros al inicio de la página
    st.subheader("Filtros")
    
    # Crear contenedor para filtros
    filtros_container = st.container()
    
    with filtros_container:
        # Primera fila de filtros
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # Filtro de agencia
            st.subheader("Agencia")
            agencia_seleccionada = st.selectbox(
                "Seleccionar Agencia",
                options=[0] + [team['id'] for team in teams],
                format_func=lambda x: team_names[x],
                key="agencia"
            )
        
        with col2:
            # Filtro de estado de facturación
            st.subheader("Estado de Facturación")
            estado_facturacion = st.multiselect(
                "Estado de facturación",
                options=list(INVOICE_STATUS.keys()),
                default=['invoiced'],
                format_func=lambda x: INVOICE_STATUS[x]
            )
        
        with col3:
            # Filtro de tipo de cupo
            TIPO_CUPO = {
                'Regular': 'Regular',
                'Social': 'Social',
                'Sin Subsidio': 'Sin Subsidio',
                'Privado': 'Privado'
            }
            
            st.subheader("Tipo de Cupo")
            tipo_cupo_seleccionado = st.selectbox(
                "Seleccionar Tipo de Cupo",
                options=list(TIPO_CUPO.keys()),
                format_func=lambda x: TIPO_CUPO[x],
                key="tipo_cupo"
            )
        
        # Segunda fila para filtros de fecha
        col1, col2 = st.columns(2)
        
        # Filtro de fechas
        fecha_fin = datetime.now()
        fecha_inicio = fecha_fin - timedelta(days=30)
        
        with col1:
            fecha_inicio_selected = st.date_input(
                "Fecha Inicio",
                value=fecha_inicio,
                key="fecha_inicio"
            )
            
        with col2:
            fecha_fin_selected = st.date_input(
                "Fecha Fin",
                value=fecha_fin,
                key="fecha_fin"
            )
        
        # Agregar una línea divisoria
        st.markdown("---")

    # Construir el dominio de búsqueda
    domain = [
        ("date_order", ">=", f"{fecha_inicio_selected} 00:00:00"),
        ("date_order", "<=", f"{fecha_fin_selected} 23:59:59"),
        ("invoice_status", "in", estado_facturacion)
    ]

    # Agregar filtro de agencia solo si no es "Todos"
    if agencia_seleccionada != 0:
        domain.append(("team_id", "=", agencia_seleccionada))

    # El filtro de Tipo de Cupo ya está incluido en la parte superior de la página

    # Campos a obtener
    fields = [
        'name',           # Número de orden
        'partner_id',     # Cliente
        'date_order',     # Fecha de orden
        'invoice_status', # Estado de facturación
        'amount_total',   # Monto total
        'currency_id',    # Moneda
        'user_id',        # Usuario
        'team_id',        # Equipo de ventas
        'order_line',     # Líneas de orden
    ]

    progress_text = "Operación en progreso. Por favor, espere..."
    progress_bar = st.progress(0, text=progress_text)

    with st.spinner('Cargando órdenes...'):
        orders = odoo.search_read('sale.order', domain=domain, fields=fields)
        progress_bar.progress(25, text="Órdenes cargadas...")

        if orders:
            # Obtener todas las primeras líneas y productos de una vez
            first_line_ids = [order['order_line'][0] if order['order_line'] else None for order in orders]
            first_line_ids = [id for id in first_line_ids if id is not None]

            first_lines = odoo.search_read(
                'sale.order.line',
                domain=[('id', 'in', first_line_ids)],
                fields=[
                    'id', 
                    'product_id', 
                    'product_uom_qty',
                    'name',           # Descripción de la línea
                    'price_unit',     # Precio unitario
                    'price_subtotal'  # Subtotal
                ]
            )
            progress_bar.progress(50, text="Líneas de orden cargadas...")

            # Diccionarios para acceso rápido
            first_lines_dict = {line['id']: line for line in first_lines}

            product_ids = list(set(line['product_id'][0] for line in first_lines))
            products = odoo.search_read(
                'product.template',
                domain=[('id', 'in', product_ids)],
                fields=['id', 
                        'name',
                        'default_code',              # Código del producto
                        'list_price',                
                        'x_studio_comision_agencia',
                        'x_studio_destino',
                        'x_studio_tipo_de_cupo'
                       ]
            )
            products_dict = {prod['id']: prod for prod in products}

            progress_bar.progress(75, text="Productos cargados...")

            # Procesar órdenes
            orders_data = []
            for order in orders:
                if order['order_line']:
                    first_line = first_lines_dict.get(order['order_line'][0])
                    if first_line:
                        product = products_dict.get(first_line['product_id'][0])
                        if product:
                            comision_rate = product.get('x_studio_comision_agencia', 0)
                            cantidad = first_line['product_uom_qty']
                            comision = comision_rate * cantidad

                            # Agregar a resumen de agencias
                            team_id = order['team_id'][0] if order['team_id'] else 0
                            team_name = order['team_id'][1] if order['team_id'] else 'Sin Agencia'


                            orders_data.append({
                                'Número': order['name'],
                                'Cliente': order['partner_id'][1] if order['partner_id'] else 'Sin cliente',
                                'Fecha': datetime.strptime(order['date_order'], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M"),
                                'Producto': product.get('name', 'Sin nombre'),
                                'Destino': product.get('x_studio_destino', 'Sin destino'),
                                'Tipo de Cupo': product.get('x_studio_tipo_de_cupo', 'No definido'),  # Ya no necesitamos el mapping
                                'Estado Facturación': INVOICE_STATUS[order['invoice_status']],
                                'Agencia': team_name,
                                'Vendedor': order['user_id'][1] if order['user_id'] else 'Sin asignar',
                                'Cantidad': int(cantidad),
                                'Comision': float(comision),
                                'Total': float(order['amount_total']),
                                'ID': int(order['id'])
                            })
                            
            # Antes del filtro, veamos los tipos de cupo que tenemos
            # Y modificar el filtro
            if tipo_cupo_seleccionado:
                orders_data = [
                    order for order in orders_data 
                    if order['Tipo de Cupo'] == tipo_cupo_seleccionado
                ]
            

            progress_bar.progress(100, text="¡Completado!")

            # Agregar esto después de procesar los orders_data y antes de mostrar la tabla de resumen
            # DESPUÉS del filtro, calculamos el resumen por agencias
            
            resumen_agencias = {}
            for order in orders_data:  # Usamos orders_data filtrado
                team_id = order['Agencia']  # Ya tenemos el nombre de la agencia en orders_data

                if team_id not in resumen_agencias:
                    resumen_agencias[team_id] = {
                        'Agencia': team_id,
                        'Total Órdenes': 0,
                        'Total Pasajeros': 0,
                        'Total Comisiones': 0,
                        'Total Vendido': 0
                    }

                resumen_agencias[team_id]['Total Órdenes'] += 1
                resumen_agencias[team_id]['Total Pasajeros'] += order['Cantidad']
                resumen_agencias[team_id]['Total Comisiones'] += order['Comision']
                resumen_agencias[team_id]['Total Vendido'] += order['Total']

            # Calcular métricas globales
            total_ordenes = len(orders_data)
            total_pasajeros = sum(resumen['Total Pasajeros'] for resumen in resumen_agencias.values())
            total_comisiones = sum(resumen['Total Comisiones'] for resumen in resumen_agencias.values())
            total_ventas = sum(resumen['Total Vendido'] for resumen in resumen_agencias.values())

            # Mostrar métricas en fila
            st.write("### Resumen General")
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric(
                    label="Total Órdenes",
                    value=format_currency(total_ordenes, 0)
                )

            with col2:
                st.metric(
                    label="Total Pasajeros",
                    value=format_currency(total_pasajeros, 0)
                )

            with col3:
                st.metric(
                    label="Total Comisiones",
                    value=f"CLP {format_currency(total_comisiones, 0)}"
                )

            with col4:
                st.metric(
                    label="Total Ventas",
                    value=f"CLP {format_currency(total_ventas, 0)}"
                )

            # Agregar un separador
            st.markdown("---")

            # Continuar con el resto del código...
            
            # Tabla de resumen por agencia
            st.subheader("Resumen por Agencia")
            df_resumen = pd.DataFrame(list(resumen_agencias.values()))
            df_resumen['Total Comisiones'] = df_resumen['Total Comisiones'].apply(lambda x: f"CLP {format_currency(x, 0)}")
            df_resumen['Total Vendido'] = df_resumen['Total Vendido'].apply(lambda x: f"CLP {format_currency(x, 0)}")

            # Botón para descargar resumen
            st.download_button(
                label="📥 Descargar Resumen por Agencia",
                data=to_csv(df_resumen),
                file_name="resumen_agencias.csv",
                mime="text/csv"
            )

            # Mostrar tabla de resumen con selección
            selected_rows = st.data_editor(
                df_resumen,
                use_container_width=True,
                disabled=True,
                key="resumen_table"
            )

            # Crear DataFrame de órdenes
            st.subheader("Órdenes")
            df_orders = pd.DataFrame(orders_data)
            # Debug: mostrar información sobre los datos
            # st.write("DEBUG - Columnas disponibles:", df_orders.columns.tolist())
            # st.write("DEBUG - Cantidad de registros:", len(df_orders))
            # st.write("DEBUG - Muestra de orders_data:", orders_data[:1] if orders_data else "Sin datos")

            if not orders_data:
                st.warning("No hay datos para mostrar")
            else:
                # Formatear columnas de manera segura
                for row in df_orders.index:
                    if 'Comision' in df_orders.columns:
                        valor_comision = df_orders.at[row, 'Comision']
                        df_orders.at[row, 'Comision'] = f"CLP {format_currency(float(valor_comision), 0)}"

                    if 'Total' in df_orders.columns:
                        valor_total = df_orders.at[row, 'Total']
                        df_orders.at[row, 'Total'] = f"CLP {format_currency(float(valor_total), 0)}"



            

            # Botón para descargar órdenes
            st.download_button(
                label="📥 Descargar Órdenes",
                data=to_csv(df_orders.drop('ID', axis=1)),
                file_name="ordenes.csv",
                mime="text/csv"
            )

            # Mostrar tabla de órdenes
            selected_order = st.data_editor(
                df_orders.drop('ID', axis=1),
                use_container_width=True,
                disabled=True,
                key="orders_table"
            )


        else:
            st.info("No se encontraron órdenes de venta con los filtros seleccionados")

except Exception as e:
    st.error(f"Error: {str(e)}")
    st.write("Detalles del error para debugging:", e)