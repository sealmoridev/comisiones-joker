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

def to_excel(df, sheet_name='Sheet1'):
    """Convierte DataFrame a Excel XLSX"""
    from io import BytesIO
    output = BytesIO()
    df.to_excel(output, engine='openpyxl', sheet_name=sheet_name, index=False)
    return output.getvalue()

def load_orders_data(odoo, domain, fields, tipos_cupo_seleccionados):
    """Carga y procesa los datos de órdenes"""
    orders = odoo.search_read('sale.order', domain=domain, fields=fields)
    
    if not orders:
        return [], {}
    
    # Obtener todas las líneas de orden (no solo la primera)
    all_line_ids = []
    for order in orders:
        if order['order_line']:
            all_line_ids.extend(order['order_line'])
    
    # Obtener todas las líneas de orden
    all_lines = odoo.search_read(
        'sale.order.line',
        domain=[('id', 'in', all_line_ids)],
        fields=[
            'id', 
            'product_id', 
            'product_uom_qty',
            'name',
            'price_unit',
            'price_subtotal',
            'order_id'
        ]
    )
    
    # Crear diccionario de líneas por orden
    lines_by_order = {}
    for line in all_lines:
        order_id = line['order_id'][0]
        if order_id not in lines_by_order:
            lines_by_order[order_id] = []
        lines_by_order[order_id].append(line)
    
    # Obtener productos únicos
    product_ids = list(set(line['product_id'][0] for line in all_lines if line['product_id']))
    products = odoo.search_read(
        'product.template',
        domain=[('id', 'in', product_ids)],
        fields=['id', 
                'name',
                'default_code',
                'list_price',                
                'x_studio_comision_agencia',
                'x_studio_destino',
                'x_studio_tipo_de_cupo'
               ]
    )
    products_dict = {prod['id']: prod for prod in products}
    
    # Procesar órdenes
    orders_data = []
    resumen_agencias = {}
    ordenes_procesadas_por_agencia = {}  # Para evitar contar la misma orden múltiples veces
    
    for order in orders:
        order_lines = lines_by_order.get(order['id'], [])
        team_id = order['team_id'][0] if order['team_id'] else 0
        team_name = order['team_id'][1] if order['team_id'] else 'Sin Agencia'
        
        # Inicializar resumen de agencia si no existe
        if team_name not in resumen_agencias:
            resumen_agencias[team_name] = {
                'Agencia': team_name,
                'Total Órdenes': 0,
                'Total Pasajeros': 0,
                'Total Comisiones': 0,
                'Total Vendido': 0
            }
            ordenes_procesadas_por_agencia[team_name] = set()
        
        # Variable para verificar si la orden tiene líneas válidas (que pasen el filtro)
        orden_tiene_lineas_validas = False
        
        # Procesar cada línea de la orden
        for line in order_lines:
            if line['product_id']:
                product = products_dict.get(line['product_id'][0])
                if product:
                    # Filtrar por tipo de cupo si hay selecciones
                    if tipos_cupo_seleccionados and product.get('x_studio_tipo_de_cupo') not in tipos_cupo_seleccionados:
                        continue
                    
                    # Marcar que la orden tiene al menos una línea válida
                    orden_tiene_lineas_validas = True
                    
                    comision_rate = product.get('x_studio_comision_agencia', 0)
                    cantidad = line['product_uom_qty']
                    comision = comision_rate * cantidad
                    
                    orders_data.append({
                        'Número': order['name'],
                        'Cliente': order['partner_id'][1] if order['partner_id'] else 'Sin cliente',
                        'Fecha': datetime.strptime(order['date_order'], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M"),
                        'Producto': product.get('name', 'Sin nombre'),
                        'Destino': product.get('x_studio_destino', 'Sin destino'),
                        'Tipo de Cupo': product.get('x_studio_tipo_de_cupo', 'No definido'),
                        'Estado Facturación': INVOICE_STATUS[order['invoice_status']],
                        'Agencia': team_name,
                        'Vendedor': order['user_id'][1] if order['user_id'] else 'Sin asignar',
                        'Cantidad': int(cantidad),
                        'Comision': float(comision),
                        'Total': float(line['price_subtotal']),  # Usar subtotal de la línea
                        'ID': int(order['id'])
                    })
                    
                    # Actualizar resumen de agencia
                    resumen_agencias[team_name]['Total Pasajeros'] += cantidad
                    resumen_agencias[team_name]['Total Comisiones'] += comision
                    resumen_agencias[team_name]['Total Vendido'] += line['price_subtotal']
        
        # Contar la orden solo una vez por agencia y solo si tiene líneas válidas
        if orden_tiene_lineas_validas and order['id'] not in ordenes_procesadas_por_agencia[team_name]:
            resumen_agencias[team_name]['Total Órdenes'] += 1
            ordenes_procesadas_por_agencia[team_name].add(order['id'])
    
    return orders_data, resumen_agencias


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
            tipos_cupo_seleccionados = st.multiselect(
                "Seleccionar Tipos de Cupo",
                options=list(TIPO_CUPO.keys()),
                default=['Regular', 'Sin Subsidio'],
                format_func=lambda x: TIPO_CUPO[x],
                key="tipos_cupo",
                help="Seleccione uno o más tipos de cupo"
            )
        
        # Tercera fila para comparación con año anterior
        st.subheader("Comparación Anual")
        comparar_año_anterior = st.checkbox(
            "Comparar con el mismo período del año anterior",
            value=False,
            help="Muestra datos del año actual vs el año anterior en las mismas fechas"
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

    with st.spinner('Cargando órdenes del año actual...'):
        # Cargar datos del año actual
        orders_data, resumen_agencias = load_orders_data(odoo, domain, fields, tipos_cupo_seleccionados)
        progress_bar.progress(50, text="Datos del año actual cargados...")
        
        # Cargar datos del año anterior si está habilitada la comparación
        orders_data_prev = []
        resumen_agencias_prev = {}
        
        # Calcular fechas del año anterior (siempre definidas)
        fecha_inicio_prev = fecha_inicio_selected.replace(year=fecha_inicio_selected.year - 1)
        fecha_fin_prev = fecha_fin_selected.replace(year=fecha_fin_selected.year - 1)
        
        if comparar_año_anterior:
            
            # Crear dominio para el año anterior
            domain_prev = [
                ("date_order", ">=", f"{fecha_inicio_prev} 00:00:00"),
                ("date_order", "<=", f"{fecha_fin_prev} 23:59:59"),
                ("invoice_status", "in", estado_facturacion)
            ]
            
            # Agregar filtro de agencia si no es "Todos"
            if agencia_seleccionada != 0:
                domain_prev.append(("team_id", "=", agencia_seleccionada))
            
            with st.spinner('Cargando órdenes del año anterior...'):
                orders_data_prev, resumen_agencias_prev = load_orders_data(odoo, domain_prev, fields, tipos_cupo_seleccionados)
                progress_bar.progress(75, text="Datos del año anterior cargados...")
        
        progress_bar.progress(100, text="¡Completado!")

        if orders_data or orders_data_prev:

            # Calcular métricas globales del año actual
            total_ordenes = len(orders_data)
            total_pasajeros = sum(resumen['Total Pasajeros'] for resumen in resumen_agencias.values())
            total_comisiones = sum(resumen['Total Comisiones'] for resumen in resumen_agencias.values())
            total_ventas = sum(resumen['Total Vendido'] for resumen in resumen_agencias.values())

            # Calcular métricas del año anterior si está habilitada la comparación
            if comparar_año_anterior:
                total_ordenes_prev = len(orders_data_prev)
                total_pasajeros_prev = sum(resumen['Total Pasajeros'] for resumen in resumen_agencias_prev.values())
                total_comisiones_prev = sum(resumen['Total Comisiones'] for resumen in resumen_agencias_prev.values())
                total_ventas_prev = sum(resumen['Total Vendido'] for resumen in resumen_agencias_prev.values())
                
                # Calcular diferencias
                delta_ordenes = total_ordenes - total_ordenes_prev
                delta_pasajeros = total_pasajeros - total_pasajeros_prev
                delta_comisiones = total_comisiones - total_comisiones_prev
                delta_ventas = total_ventas - total_ventas_prev
            else:
                delta_ordenes = delta_pasajeros = delta_comisiones = delta_ventas = None

            # Mostrar métricas en fila
            periodo_actual = f"{fecha_inicio_selected.strftime('%Y-%m-%d')} a {fecha_fin_selected.strftime('%Y-%m-%d')}"
            if comparar_año_anterior:
                st.write(f"### Resumen General - Comparación Anual")
                st.write(f"**Período Actual:** {periodo_actual}")
                st.write(f"**Período Anterior:** {fecha_inicio_prev.strftime('%Y-%m-%d')} a {fecha_fin_prev.strftime('%Y-%m-%d')}")
            else:
                st.write(f"### Resumen General - {periodo_actual}")
            
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric(
                    label="Total Órdenes",
                    value=format_currency(total_ordenes, 0),
                    delta=f"{delta_ordenes:+}" if delta_ordenes is not None else None
                )

            with col2:
                st.metric(
                    label="Total Pasajeros",
                    value=format_currency(total_pasajeros, 0),
                    delta=f"{delta_pasajeros:+}" if delta_pasajeros is not None else None
                )

            with col3:
                st.metric(
                    label="Total Comisiones",
                    value=f"CLP {format_currency(total_comisiones, 0)}",
                    delta=f"{delta_comisiones:+,.0f}" if delta_comisiones is not None else None
                )

            with col4:
                st.metric(
                    label="Total Ventas",
                    value=f"CLP {format_currency(total_ventas, 0)}",
                    delta=f"{delta_ventas:+,.0f}" if delta_ventas is not None else None
                )

            # Agregar un separador
            st.markdown("---")

            # Continuar con el resto del código...
            
            # Tabla de resumen por agencia
            st.subheader("Resumen por Agencia")
            
            if comparar_año_anterior and resumen_agencias_prev:
                # Crear DataFrame combinado para comparación
                df_actual = pd.DataFrame(list(resumen_agencias.values()))
                df_anterior = pd.DataFrame(list(resumen_agencias_prev.values()))
                
                # Renombrar columnas para identificar el año
                df_actual = df_actual.rename(columns={
                    'Total Órdenes': f'Órdenes {fecha_inicio_selected.year}',
                    'Total Pasajeros': f'Pasajeros {fecha_inicio_selected.year}',
                    'Total Comisiones': f'Comisiones {fecha_inicio_selected.year}',
                    'Total Vendido': f'Vendido {fecha_inicio_selected.year}'
                })
                
                df_anterior = df_anterior.rename(columns={
                    'Total Órdenes': f'Órdenes {fecha_inicio_prev.year}',
                    'Total Pasajeros': f'Pasajeros {fecha_inicio_prev.year}',
                    'Total Comisiones': f'Comisiones {fecha_inicio_prev.year}',
                    'Total Vendido': f'Vendido {fecha_inicio_prev.year}'
                })
                
                # Combinar datos para mostrar lado a lado
                df_combined = pd.merge(df_actual, df_anterior, on='Agencia', how='outer', suffixes=(f' {fecha_inicio_selected.year}', f' {fecha_inicio_prev.year}'))
                df_combined = df_combined.fillna(0)
                
                # Calcular deltas
                df_combined[f'Δ Órdenes'] = df_combined[f'Órdenes {fecha_inicio_selected.year}'] - df_combined[f'Órdenes {fecha_inicio_prev.year}']
                df_combined[f'Δ Pasajeros'] = df_combined[f'Pasajeros {fecha_inicio_selected.year}'] - df_combined[f'Pasajeros {fecha_inicio_prev.year}']
                df_combined[f'Δ Comisiones'] = df_combined[f'Comisiones {fecha_inicio_selected.year}'] - df_combined[f'Comisiones {fecha_inicio_prev.year}']
                df_combined[f'Δ Vendido'] = df_combined[f'Vendido {fecha_inicio_selected.year}'] - df_combined[f'Vendido {fecha_inicio_prev.year}']
                
                # Crear copia para descarga (valores numéricos)
                df_resumen_download = df_combined.copy()
                
                # Crear copia para visualización (con formato CLP)
                df_resumen = df_combined.copy()
                for col in df_resumen.columns:
                    if 'Comisiones' in col or 'Vendido' in col:
                        df_resumen[col] = df_resumen[col].apply(lambda x: f"CLP {format_currency(x, 0)}")
                
            else:
                # Tabla normal sin comparación
                df_resumen_base = pd.DataFrame(list(resumen_agencias.values()))
                
                # Crear copia para descarga (valores numéricos)
                df_resumen_download = df_resumen_base.copy()
                
                # Crear copia para visualización (con formato CLP)
                df_resumen = df_resumen_base.copy()
                df_resumen['Total Comisiones'] = df_resumen['Total Comisiones'].apply(lambda x: f"CLP {format_currency(x, 0)}")
                df_resumen['Total Vendido'] = df_resumen['Total Vendido'].apply(lambda x: f"CLP {format_currency(x, 0)}")

            # Botón para descargar resumen en Excel
            filename = "resumen_agencias_comparacion.xlsx" if comparar_año_anterior else "resumen_agencias.xlsx"
            st.download_button(
                label="📥 Descargar Resumen por Agencia (Excel)",
                data=to_excel(df_resumen_download, 'Resumen Agencias'),
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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
            
            # Combinar órdenes del año actual y anterior si está habilitada la comparación
            all_orders_data = orders_data.copy()
            
            if comparar_año_anterior and orders_data_prev:
                # Agregar columna de año para identificar las órdenes
                for order in all_orders_data:
                    order['Año'] = fecha_inicio_selected.year
                
                orders_prev_with_year = orders_data_prev.copy()
                for order in orders_prev_with_year:
                    order['Año'] = fecha_inicio_prev.year
                
                # Combinar todas las órdenes
                all_orders_data.extend(orders_prev_with_year)
            
            df_orders = pd.DataFrame(all_orders_data)

            if df_orders.empty:
                st.warning("No hay órdenes para mostrar con los filtros seleccionados")
            else:
                # Crear DataFrame para descarga (valores numéricos)
                df_orders_download = pd.DataFrame(all_orders_data)
                if 'ID' in df_orders_download.columns:
                    df_orders_download = df_orders_download.drop('ID', axis=1)
                
                # Crear DataFrame para mostrar (con formato CLP)
                df_orders_display = pd.DataFrame(all_orders_data)
                
                # Formatear columnas monetarias para visualización
                if 'Comision' in df_orders_display.columns:
                    df_orders_display['Comision'] = df_orders_display['Comision'].apply(
                        lambda x: f"CLP {format_currency(float(x), 0)}" if pd.notna(x) else "CLP 0"
                    )

                if 'Total' in df_orders_display.columns:
                    df_orders_display['Total'] = df_orders_display['Total'].apply(
                        lambda x: f"CLP {format_currency(float(x), 0)}" if pd.notna(x) else "CLP 0"
                    )
                
                # Reordenar columnas para mostrar el año al principio si hay comparación
                if comparar_año_anterior and 'Año' in df_orders_display.columns:
                    cols = ['Año'] + [col for col in df_orders_display.columns if col != 'Año' and col != 'ID']
                    df_orders_display = df_orders_display[cols]
                    # También reordenar para descarga
                    if 'Año' in df_orders_download.columns:
                        cols_download = ['Año'] + [col for col in df_orders_download.columns if col != 'Año']
                        df_orders_download = df_orders_download[cols_download]
                else:
                    # Remover columna ID para la visualización
                    if 'ID' in df_orders_display.columns:
                        df_orders_display = df_orders_display.drop('ID', axis=1)

                # Botón para descargar órdenes en Excel
                filename = "ordenes_comparacion.xlsx" if comparar_año_anterior else "ordenes.xlsx"
                st.download_button(
                    label="📥 Descargar Órdenes (Excel)",
                    data=to_excel(df_orders_download, 'Órdenes'),
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

                # Mostrar tabla de órdenes
                selected_order = st.data_editor(
                    df_orders_display,
                    use_container_width=True,
                    disabled=True,
                    key="orders_table"
                )
                
                # Mostrar información adicional
                if comparar_año_anterior:
                    ordenes_actuales = len([o for o in all_orders_data if o.get('Año') == fecha_inicio_selected.year])
                    ordenes_anteriores = len([o for o in all_orders_data if o.get('Año') == fecha_inicio_prev.year])
                    st.info(f"Mostrando {ordenes_actuales} órdenes de {fecha_inicio_selected.year} y {ordenes_anteriores} órdenes de {fecha_inicio_prev.year}")
                else:
                    st.info(f"Mostrando {len(df_orders_display)} órdenes del período seleccionado")


        else:
            st.info("No se encontraron órdenes de venta con los filtros seleccionados")

except Exception as e:
    st.error(f"Error: {str(e)}")
    st.write("Detalles del error para debugging:", e)