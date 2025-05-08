import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import sys
import os
import plotly.express as px

# Agregar la ruta del proyecto al path de Python
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from odoo_client import OdooClient
from dotenv import load_dotenv
from babel.dates import format_date

# Cargar variables de entorno
load_dotenv()

# Mapeo de estados de paquete
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

# Funciones para colorear celdas
def color_ocupacion(val):
    """Colorea las celdas de ocupación según el valor"""
    try:
        val = float(val.strip('%'))
        if val > 80:
            return 'background-color: #8eff8e'  # Verde claro
        elif val >= 50:
            return 'background-color: #ffeb82'  # Amarillo claro
        else:
            return 'background-color: #ff8e8e'  # Rojo claro
    except:
        return ''

def color_tiempo_restante(val):
    """Colorea las celdas de tiempo restante según el valor"""
    try:
        if 'Ya salió' in val:
            return 'background-color: #f0f0f0'  # Gris claro
        elif 'días' in val:
            dias = int(val.split()[0])
            if dias <= 7:  # Una semana o menos - Rojo
                return 'background-color: #ff8e8e'  # Rojo claro
            elif dias <= 30:  # Un mes o menos - Amarillo
                return 'background-color: #ffeb82'  # Amarillo claro
            else:  # Más de un mes - Verde
                return 'background-color: #8eff8e'  # Verde claro
    except:
        return ''

# Función para calcular el tiempo restante para la salida
def calcular_tiempo_restante(fecha_salida_str, fecha_actual):
    """Calcula el tiempo restante para la salida del paquete"""
    try:
        if not fecha_salida_str:
            return "Sin fecha"
            
        # Convertir la fecha de salida a objeto datetime
        fecha_salida = datetime.strptime(fecha_salida_str, '%Y-%m-%d').date()
        
        # Calcular la diferencia en días
        dias_restantes = (fecha_salida - fecha_actual).days
        
        if dias_restantes < 0:
            return f"Ya salió ({abs(dias_restantes)} días)"
        elif dias_restantes == 0:
            return "Hoy"
        elif dias_restantes == 1:
            return "1 día"
        else:
            return f"{dias_restantes} días"
    except Exception as e:
        return "Fecha inválida"

# Configuración de la página
st.set_page_config(page_title="Ocupación de Paquetes", layout="wide")
st.title("Ocupación de Paquetes")

