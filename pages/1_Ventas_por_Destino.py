import streamlit as st

# Configuración de la página - DEBE SER LA PRIMERA LLAMADA A STREAMLIT
st.set_page_config(page_title="Ventas por Destino", layout="wide")

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import sys
import os
from datetime import datetime, timedelta

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

# Agregar la ruta del proyecto al path de Python
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from odoo_client import OdooClient
import os
from dotenv import load_dotenv
from babel.dates import format_date
import plotly.express as px

# Cargar variables de entorno
load_dotenv()

# Funciones de utilidad
def format_currency(value, decimals=0):
    """Formatea un número como moneda con separadores de miles"""
    try:
        return f"${int(float(value)):,}".replace(',', '.')
    except (ValueError, TypeError):
        return value

def export_dataframe_to_excel(df, filename):
    """Exporta un DataFrame a Excel y devuelve un botón de descarga"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    
    excel_data = output.getvalue()
    return st.download_button(
        label=f"📥 Exportar a Excel",
        data=excel_data,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

def parse_spanish_month(date_str):
    """Convierte una fecha en formato 'Mes YYYY' en español a objeto datetime"""
    month_map = {
        'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
        'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
        'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12
    }
    month, year = date_str.lower().split()
    if month not in month_map:
        raise ValueError(f"Mes no válido: {month}")
    return datetime(int(year), month_map[month], 1)

def load_orders_data(start_date, end_date):
    """Carga los datos de órdenes desde Odoo para un rango de fechas"""
    try:
        client = OdooClient()
        
        # Obtener órdenes de venta con límite de 100 para pruebas
        domain = [
            ('state', 'in', ['sale', 'done']),
            ('date_order', '>=', start_date.strftime('%Y-%m-%d 00:00:00')),
            ('date_order', '<=', end_date.strftime('%Y-%m-%d 23:59:59'))
        ]
        
        fields = [
            'name', 'partner_id', 'date_order', 'amount_total',
            'invoice_status', 'user_id', 'team_id', 'order_line'
        ]
        
        # Limitar a 100 registros para pruebas iniciales
        orders = client.search_read('sale.order', domain=domain, fields=fields)
        
        if not orders:
            return pd.DataFrame()
            
        # Recopilar todos los IDs de líneas de orden
        order_line_ids = []
        for order in orders:
            if order.get('order_line'):
                order_line_ids.extend(order['order_line'])
        
        # Obtener todas las líneas de orden en una sola consulta
        order_lines = client.search_read(
            'sale.order.line',
            domain=[('id', 'in', order_line_ids)],
            fields=['order_id', 'product_id', 'product_uom_qty']
        )
        
        # Organizar líneas por orden
        lines_by_order = {}
        product_ids = []
        
        for line in order_lines:
            if not line.get('product_id'):
                continue
                
            order_id = line['order_id'][0]
            if order_id not in lines_by_order:
                lines_by_order[order_id] = []
                
            lines_by_order[order_id].append(line)
            product_ids.append(line['product_id'][0])
        
        # Obtener todos los productos en una sola consulta
        products = client.search_read(
            'product.product',
            domain=[('id', 'in', product_ids)],
            fields=[
                'id', 'default_code', 'x_studio_lote', 'x_studio_destino',
                'x_studio_transporte', 'x_studio_comision_agencia',
                'x_studio_ida_fecha_salida', 'x_studio_boletos_totales',
                'x_studio_boletos_reservados', 'x_product_count_pagados_stat_inf',
                'x_studio_boletos_disponibles', 'name', 'product_tmpl_id'
            ]
        )
        
        # Obtener los IDs de las plantillas de producto
        template_ids = [product['product_tmpl_id'][0] for product in products if product.get('product_tmpl_id')]
        
        # Obtener los datos de las plantillas de producto, incluyendo el tipo de cupo y estado de viaje
        templates = client.search_read(
            'product.template',
            domain=[('id', 'in', template_ids)],
            fields=['id', 'x_studio_tipo_de_cupo', 'x_studio_estado_viaje']
        )
        
        # Crear diccionario de plantillas para acceso rápido
        templates_dict = {template['id']: template for template in templates}
        
        # Crear diccionario de productos para acceso rápido
        products_dict = {product['id']: product for product in products}
        
        # Procesar las órdenes y crear el DataFrame
        orders_data = []
        
        for order in orders:
            order_id = order['id']
            order_lines_list = lines_by_order.get(order_id, [])
            
            for order_line in order_lines_list:
                product_id = order_line['product_id'][0]
                product = products_dict.get(product_id, {})
                
                if not product:
                    continue
                
                # Obtener datos de la plantilla del producto
                template_id = product.get('product_tmpl_id', [0])[0]
                template = templates_dict.get(template_id, {})
                
                # Datos del producto
                product_info = {
                    'default_code': product.get('default_code', ''),
                    'x_studio_lote': product.get('x_studio_lote', ''),
                    'x_studio_destino': product.get('x_studio_destino', ''),
                    'x_studio_transporte': product.get('x_studio_transporte', ''),
                    'fecha_salida': product.get('x_studio_ida_fecha_salida', ''),
                    'plazas_totales': product.get('x_studio_boletos_totales', 0),
                    'plazas_reservadas': product.get('x_studio_boletos_reservados', 0),
                    'plazas_pagadas': product.get('x_product_count_pagados_stat_inf', 0),
                    'plazas_disponibles': product.get('x_studio_boletos_disponibles', 0),
                    'nombre_producto': product.get('name', ''),
                    'tipo_cupo': template.get('x_studio_tipo_de_cupo', ''),
                    'estado_viaje': template.get('x_studio_estado_viaje', False)
                }
                
                # Calcular la comisión basada en el producto y la cantidad
                comision_agencia = product.get('x_studio_comision_agencia', 0)
                cantidad = order_line.get('product_uom_qty', 0)
                total_commission = comision_agencia * cantidad
                
                # Obtener el nombre descriptivo del estado del paquete
                estado_codigo = product_info['estado_viaje']
                estado_nombre = ESTADO_PAQUETE.get(estado_codigo, f'Estado {estado_codigo}')
                
                # Agregar datos de la orden
                order_data = {
                    'Número': order['name'],
                    'Cliente': order['partner_id'][1] if order['partner_id'] else '',
                    'Fecha': datetime.strptime(order['date_order'], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d'),
                    'Estado': INVOICE_STATUS.get(order['invoice_status'], order['invoice_status']),
                    'Total': order['amount_total'],
                    'Vendedor': order['user_id'][1] if order['user_id'] else '',
                    'Agencia': order['team_id'][1] if order['team_id'] else '',
                    'Comision': total_commission,
                    'Código Paquete': product_info['default_code'],
                    'Nombre Paquete': product_info['nombre_producto'],
                    'Lote': product_info['x_studio_lote'],
                    'Destino': product_info['x_studio_destino'],
                    'Transporte': product_info['x_studio_transporte'],
                    'Pasajeros': order_line.get('product_uom_qty', 0),
                    'Fecha Salida': product_info['fecha_salida'],
                    'Plazas Totales': product_info['plazas_totales'],
                    'Plazas Reservadas': product_info['plazas_reservadas'],
                    'Plazas Pagadas': product_info['plazas_pagadas'],
                    'Plazas Disponibles': product_info['plazas_disponibles'],
                    'Tipo de Cupo': product_info['tipo_cupo'],
                    'Estado de Paquete Codigo': product_info['estado_viaje'],
                    'Estado de Paquete': estado_nombre
                }
                orders_data.append(order_data)
        
        return pd.DataFrame(orders_data)
        
    except Exception as e:
        st.error(f"Error al cargar datos: {str(e)}")
        return None

# Título de la página
st.title("Ventas por Destino")

# Inicializar el estado de la sesión si no existe
if 'orders_df' not in st.session_state:
    st.session_state.orders_df = None
    st.session_state.last_loaded_month = None

# Constantes
INVOICE_STATUS = {
    'upselling': 'Oportunidad de Venta Adicional',
    'invoiced': 'Facturado',
    'to invoice': 'Por Facturar',
    'no': 'Nada que Facturar'
}

# Mapeo de cu00f3digos de estado de paquete a nombres descriptivos
ESTADO_PAQUETE = {
    0: 'Bloqueado',
    1: 'Inactivo',
    2: 'Pendiente',
    3: 'Activo',
    4: 'Validación',
    5: 'Cerrado',
    6: 'Rendido',
    7: 'Liquidado',
    8: 'Pre-confirmado',
    9: 'Anulado',
    10: 'Social'
}

try:
    # Obtener lista de meses disponibles
    client = OdooClient()
    all_orders = client.search_read('sale.order', 
                                  domain=[('state', 'in', ['sale', 'done'])],
                                  fields=['date_order'])
    
    # Extraer meses únicos
    months = set()
    for order in all_orders:
        date = datetime.strptime(order['date_order'], '%Y-%m-%d %H:%M:%S')
        months.add(date.strftime('%Y-%m'))
    
    # Convertir a lista ordenada
    months = sorted(list(months), reverse=True)
    
    # Crear opciones de meses en español
    month_options = []
    for month in months:
        date = datetime.strptime(month, '%Y-%m')
        month_name = format_date(date, format='MMMM yyyy', locale='es').capitalize()
        month_options.append(month_name)
    
    # Obtener el mes actual
    current_date = datetime.now()
    current_month = format_date(current_date, format='MMMM yyyy', locale='es').capitalize()
    
    # Si el mes actual no está en las opciones, usar el mes más reciente
    default_month = current_month if current_month in month_options else month_options[0]
    
    # Filtro de mes y botón de carga
    col1, col2 = st.columns([3, 1])
    with col1:
        selected_month = st.selectbox(
            "Seleccionar Mes",
            options=month_options,
            index=month_options.index(default_month),
            help="Seleccione el mes para ver las ventas"
        )
    
    with col2:
        load_button = st.button("Cargar Datos", type="primary")
    
    # Cargar datos solo cuando se presione el botón
    if load_button:
        with st.spinner('Cargando datos...'):
            selected_date = parse_spanish_month(selected_month)
            start_date = selected_date.replace(day=1)
            end_date = (start_date.replace(month=start_date.month % 12 + 1, day=1) if start_date.month < 12 
                       else start_date.replace(year=start_date.year + 1, month=1, day=1)) - timedelta(days=1)
            
            st.session_state.orders_df = load_orders_data(start_date, end_date)
            st.session_state.last_loaded_month = selected_month
            
            if st.session_state.orders_df is not None:
                st.success(f'Datos cargados exitosamente para {selected_month}')
    # Cargar datos por defecto si no hay datos cargados
    elif st.session_state.orders_df is None:
        with st.spinner('Cargando datos iniciales...'):
            selected_date = parse_spanish_month(default_month)
            start_date = selected_date.replace(day=1)
            end_date = (start_date.replace(month=start_date.month % 12 + 1, day=1) if start_date.month < 12 
                       else start_date.replace(year=start_date.year + 1, month=1, day=1)) - timedelta(days=1)
            
            st.session_state.orders_df = load_orders_data(start_date, end_date)
            st.session_state.last_loaded_month = default_month
            
            if st.session_state.orders_df is not None:
                st.success(f'Datos cargados exitosamente para {default_month}')
    
    # Mostrar mensaje si se está viendo datos de un mes diferente al seleccionado
    if (st.session_state.last_loaded_month is not None and 
        st.session_state.last_loaded_month != selected_month):
        st.warning(f'Mostrando datos de {st.session_state.last_loaded_month}. Presiona "Cargar Datos" para ver {selected_month}.')
    
    # Continuar solo si hay datos cargados
    if st.session_state.orders_df is not None:
        df = st.session_state.orders_df
        
        # Sección de filtros en columnas
        st.subheader("Filtros de Búsqueda")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # Filtro de Agencia
            agencias = ['Todas'] + sorted(df['Agencia'].unique().tolist())
            selected_agencia = st.selectbox('Agencia', agencias)
            
        with col2:
            # Filtro de Destino
            destinos = ['Todos'] + sorted(df['Destino'].unique().tolist())
            selected_destino = st.selectbox('Destino', destinos)
            
        with col3:
            # Filtro de Estado
            estados = ['Todos'] + sorted(df['Estado'].unique().tolist())
            selected_estado = st.selectbox('Estado', estados)
        
        # Segunda fila de filtros
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # Filtro de Lote
            lotes = ['Todos'] + sorted(df['Lote'].unique().tolist())
            selected_lote = st.selectbox('Lote', lotes)
            
        with col2:
            # Filtro de Tipo de Cupo (si existe en los datos)
            if 'Tipo de Cupo' in df.columns:
                tipos_cupo = sorted(df['Tipo de Cupo'].unique().tolist())
            else:
                # Valores predeterminados de tipos de cupo
                tipos_cupo = ['Regular', 'Social', 'Sin Subsidio', 'Privado']
            
            # Establecer valores predeterminados: Regular y Sin Subsidio
            default_tipos = []
            for tipo in ['Regular', 'Sin Subsidio']:
                if tipo in tipos_cupo:
                    default_tipos.append(tipo)
            
            # Crear filtro multiselect con valores predeterminados
            selected_tipo_cupo = st.multiselect(
                'Tipo de Cupo', 
                options=tipos_cupo,
                default=default_tipos,
                help='Seleccione uno o más tipos de cupo'
            )
        
        with col3:
            # Filtro de Estado de Paquete
            selected_estado_paquete = []
            if 'Estado de Paquete Codigo' in df.columns:
                # Obtener los valores únicos de Estado de Paquete Codigo
                
                # Crear un diccionario para mapear códigos a nombres y viceversa
                # Convertir los códigos a enteros para que coincidan con las claves del diccionario ESTADO_PAQUETE
                codigos_unicos = []
                for codigo in df['Estado de Paquete Codigo'].unique():
                    if codigo is not None:
                        try:
                            # Intentar convertir a entero
                            codigo_int = int(codigo)
                            codigos_unicos.append(codigo_int)
                        except (ValueError, TypeError):
                            # Si no se puede convertir, usar el valor original
                            codigos_unicos.append(codigo)
                
                nombres_estados = {codigo: ESTADO_PAQUETE.get(codigo, f'Estado {codigo}') for codigo in codigos_unicos}
                
                # Mapeo completado
                
                # Mostrar los nombres de los estados en el filtro
                opciones_estados = sorted(nombres_estados.values())
                
                # Establecer el valor predeterminado como 'Activo'
                default_estado = []
                if 'Activo' in opciones_estados:
                    default_estado = ['Activo']
                
                # Crear filtro multiselect con valor predeterminado 'Activo'
                selected_estado_paquete_nombres = st.multiselect(
                    'Estado de Paquete',
                    options=opciones_estados,
                    default=default_estado,
                    help='Seleccione uno o más estados de paquete. Por defecto se selecciona el estado Activo'
                )
                
                # Convertir los nombres seleccionados a códigos para el filtrado
                codigos_a_nombres = {v: k for k, v in nombres_estados.items()}
                selected_estado_paquete = [codigos_a_nombres[nombre] for nombre in selected_estado_paquete_nombres if nombre in codigos_a_nombres]
        
        # Aplicar filtros al DataFrame
        filtered_df = df.copy()
        if selected_agencia != 'Todas':
            filtered_df = filtered_df[filtered_df['Agencia'] == selected_agencia]
        if selected_destino != 'Todos':
            filtered_df = filtered_df[filtered_df['Destino'] == selected_destino]
        if selected_estado != 'Todos':
            filtered_df = filtered_df[filtered_df['Estado'] == selected_estado]
        if selected_lote != 'Todos':
            filtered_df = filtered_df[filtered_df['Lote'] == selected_lote]
        
        # Filtrar por tipo de cupo (selecciu00f3n mu00faltiple)
        if 'Tipo de Cupo' in df.columns and len(selected_tipo_cupo) > 0:
            filtered_df = filtered_df[filtered_df['Tipo de Cupo'].isin(selected_tipo_cupo)]
            
        # Filtrar por estado de paquete (selección múltiple)
        if 'Estado de Paquete Codigo' in df.columns and len(selected_estado_paquete) > 0:
            # Convertir los códigos en el DataFrame a enteros para la comparación
            # Creamos una copia para no modificar el DataFrame original
            temp_df = filtered_df.copy()
            temp_df['Estado de Paquete Codigo Int'] = temp_df['Estado de Paquete Codigo'].apply(
                lambda x: int(x) if x is not None and isinstance(x, (int, float, str)) and str(x).isdigit() else x
            )
            filtered_df = temp_df[temp_df['Estado de Paquete Codigo Int'].isin(selected_estado_paquete)]
        
        # Mostrar resumen detallado
        st.subheader("Resumen General")
        
        # Calcular totales por estado de facturación
        facturado_df = filtered_df[filtered_df['Estado'] == 'Facturado']
        por_facturar_df = filtered_df[filtered_df['Estado'] == 'Por Facturar']
        
        # Totales generales
        total_ventas = filtered_df['Total'].sum()
        total_comisiones = filtered_df['Comision'].sum()
        total_pasajeros = filtered_df['Pasajeros'].sum()
        total_ordenes = len(filtered_df)
        
        # Totales facturados
        ventas_facturadas = facturado_df['Total'].sum()
        comisiones_facturadas = facturado_df['Comision'].sum()
        pasajeros_facturados = facturado_df['Pasajeros'].sum()
        ordenes_facturadas = len(facturado_df)
        
        # Totales por facturar
        ventas_por_facturar = por_facturar_df['Total'].sum()
        comisiones_por_facturar = por_facturar_df['Comision'].sum()
        pasajeros_por_facturar = por_facturar_df['Pasajeros'].sum()
        ordenes_por_facturar = len(por_facturar_df)
        
        # Crear tarjetas de resumen con diseño elegante
        st.markdown('''<style>
            .metric-card {
                border-radius: 10px;
                padding: 15px;
                margin-bottom: 10px;
                background-color: #f8f9fa;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }
            .metric-title {
                font-size: 1.2rem;
                font-weight: bold;
                margin-bottom: 10px;
                color: #1E3A8A;
            }
            .metric-value {
                font-size: 1.8rem;
                font-weight: bold;
                color: #1E3A8A;
            }
            .metric-subtitle {
                font-size: 0.9rem;
                margin-top: 5px;
                color: #4B5563;
            }
            .metric-subvalue {
                font-size: 1.1rem;
                font-weight: bold;
            }
            .facturado {
                color: #047857;  /* Verde oscuro */
            }
            .por-facturar {
                color: #B91C1C;  /* Rojo oscuro */
            }
        </style>''', unsafe_allow_html=True)
        

        # Inicializar variables para plazas globales
        plazas_totales_global = 0
        plazas_reservadas_global = 0
        plazas_pagadas_global = 0
        plazas_disponibles_global = 0
        porcentaje_ocupacion_global = 0
        
        # Crear filas de tarjetas - Reorganizadas según el nuevo diseño
        # Primera fila: Pasajeros, Ventas y Comisiones (3 columnas)
        col1, col2, col3 = st.columns(3)
        
        # 1. Tarjeta de Pasajeros del mes filtrado
        with col1:
            pasajeros_str = f'''
            <div class='metric-card'>
                <div class='metric-title'>Total Pasajeros - {selected_month}</div>
                <div class='metric-value'>{int(total_pasajeros):,}</div>
                <div class='metric-subtitle'>Facturado:</div>
                <div class='metric-subvalue facturado'>{int(pasajeros_facturados):,}</div>
                <div class='metric-subtitle'>Por Facturar:</div>
                <div class='metric-subvalue por-facturar'>{int(pasajeros_por_facturar):,}</div>
            </div>
            '''
            st.markdown(pasajeros_str.replace(',', '.'), unsafe_allow_html=True)
        
        # 2. Tarjeta de Ventas
        with col2:
            st.markdown(f'''
            <div class='metric-card'>
                <div class='metric-title'>Total Ventas - {selected_month}</div>
                <div class='metric-value'>{format_currency(total_ventas)}</div>
                <div class='metric-subtitle'>Facturado:</div>
                <div class='metric-subvalue facturado'>{format_currency(ventas_facturadas)}</div>
                <div class='metric-subtitle'>Por Facturar:</div>
                <div class='metric-subvalue por-facturar'>{format_currency(ventas_por_facturar)}</div>
            </div>
            ''', unsafe_allow_html=True)
        
        # 3. Tarjeta de Comisiones
        with col3:
            st.markdown(f'''
            <div class='metric-card'>
                <div class='metric-title'>Total Comisiones - {selected_month}</div>
                <div class='metric-value'>{format_currency(total_comisiones)}</div>
                <div class='metric-subtitle'>Facturado:</div>
                <div class='metric-subvalue facturado'>{format_currency(comisiones_facturadas)}</div>
                <div class='metric-subtitle'>Por Facturar:</div>
                <div class='metric-subvalue por-facturar'>{format_currency(comisiones_por_facturar)}</div>
            </div>
            ''', unsafe_allow_html=True)
        
        # Ya no mostramos la segunda fila de tarjetas (Ocupaciu00f3n, Plazas Reservadas, Plazas Pagadas, Plazas Disponibles)
        # para simplificar el dashboard y evitar problemas con los datos
        
        # Gráficos
        st.subheader("Análisis Gráfico")
        
        # Primero, calculamos las plazas por destino
        # Agrupamos los paquetes por destino y sumamos las plazas
        plazas_por_destino = {}
        for destino in filtered_df['Destino'].unique():
            # Filtrar por destino y obtener valores únicos de paquetes
            paquetes_destino = filtered_df[filtered_df['Destino'] == destino]['Código Paquete'].unique()
            
            # Para cada paquete, obtener los datos de plazas (tomamos el primer registro, asumiendo que son iguales)
            plazas_totales = 0
            plazas_reservadas = 0
            plazas_pagadas = 0
            plazas_disponibles = 0
            
            for paquete in paquetes_destino:
                paquete_data = filtered_df[(filtered_df['Destino'] == destino) & (filtered_df['Código Paquete'] == paquete)].iloc[0]
                plazas_totales += paquete_data.get('Plazas Totales', 0) or 0
                plazas_reservadas += paquete_data.get('Plazas Reservadas', 0) or 0
                plazas_pagadas += paquete_data.get('Plazas Pagadas', 0) or 0
                plazas_disponibles += paquete_data.get('Plazas Disponibles', 0) or 0
            
            plazas_por_destino[destino] = {
                'Plazas Totales': plazas_totales,
                'Plazas Reservadas': plazas_reservadas,
                'Plazas Pagadas': plazas_pagadas,
                'Plazas Disponibles': plazas_disponibles
            }
        
        # Los totales globales se calcularu00e1n despuu00e9s de que ventas_por_destino estu00e9 definido
        
        # Calcular porcentaje de ocupación global
        if plazas_totales_global > 0:
            plazas_ocupadas_global = plazas_reservadas_global + plazas_pagadas_global
            porcentaje_ocupacion_global = min(100, (plazas_ocupadas_global / plazas_totales_global) * 100)
            
        # Crear un DataFrame para el gráfico de plazas por destino
        plazas_por_destino_grafico = []
        
        # Crear datos para el gráfico
        for destino, plazas in plazas_por_destino.items():
            # Plazas pagadas
            plazas_pagadas_valor = plazas['Plazas Pagadas']
            plazas_por_destino_grafico.append({
                'Destino': destino,
                'Tipo': 'Plazas Pagadas',
                'Valor': plazas_pagadas_valor
            })
            
            # Plazas disponibles
            plazas_disponibles_valor = plazas['Plazas Disponibles']
            plazas_por_destino_grafico.append({
                'Destino': destino,
                'Tipo': 'Plazas Disponibles',
                'Valor': plazas_disponibles_valor
            })
        
        # Convertir a DataFrame
        df_plazas_grafico = pd.DataFrame(plazas_por_destino_grafico)
        
        # Ordenar el DataFrame por el total de plazas (pagadas + disponibles) para mejor visualizaciu00f3n
        # Primero, crear un DataFrame auxiliar para calcular el total por destino
        df_total = df_plazas_grafico.copy()
        df_total_por_destino = df_total.groupby('Destino')['Valor'].sum().reset_index()
        df_total_por_destino = df_total_por_destino.sort_values('Valor', ascending=True)
        
        # Ordenar el DataFrame original segu00fan el orden de destinos
        orden_destinos = df_total_por_destino['Destino'].tolist()
        df_plazas_grafico['Destino'] = pd.Categorical(df_plazas_grafico['Destino'], categories=orden_destinos, ordered=True)
        df_plazas_grafico = df_plazas_grafico.sort_values('Destino')
        
        # Crear datos para el gru00e1fico
        destinos = df_plazas_grafico['Destino'].unique()
        
        # Crear diccionarios para almacenar los valores por destino
        plazas_pagadas = {}
        plazas_disponibles = {}
        
        # Llenar los diccionarios con los valores
        for destino in destinos:
            # Obtener los valores como lista para evitar problemas con .values
            pagadas_df = df_plazas_grafico[(df_plazas_grafico['Destino'] == destino) & (df_plazas_grafico['Tipo'] == 'Plazas Pagadas')]['Valor']
            disponibles_df = df_plazas_grafico[(df_plazas_grafico['Destino'] == destino) & (df_plazas_grafico['Tipo'] == 'Plazas Disponibles')]['Valor']
            
            # Convertir a lista y obtener el primer valor si existe
            pagadas_list = pagadas_df.tolist()
            disponibles_list = disponibles_df.tolist()
            
            plazas_pagadas[destino] = pagadas_list[0] if len(pagadas_list) > 0 else 0
            plazas_disponibles[destino] = disponibles_list[0] if len(disponibles_list) > 0 else 0
        
        # Ordenar los destinos por el total de plazas
        total_plazas = {destino: plazas_pagadas[destino] + plazas_disponibles[destino] for destino in destinos}
        destinos_ordenados = sorted(destinos, key=lambda x: total_plazas[x])
        
        # Crear listas ordenadas para el gru00e1fico
        valores_pagadas = [plazas_pagadas[destino] for destino in destinos_ordenados]
        valores_disponibles = [plazas_disponibles[destino] for destino in destinos_ordenados]
        
        # Crear la figura con barras verticales
        fig = go.Figure()
        
        # Au00f1adir barras para plazas pagadas
        fig.add_trace(go.Bar(
            x=destinos_ordenados,
            y=valores_pagadas,
            name='Plazas Pagadas',
            text=[f"{int(v):,}".replace(',', '.') for v in valores_pagadas],
            textposition='outside',
            marker_color='rgba(0, 128, 0, 0.8)'  # Verde para plazas pagadas
        ))
        
        # Au00f1adir barras para plazas disponibles
        fig.add_trace(go.Bar(
            x=destinos_ordenados,
            y=valores_disponibles,
            name='Plazas Disponibles',
            text=[f"{int(v):,}".replace(',', '.') for v in valores_disponibles],
            textposition='outside',
            marker_color='rgba(255, 165, 0, 0.8)'  # Naranja para plazas disponibles
        ))
        
        # Configurar el título del gráfico y otras propiedades
        fig.update_layout(
            title=f'Plazas por Destino - {selected_month}',
            barmode='group',  # Agrupar barras lado a lado
            bargap=0.15,      # Espacio entre grupos de barras
            bargroupgap=0.1,  # Espacio entre barras del mismo grupo
            plot_bgcolor='white',  # Fondo blanco
            showlegend=True,
            legend=dict(
                orientation="h",     # Orientaciu00f3n horizontal de la leyenda
                yanchor="bottom",    # Anclar en la parte inferior
                y=1.02,               # Posicionar encima del gru00e1fico
                xanchor="right",     # Anclar a la derecha
                x=1                   # Posicionar en el extremo derecho
            ),
            yaxis=dict(
                title="Nu00famero de Plazas",
                rangemode='tozero',  # Asegurar que el eje Y comience en cero
                gridcolor='lightgray'  # Color de las líneas de la cuadrícula
            ),
            xaxis=dict(
                title="Destino",
                tickangle=-45  # Rotar las etiquetas para mejor legibilidad
            )
        )
        
        # Personalizar el gru00e1fico
        fig.update_layout(
            xaxis_title="Destino",
            yaxis_title="Nu00famero de Plazas",
            legend_title="Tipo",
            font=dict(size=12),
            yaxis=dict(
                rangemode='tozero',  # Asegurar que el eje Y comience en cero
                autorange=True       # Permitir que el rango se ajuste automáticamente
            ),
            bargap=0.2,              # Espacio entre grupos de barras
            bargroupgap=0.1,         # Espacio entre barras del mismo grupo
            legend=dict(
                orientation="h",     # Orientaciu00f3n horizontal de la leyenda
                yanchor="bottom",    # Anclar en la parte inferior
                y=1.02,               # Posicionar encima del gru00e1fico
                xanchor="right",     # Anclar a la derecha
                x=1                   # Posicionar en el extremo derecho
            )
        )
        
        # Mejorar la presentaciu00f3n de las etiquetas de texto
        fig.update_traces(textposition='outside', textfont=dict(size=10, color='black'))
        
        st.plotly_chart(fig, use_container_width=True)
        
        # Crear el DataFrame de ventas por destino
        ventas_por_destino = filtered_df.groupby('Destino').agg({
            'Total': 'sum',
            'Comision': 'sum',
            'Pasajeros': 'sum',
            'Número': 'count'
        }).reset_index()
        
        ventas_por_destino = ventas_por_destino.rename(columns={
            'Número': 'Órdenes Mes',
            'Pasajeros': 'Pasajeros Mes'
        })
        ventas_por_destino = ventas_por_destino.sort_values('Total', ascending=False)
        
        # Tabla de resumen de ventas por destino
        col1, col2 = st.columns([3, 1])
        with col1:
            st.subheader("Resumen de Ventas por Destino")
        with col2:
            # Botu00f3n de exportaciu00f3n justo debajo del tu00edtulo, en la esquina superior derecha
            if not ventas_por_destino.empty:
                # Crear una copia del DataFrame con todas las columnas para exportar
                export_df = ventas_por_destino.copy()
                export_dataframe_to_excel(
                    export_df, 
                    f"ventas_por_destino_{selected_month}.xlsx"
                )
        
        # Primero, calculamos las plazas por destino
        # Agrupamos los paquetes por destino y sumamos las plazas
        plazas_por_destino = {}
        for destino in filtered_df['Destino'].unique():
            # Filtrar por destino y obtener valores únicos de paquetes
            paquetes_destino = filtered_df[filtered_df['Destino'] == destino]['Código Paquete'].unique()
            
            # Para cada paquete, obtener los datos de plazas (tomamos el primer registro, asumiendo que son iguales)
            plazas_totales = 0
            plazas_reservadas = 0
            plazas_pagadas = 0
            plazas_disponibles = 0
            
            for paquete in paquetes_destino:
                paquete_data = filtered_df[(filtered_df['Destino'] == destino) & (filtered_df['Código Paquete'] == paquete)].iloc[0]
                plazas_totales += paquete_data.get('Plazas Totales', 0) or 0
                plazas_reservadas += paquete_data.get('Plazas Reservadas', 0) or 0
                plazas_pagadas += paquete_data.get('Plazas Pagadas', 0) or 0
                plazas_disponibles += paquete_data.get('Plazas Disponibles', 0) or 0
            
            plazas_por_destino[destino] = {
                'Plazas Totales': plazas_totales,
                'Plazas Reservadas': plazas_reservadas,
                'Plazas Pagadas': plazas_pagadas,
                'Plazas Disponibles': plazas_disponibles
            }
        
        # Agregar las plazas al DataFrame de ventas por destino
        for idx, row in ventas_por_destino.iterrows():
            destino = row['Destino']
            if destino in plazas_por_destino:
                ventas_por_destino.at[idx, 'Plazas Totales'] = plazas_por_destino[destino]['Plazas Totales']
                ventas_por_destino.at[idx, 'Plazas Reservadas'] = plazas_por_destino[destino]['Plazas Reservadas']
                ventas_por_destino.at[idx, 'Plazas Pagadas'] = plazas_por_destino[destino]['Plazas Pagadas']
                ventas_por_destino.at[idx, 'Plazas Disponibles'] = plazas_por_destino[destino]['Plazas Disponibles']
                
                # Calcular porcentaje de ocupación
                plazas_totales = plazas_por_destino[destino]['Plazas Totales']
                if plazas_totales > 0:
                    plazas_ocupadas = plazas_por_destino[destino]['Plazas Reservadas'] + plazas_por_destino[destino]['Plazas Pagadas']
                    porcentaje_ocupacion = min(100, (plazas_ocupadas / plazas_totales) * 100)
                    ventas_por_destino.at[idx, 'Ocupación'] = f"{int(porcentaje_ocupacion)}%"
                else:
                    ventas_por_destino.at[idx, 'Ocupación'] = "0%"
        

        
        # Función para colorear las celdas de ocupación
        def color_ocupacion(val):
            # Extraer el número del porcentaje (quitar el símbolo %)
            try:
                num = int(val.replace('%', ''))
            except:
                return ''
                
            # Definir colores por rango (invertidos)
            if num < 50:  # Menos del 50% - Rojo (baja ocupación)
                return 'background-color: #ff9e82'  # Rojo claro
            elif num < 80:  # Entre 50% y 80% - Amarillo (ocupación media)
                return 'background-color: #ffeb82'  # Amarillo claro
            else:  # Más del 80% - Verde (alta ocupación)
                return 'background-color: #8eff8e'  # Verde claro
        
        # Mostrar la tabla con formato y colores
        st.dataframe(
            ventas_por_destino[[
                'Destino', 'Total', 'Comision', 'Pasajeros Mes', 'Órdenes Mes',
                'Plazas Totales', 'Plazas Reservadas', 'Plazas Pagadas', 'Plazas Disponibles', 'Ocupación'
            ]].style.format({
                'Total': lambda x: format_currency(x),
                'Comision': lambda x: format_currency(x),
                'Pasajeros Mes': lambda x: f"{int(x):,}".replace(',', '.'),
                'Órdenes Mes': lambda x: f"{int(x):,}".replace(',', '.'),
                'Plazas Totales': lambda x: f"{int(x):,}".replace(',', '.') if pd.notna(x) else "0",
                'Plazas Reservadas': lambda x: f"{int(x):,}".replace(',', '.') if pd.notna(x) else "0",
                'Plazas Pagadas': lambda x: f"{int(x):,}".replace(',', '.') if pd.notna(x) else "0",
                'Plazas Disponibles': lambda x: f"{int(x):,}".replace(',', '.') if pd.notna(x) else "0"
            }).applymap(color_ocupacion, subset=['Ocupación']),
            hide_index=True,
            use_container_width=True
        )
        
        # Eliminamos este botón ya que lo reposicionaremos
        
        # Agregar leyenda para el semáforo de ocupación
        st.markdown("**Semáforo de Ocupación:** 🔴 < 50% | 🟡 50-80% | 🟢 > 80%")
        
        # Calcular totales globales a partir de la tabla ventas_por_destino
        # Esta tabla ya tiene los datos correctos y procesados
        if 'Plazas Totales' in ventas_por_destino.columns:
            plazas_totales_global = ventas_por_destino['Plazas Totales'].sum()
            plazas_reservadas_global = ventas_por_destino['Plazas Reservadas'].sum() if 'Plazas Reservadas' in ventas_por_destino.columns else 0
            plazas_pagadas_global = ventas_por_destino['Plazas Pagadas'].sum() if 'Plazas Pagadas' in ventas_por_destino.columns else 0
            plazas_disponibles_global = ventas_por_destino['Plazas Disponibles'].sum() if 'Plazas Disponibles' in ventas_por_destino.columns else 0
            
            # Recalcular porcentaje de ocupación global
            if plazas_totales_global > 0:
                plazas_ocupadas_global = plazas_reservadas_global + plazas_pagadas_global
                porcentaje_ocupacion_global = min(100, (plazas_ocupadas_global / plazas_totales_global) * 100)
        
        # Tabla de resumen de ventas por paquete
        col1, col2 = st.columns([3, 1])
        with col1:
            st.subheader("Resumen de Ventas por Paquete")
        
        # Obtener la fecha actual para calcular el tiempo restante para la salida
        fecha_actual = datetime.now().date()
        
        # Verificar si hay datos en la columna 'Código Paquete'
        if 'Código Paquete' in filtered_df.columns:
            # Primero, asegúrate de que la columna 'Fecha Salida' esté en formato de fecha
            filtered_df['Fecha Salida'] = pd.to_datetime(filtered_df['Fecha Salida'], errors='coerce').dt.date
            
            # Agrupar por paquete y obtener la primera ocurrencia de cada campo adicional
            # (asumiendo que todos los registros del mismo paquete tienen los mismos valores)
            ventas_por_paquete = filtered_df.groupby(['Código Paquete', 'Nombre Paquete', 'Destino', 'Lote']).agg({
                'Total': 'sum',
                'Comision': 'sum',
                'Pasajeros': 'sum',
                'Número': 'count',
                'Fecha Salida': 'first',
                'Plazas Totales': 'first',
                'Plazas Reservadas': 'first',
                'Plazas Pagadas': 'first',
                'Plazas Disponibles': 'first',
                'Estado de Paquete': 'first',
                'Estado de Paquete Codigo': 'first'
            }).reset_index()
            
            # Asegurarnos de que la columna 'Estado de Paquete' muestre los nombres descriptivos correctos
            # Recorrer cada fila y verificar si el estado es del tipo 'Estado X'
            for idx, row in ventas_por_paquete.iterrows():
                estado_actual = row['Estado de Paquete']
                codigo_estado = row['Estado de Paquete Codigo']
                
                # Si el estado actual es del tipo 'Estado X', intentar obtener el nombre descriptivo
                if isinstance(estado_actual, str) and estado_actual.startswith('Estado '):
                    try:
                        # Intentar convertir el código a entero y obtener el nombre del diccionario
                        codigo_int = int(codigo_estado) if codigo_estado is not None else None
                        if codigo_int is not None and codigo_int in ESTADO_PAQUETE:
                            ventas_por_paquete.at[idx, 'Estado de Paquete'] = ESTADO_PAQUETE[codigo_int]
                    except (ValueError, TypeError):
                        # Si hay algún error, mantener el valor original
                        pass
            
            ventas_por_paquete = ventas_por_paquete.rename(columns={
                'Número': 'Órdenes Mes',
                'Pasajeros': 'Pasajeros Mes'
            })
            ventas_por_paquete = ventas_por_paquete.sort_values(['Destino', 'Total'], ascending=[True, False])
            
            # Calcular tiempo restante y ocupación para cada paquete
            for idx, row in ventas_por_paquete.iterrows():
                # Calcular días restantes para la salida
                if pd.notna(row['Fecha Salida']):
                    dias_restantes = (row['Fecha Salida'] - fecha_actual).days
                    if dias_restantes < 0:
                        ventas_por_paquete.at[idx, 'Tiempo Restante'] = "Ya salió"
                    else:
                        ventas_por_paquete.at[idx, 'Tiempo Restante'] = f"{dias_restantes} días"
                else:
                    ventas_por_paquete.at[idx, 'Tiempo Restante'] = "Sin fecha"
                
                # Calcular porcentaje de ocupación
                plazas_totales = row['Plazas Totales'] or 0
                if plazas_totales > 0:
                    plazas_ocupadas = (row['Plazas Reservadas'] or 0) + (row['Plazas Pagadas'] or 0)
                    porcentaje_ocupacion = min(100, (plazas_ocupadas / plazas_totales) * 100)
                    ventas_por_paquete.at[idx, 'Ocupación'] = f"{int(porcentaje_ocupacion)}%"
                else:
                    ventas_por_paquete.at[idx, 'Ocupación'] = "0%"
            
            # Función para colorear las celdas de ocupación
            def color_ocupacion(val):
                # Extraer el número del porcentaje (quitar el símbolo %)
                try:
                    num = int(val.replace('%', ''))
                except:
                    return ''
                    
                # Definir colores por rango (invertidos)
                if num < 50:  # Menos del 50% - Rojo (baja ocupación)
                    return 'background-color: #ff9e82'  # Rojo claro
                elif num < 80:  # Entre 50% y 80% - Amarillo (ocupación media)
                    return 'background-color: #ffeb82'  # Amarillo claro
                else:  # Más del 80% - Verde (alta ocupación)
                    return 'background-color: #8eff8e'  # Verde claro
            
            # Función para colorear las celdas de tiempo restante
            def color_tiempo_restante(val):
                if 'Ya salió' in val:
                    return 'background-color: #d3d3d3'  # Gris para salidas pasadas
                elif 'Sin fecha' in val:
                    return ''  # Sin color para fechas no definidas
                
                try:
                    # Extraer el número de días
                    dias = int(val.split()[0])
                    
                    # Definir colores por rango de días
                    if dias <= 7:  # Última semana - Rojo (urgente)
                        return 'background-color: #ff9e82'  # Rojo claro
                    elif dias <= 30:  # Último mes - Amarillo (pronto)
                        return 'background-color: #ffeb82'  # Amarillo claro
                    else:  # Más de un mes - Verde (tiempo suficiente)
                        return 'background-color: #8eff8e'  # Verde claro
                except:
                    return ''
            
            # Agregar el botón de exportación justo debajo del título, en la esquina superior derecha
            col_exp1, col_exp2 = st.columns([3, 1])
            with col_exp2:
                # Botón de exportación
                export_dataframe_to_excel(
                    ventas_por_paquete, 
                    f"ventas_por_paquete_{selected_month}.xlsx"
                )
            
            # Mostrar la tabla con formato y colores
            st.dataframe(
                ventas_por_paquete[[
                    'Código Paquete', 'Nombre Paquete', 'Destino', 'Lote', 'Estado de Paquete', 'Fecha Salida', 'Tiempo Restante',
                    'Plazas Totales', 'Plazas Reservadas', 'Plazas Pagadas', 'Plazas Disponibles', 'Ocupación',
                    'Total', 'Comision', 'Pasajeros Mes', 'Órdenes Mes'
                ]].style.format({
                    'Total': lambda x: format_currency(x),
                    'Comision': lambda x: format_currency(x),
                    'Pasajeros Mes': lambda x: f"{int(x):,}".replace(',', '.'),
                    'Órdenes Mes': lambda x: f"{int(x):,}".replace(',', '.'),
                    'Plazas Totales': lambda x: f"{int(x):,}".replace(',', '.') if pd.notna(x) else "0",
                    'Plazas Reservadas': lambda x: f"{int(x):,}".replace(',', '.') if pd.notna(x) else "0",
                    'Plazas Pagadas': lambda x: f"{int(x):,}".replace(',', '.') if pd.notna(x) else "0",
                    'Plazas Disponibles': lambda x: f"{int(x):,}".replace(',', '.') if pd.notna(x) else "0"
                })
                .applymap(color_ocupacion, subset=['Ocupación'])
                .applymap(color_tiempo_restante, subset=['Tiempo Restante']),
                hide_index=True,
                use_container_width=True
            )
            
            # Agregar leyenda para los semáforos
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Semáforo de Ocupación:** 🔴 < 50% | 🟡 50-80% | 🟢 > 80%")
            with col2:
                st.markdown("**Semáforo de Tiempo:** 🟢 > 30 días | 🟡 8-30 días | 🔴 ≤7 días | ⬜ Ya salió")
        else:
            st.warning("No se encontró información de paquetes en los datos.")
        
        # Tabla detallada
        col1, col2 = st.columns([3, 1])
        with col1:
            st.subheader(f"Detalle de Órdenes - {selected_month}")
        with col2:
            # Botón de exportación justo debajo del título, en la esquina superior derecha
            if not filtered_df.empty:
                export_dataframe_to_excel(
                    filtered_df, 
                    f"detalle_ordenes_{selected_month}.xlsx"
                )
        
        # Crear un DataFrame con solo las columnas que queremos mostrar
        df_detalle = filtered_df[[
            'Número', 'Cliente', 'Fecha', 'Estado', 'Código Paquete', 'Nombre Paquete',
            'Destino', 'Lote', 'Pasajeros', 'Total', 'Comision', 'Agencia', 'Vendedor'
        ]].copy()
        
        st.dataframe(
            df_detalle.style.format({
                'Total': lambda x: format_currency(x),
                'Comision': lambda x: format_currency(x),
                'Pasajeros': lambda x: f"{int(x):,}".replace(',', '.')
            }),
            hide_index=True,
            use_container_width=True
        )
        
        # Eliminamos este botón ya que lo reposicionaremos
            
except Exception as e:
    st.error(f"Error al conectar con Odoo: {str(e)}")
    st.stop()