try:
    # Crear cliente Odoo
    client = OdooClient()
    
    # Obtener todos los paquetes (product.template)
    templates = client.search_read(
        'product.template',
        domain=[],
        fields=[
            'id', 'name', 'default_code', 'x_studio_lote', 'x_studio_destino',
            'x_studio_transporte', 'x_studio_ida_fecha_salida', 'x_studio_boletos_totales',
            'x_studio_boletos_reservados', 'x_product_count_pagados_stat_inf',
            'x_studio_boletos_disponibles', 'x_studio_tipo_de_cupo', 'x_studio_estado_viaje',
            'list_price', 'x_studio_comision_agencia'
        ]
    )
    
    # Convertir a DataFrame
    df_templates = pd.DataFrame(templates)
    
    # Mapear los estados a nombres descriptivos
    def mapear_estado(estado):
        if pd.isna(estado):
            return 'No definido'
        try:
            # Si es un número entero, usamos el diccionario de mapeo
            if isinstance(estado, (int, float)):
                return ESTADO_PAQUETE.get(int(estado), f'Estado {int(estado)}')
            # Si es una cadena que comienza con 'Estado ', extraemos el número
            elif isinstance(estado, str) and estado.startswith('Estado '):
                try:
                    num_estado = int(estado.replace('Estado ', ''))
                    return ESTADO_PAQUETE.get(num_estado, estado)
                except ValueError:
                    return estado
            else:
                return estado
        except:
            return f'Estado {estado}' if pd.notna(estado) else 'No definido'
    
    # Guardar el código original del estado y aplicar el mapeo
    df_templates['Estado de Paquete Codigo'] = df_templates['x_studio_estado_viaje']
    df_templates['Estado de Paquete'] = df_templates['Estado de Paquete Codigo'].apply(mapear_estado)
    
    # Crear contenedor para filtros al inicio de la página
    st.subheader("Filtros")
    filtros_container = st.container()
    
    with filtros_container:
        col1, col2 = st.columns(2)
        
        with col1:
            # Filtro de estado de paquete
            # Obtener los valores únicos de Estado de Paquete Codigo
            codigos_unicos = []
            for codigo in df_templates['Estado de Paquete Codigo'].dropna().unique():
                if codigo is not None:
                    try:
                        # Intentar convertir a entero
                        codigo_int = int(codigo)
                        codigos_unicos.append(codigo_int)
                    except (ValueError, TypeError):
                        # Si no se puede convertir, usar el valor original
                        codigos_unicos.append(codigo)
            
            # Crear un diccionario para mapear códigos a nombres
            nombres_estados = {codigo: ESTADO_PAQUETE.get(codigo, f'Estado {codigo}') for codigo in codigos_unicos}
            
            # Mostrar los nombres de los estados en el filtro
            opciones_estados = sorted(nombres_estados.values())
            
            # Estados por defecto (Activo, Validación)
            default_estados = []
            if 'Activo' in opciones_estados:
                default_estados.append('Activo')
            if 'Validación' in opciones_estados:
                default_estados.append('Validación')
            
            # Multiselect para filtrar por estado
            estados_seleccionados_nombres = st.multiselect(
                "Estado de Paquete",
                options=opciones_estados,
                default=default_estados
            )
            
            # Guardar los nombres seleccionados directamente
            # Ya no necesitamos convertir a códigos porque filtraremos por nombre
            estados_seleccionados = estados_seleccionados_nombres
            
            # Filtro de tipo de cupo
            tipos_cupo_unicos = sorted(df_templates['x_studio_tipo_de_cupo'].dropna().unique())
            tipos_cupo_seleccionados = st.multiselect(
                "Tipo de Cupo",
                options=tipos_cupo_unicos,
                default=[]
            )
        
        with col2:
            # Filtro de lote
            lotes_unicos = sorted(df_templates['x_studio_lote'].dropna().unique())
            lote_seleccionado = st.selectbox(
                "Lote",
                options=["Todos"] + list(lotes_unicos),
                index=0
            )
            
            # Filtro de destino
            destinos_unicos = sorted(df_templates['x_studio_destino'].dropna().unique())
            destinos_seleccionados = st.multiselect(
                "Destinos",
                options=destinos_unicos,
                default=[]
            )
            
            # Filtro de mes-año de salida
            # Convertir las fechas de salida a objetos datetime
            fechas_salida = pd.to_datetime(df_templates['x_studio_ida_fecha_salida'], errors='coerce')
            
            # Extraer mes-año de las fechas válidas
            meses_anio = []
            for fecha in fechas_salida.dropna():
                mes_anio = fecha.strftime('%B %Y')  # Formato: 'Mayo 2025'
                if mes_anio not in meses_anio:
                    meses_anio.append(mes_anio)
            
            # Ordenar los meses-año cronológicamente
            # Primero convertimos a objetos datetime para ordenar
            meses_anio_ordenados = sorted(meses_anio, 
                                         key=lambda x: pd.to_datetime(x, format='%B %Y', errors='coerce'))
            
            # Crear el filtro multiselect
            meses_anio_seleccionados = st.multiselect(
                "Mes-Año de Salida",
                options=meses_anio_ordenados,
                default=[]
            )
    
    # Aplicar filtros
    df_templates_filtrado = df_templates.copy()
    
    # Filtrar por estado usando los nombres de los estados
    if estados_seleccionados:
        # Función para mapear códigos numéricos a nombres descriptivos
        def mapear_codigo_a_nombre(codigo):
            try:
                if pd.isna(codigo):
                    return 'No definido'
                # Si es un string que representa un número, convertirlo a entero
                if isinstance(codigo, str) and codigo.isdigit():
                    codigo_int = int(codigo)
                    return ESTADO_PAQUETE.get(codigo_int, f'Estado {codigo}')
                # Si ya es un número, usarlo directamente
                elif isinstance(codigo, (int, float)):
                    return ESTADO_PAQUETE.get(int(codigo), f'Estado {codigo}')
                else:
                    return f'Estado {codigo}'
            except:
                return f'Estado {codigo}'
                
        # Aplicar la función de mapeo
        df_templates_filtrado['Estado de Paquete'] = df_templates_filtrado['Estado de Paquete Codigo'].apply(mapear_codigo_a_nombre)
        
        # Filtrar por los nombres seleccionados
        df_templates_filtrado = df_templates_filtrado[df_templates_filtrado['Estado de Paquete'].isin(estados_seleccionados)]
    
    # Filtrar por tipo de cupo
    if tipos_cupo_seleccionados:
        df_templates_filtrado = df_templates_filtrado[df_templates_filtrado['x_studio_tipo_de_cupo'].isin(tipos_cupo_seleccionados)]
    
    # Filtrar por lote
    if lote_seleccionado != "Todos":
        df_templates_filtrado = df_templates_filtrado[df_templates_filtrado['x_studio_lote'] == lote_seleccionado]
    
    # Filtrar por destino
    if destinos_seleccionados:
        df_templates_filtrado = df_templates_filtrado[df_templates_filtrado['x_studio_destino'].isin(destinos_seleccionados)]
    
    # Filtrar por mes-año de salida
    if meses_anio_seleccionados:
        # Convertir las fechas de salida a objetos datetime
        df_templates_filtrado = df_templates_filtrado.copy()  # Crear una copia para evitar warnings
        df_templates_filtrado['fecha_temp'] = pd.to_datetime(df_templates_filtrado['x_studio_ida_fecha_salida'], errors='coerce')
        
        # Crear una columna de mes-año para facilitar el filtrado
        def obtener_mes_anio(fecha):
            if pd.isna(fecha):
                return ''
            return fecha.strftime('%B %Y')
        
        # Aplicar la función para crear la columna de mes-año
        df_templates_filtrado['mes_anio'] = df_templates_filtrado['fecha_temp'].apply(obtener_mes_anio)
        
        # Filtrar las filas donde el mes-año está en los seleccionados
        df_templates_filtrado = df_templates_filtrado[df_templates_filtrado['mes_anio'].isin(meses_anio_seleccionados)]
        
        # Eliminar las columnas temporales
        df_templates_filtrado = df_templates_filtrado.drop(['fecha_temp', 'mes_anio'], axis=1)
    
    if not df_templates_filtrado.empty:
        # Asegurarse de que la columna de plazas pagadas esté presente
        if 'x_product_count_pagados_stat_inf' not in df_templates_filtrado.columns:
            df_templates_filtrado['x_product_count_pagados_stat_inf'] = 0
        
        # Renombrar para claridad
        df_templates_filtrado['Plazas Pagadas'] = df_templates_filtrado['x_product_count_pagados_stat_inf']
        
        # Calcular indicadores generales
        total_plazas = df_templates_filtrado['x_studio_boletos_totales'].sum()
        plazas_pagadas = df_templates_filtrado['Plazas Pagadas'].sum()
        plazas_reservadas = df_templates_filtrado['x_studio_boletos_reservados'].sum()
        plazas_disponibles = df_templates_filtrado['x_studio_boletos_disponibles'].sum()
        
        # Calcular porcentaje de ocupación global
        porcentaje_ocupacion = (plazas_pagadas / total_plazas * 100) if total_plazas > 0 else 0
        
        # Mostrar indicadores en tarjetas
        st.subheader('Indicadores Generales')
        
        # Crear 4 columnas para las tarjetas
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Plazas Programadas", f"{int(total_plazas):,}".replace(',', '.'))
            
        with col2:
            st.metric("Plazas Pagadas", f"{int(plazas_pagadas):,}".replace(',', '.'))
            
        with col3:
            st.metric("Plazas Reservadas", f"{int(plazas_reservadas):,}".replace(',', '.'))
            
        with col4:
            st.metric("Plazas Disponibles", f"{int(plazas_disponibles):,}".replace(',', '.'))
        
        # Barra de progreso para el porcentaje de ocupación
        st.markdown(f"### Porcentaje de Ocupación: {porcentaje_ocupacion:.1f}%")
        st.progress(porcentaje_ocupacion / 100)
        
        # Agregar espacio
        st.markdown("---")
        
        # Calcular ocupación basada en plazas pagadas y totales
        df_templates_filtrado['Ocupación'] = df_templates_filtrado.apply(
            lambda row: f"{int(row['Plazas Pagadas'] / row['x_studio_boletos_totales'] * 100)}%" 
            if pd.notna(row['x_studio_boletos_totales']) and row['x_studio_boletos_totales'] > 0 
            else "0%",
            axis=1
        )
        
        # Calcular tiempo restante para la salida
        fecha_actual = datetime.now().date()
        df_templates_filtrado['Tiempo Restante'] = df_templates_filtrado.apply(
            lambda row: calcular_tiempo_restante(row['x_studio_ida_fecha_salida'], fecha_actual), 
            axis=1
        )
        
        # Asegurarse de que la columna Estado de Paquete tenga los nombres descriptivos
        df_templates_filtrado['Estado de Paquete'] = df_templates_filtrado['Estado de Paquete Codigo'].apply(mapear_estado)
        
        # Crear resumen por destino
        resumen_destino = df_templates_filtrado.groupby('x_studio_destino').agg({
            'id': 'count',
            'x_studio_boletos_totales': 'sum',
            'Plazas Pagadas': 'sum',
            'x_studio_boletos_reservados': 'sum',
            'x_studio_boletos_disponibles': 'sum',
            'list_price': 'mean'
        }).reset_index()
        
        resumen_destino.columns = [
            'Destino', 'Cantidad Paquetes', 'Plazas Totales', 'Plazas Pagadas',
            'Plazas Reservadas', 'Plazas Disponibles', 'Precio Promedio'
        ]
        
        # Calcular ocupación por destino basada en plazas pagadas
        resumen_destino['Ocupación'] = resumen_destino.apply(
            lambda row: f"{int(row['Plazas Pagadas'] / row['Plazas Totales'] * 100)}%" 
            if row['Plazas Totales'] > 0 else "0%",
            axis=1
        )
        
        # Gráfico de ocupación por destino
        st.subheader("Ocupación por Destino")
        
        # Preparar datos para el gráfico
        grafico_data = resumen_destino.copy()
        grafico_data['Porcentaje Ocupación'] = grafico_data['Ocupación'].apply(
            lambda x: float(x.strip('%')) if isinstance(x, str) else 0
        )
        
        # Crear un nuevo DataFrame con colores personalizados para cada barra
        grafico_data = grafico_data.sort_values('Porcentaje Ocupación', ascending=True)
        
        # Definir colores basados en el porcentaje de ocupación
        def get_color(porcentaje):
            if porcentaje < 50:
                return 'rgba(255, 0, 0, 0.7)'  # Rojo para menos del 50%
            elif porcentaje < 80:
                return 'rgba(255, 255, 0, 0.7)'  # Amarillo para 50-80%
            else:
                return 'rgba(0, 128, 0, 0.7)'  # Verde para más del 80%
        
        # Aplicar colores personalizados
        colores = grafico_data['Porcentaje Ocupación'].apply(get_color)
        
        # Crear gráfico de barras horizontal con colores personalizados
        fig = px.bar(
            grafico_data,
            y='Destino',
            x='Porcentaje Ocupación',
            title='Porcentaje de Ocupación por Destino',
            labels={'Porcentaje Ocupación': 'Ocupación (%)', 'Destino': 'Destino'},
            text=grafico_data['Porcentaje Ocupación'].apply(lambda x: f'{x:.1f}%')  # Mostrar porcentaje en cada barra
        )
        
        # Actualizar colores de las barras manualmente
        fig.update_traces(marker_color=colores.tolist(), textposition='auto')
        
        # Personalizar el gráfico
        fig.update_layout(
            height=400,
            margin=dict(l=0, r=0, t=40, b=0),
            showlegend=False
        )
        
        # Añadir una leyenda manual
        fig.add_shape(type='rect', x0=0, y0=-1.5, x1=10, y1=-1.2, fillcolor='rgba(255, 0, 0, 0.7)', line_color='rgba(255, 0, 0, 0.7)')
        fig.add_shape(type='rect', x0=15, y0=-1.5, x1=25, y1=-1.2, fillcolor='rgba(255, 255, 0, 0.7)', line_color='rgba(255, 255, 0, 0.7)')
        fig.add_shape(type='rect', x0=30, y0=-1.5, x1=40, y1=-1.2, fillcolor='rgba(0, 128, 0, 0.7)', line_color='rgba(0, 128, 0, 0.7)')
        
        fig.add_annotation(x=5, y=-1.35, text='< 50%', showarrow=False, font=dict(color='black'))
        fig.add_annotation(x=20, y=-1.35, text='50-80%', showarrow=False, font=dict(color='black'))
        fig.add_annotation(x=35, y=-1.35, text='> 80%', showarrow=False, font=dict(color='black'))
        
        st.plotly_chart(fig, use_container_width=True)
        
        # Mostrar resumen por destino
        st.subheader("Resumen por Destino")
        col1, col2 = st.columns([3, 1])
        with col1:
            st.subheader("Resumen de Paquetes por Destino")
        with col2:
            # Botón de exportación justo debajo del título, en la esquina superior derecha
            if not resumen_destino.empty:
                export_dataframe_to_excel(
                    resumen_destino, 
                    f"resumen_destino_paquetes.xlsx"
                )
        
        # Mostrar tabla de resumen por destino
        st.dataframe(
            resumen_destino.style.format({
                'Precio Promedio': lambda x: format_currency(x),
                'Cantidad Paquetes': lambda x: f"{int(x):,}".replace(',', '.'),
                'Plazas Totales': lambda x: f"{int(x):,}".replace(',', '.'),
                'Plazas Reservadas': lambda x: f"{int(x):,}".replace(',', '.'),
                'Plazas Disponibles': lambda x: f"{int(x):,}".replace(',', '.')
            })
            .applymap(color_ocupacion, subset=['Ocupación']),
            hide_index=True,
            use_container_width=True
        )
        
        # Tabla detallada de paquetes
        st.subheader("Detalle de Paquetes")
        col1, col2 = st.columns([3, 1])
        with col1:
            st.subheader("Listado de Paquetes")
        with col2:
            # Botón de exportación justo debajo del título, en la esquina superior derecha
            if not df_templates_filtrado.empty:
                export_dataframe_to_excel(
                    df_templates_filtrado, 
                    f"detalle_paquetes.xlsx"
                )
        
        # Asegurarse de que la columna Estado de Paquete tenga los nombres descriptivos
        # Esto es necesario porque puede que no se haya aplicado correctamente el mapeo
        df_templates_filtrado['Estado de Paquete'] = df_templates_filtrado['Estado de Paquete Codigo'].apply(mapear_estado)
        
        # Seleccionar y formatear columnas para la tabla
        df_detalle = df_templates_filtrado[[
            'default_code', 'name', 'x_studio_destino', 'x_studio_lote', 'Estado de Paquete',
            'x_studio_ida_fecha_salida', 'Tiempo Restante', 'x_studio_boletos_totales',
            'Plazas Pagadas', 'x_studio_boletos_reservados', 'x_studio_boletos_disponibles', 
            'Ocupación', 'list_price', 'x_studio_comision_agencia'
        ]].copy()
        
        # Renombrar columnas para mejor visualización
        df_detalle.columns = [
            'Código', 'Nombre Paquete', 'Destino', 'Lote', 'Estado',
            'Fecha Salida', 'Tiempo Restante', 'Plazas Totales',
            'Plazas Pagadas', 'Plazas Reservadas', 'Plazas Disponibles', 'Ocupación',
            'Precio', 'Comisión Agencia'
        ]
        
        # Aplicar directamente el mapeo de estados a la columna Estado
        # Convertir explícitamente los valores a enteros para usar como claves en el diccionario ESTADO_PAQUETE
        def mapear_estado_directo(valor):
            try:
                if pd.isna(valor):
                    return 'No definido'
                    
                # Si es una cadena, intentar convertirla a entero directamente
                if isinstance(valor, str):
                    try:
                        # Intentar convertir la cadena a entero
                        num_estado = int(valor)
                        return ESTADO_PAQUETE.get(num_estado, f'Estado {valor}')
                    except ValueError:
                        # Si es una cadena que comienza con 'Estado ', extraer el número
                        if valor.startswith('Estado '):
                            try:
                                num_estado = int(valor.replace('Estado ', ''))
                                return ESTADO_PAQUETE.get(num_estado, valor)
                            except ValueError:
                                return valor
                        return valor
                # Si es un número, convertirlo a entero
                elif isinstance(valor, (int, float)):
                    return ESTADO_PAQUETE.get(int(valor), f'Estado {valor}')
                else:
                    return str(valor)
            except Exception as e:
                st.error(f"Error al mapear estado: {e}, valor: {valor}, tipo: {type(valor)}")
                return f'Error: {valor}'
        
        # Aplicar la función de mapeo
        df_detalle['Estado'] = df_detalle['Estado'].apply(mapear_estado_directo)
        
        # La columna Estado ya contiene el nombre descriptivo del estado
        
        # Destacar la columna de estado
        st.markdown("""
        <style>
        [data-testid="stDataFrame"] table tbody tr td:nth-child(5) {
            font-weight: bold;
        }
        </style>
        """, unsafe_allow_html=True)
        
        # Mostrar tabla detallada
        st.dataframe(
            df_detalle.style.format({
                'Precio': lambda x: format_currency(x),
                'Comisión Agencia': lambda x: format_currency(x),
                'Plazas Totales': lambda x: f"{int(x):,}".replace(',', '.') if pd.notna(x) else "0",
                'Plazas Reservadas': lambda x: f"{int(x):,}".replace(',', '.') if pd.notna(x) else "0",
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
        st.warning("No se encontraron paquetes con los filtros seleccionados.")

except Exception as e:
    st.error(f"Error: {str(e)}")
    st.write("Detalles del error para debugging:", e)
