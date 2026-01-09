import streamlit as st

# Configuración de la página - DEBE SER LA PRIMERA LLAMADA A STREAMLIT
st.set_page_config(page_title="Cuadratura de Pagos Conciliados", layout="wide")

import pandas as pd
import numpy as np
import io
import sys
import os
from datetime import datetime

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
from dotenv import load_dotenv

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

INVOICE_STATUS = {
    'upselling': 'Oportunidad de Venta Adicional',
    'invoiced': 'Facturado',
    'to invoice': 'Por Facturar',
    'no': 'Nada que Facturar'
}

# Funciones de utilidad
def format_currency(value, decimals=0):
    """Formatea un número como moneda con separadores de miles"""
    try:
        return f"${int(float(value)):,}".replace(',', '.')
    except (ValueError, TypeError):
        return value


def export_dataframe_to_excel(df, filename, styler=None):
    """Exporta un DataFrame a Excel y devuelve un botón de descarga"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        if styler is not None:
            styler.to_excel(writer, index=False)
        else:
            df.to_excel(writer, index=False)

    excel_data = output.getvalue()
    return st.download_button(
        label=f"📥 Exportar a Excel",
        data=excel_data,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def safe_m2o_name(value):
    if not value:
        return ''
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return value[1]
    return str(value)


def get_first_existing_field(fields_meta, candidates):
    for c in candidates:
        if c in fields_meta:
            return c
    return None


def safe_float(value, default=0.0):
    try:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def extract_payment_applications_via_reconcile(odoo, invoice_ids, invoices_dict, inv_state_field, payment_state_field):
    """Construye detalle de pagos por factura usando conciliaciones (account.partial.reconcile).

    Devuelve:
    - df_payments: 1 fila por aplicación de pago a factura (monto aplicado)
    - applied_by_invoice: dict invoice_id -> monto aplicado total
    """

    if not invoice_ids:
        return pd.DataFrame(), {}

    # Verificar disponibilidad del modelo
    try:
        pr_fields_meta = odoo.fields_get('account.partial.reconcile')
    except Exception:
        return pd.DataFrame(), {}

    # 1) Obtener líneas de cuenta de las facturas (buscamos líneas receivable/payable)
    aml_fields_meta = odoo.fields_get('account.move.line')
    internal_type_field = get_first_existing_field(aml_fields_meta, ['account_internal_type', 'internal_type'])

    aml_fields = ['id', 'move_id', 'date', 'name', 'partner_id', 'account_id', 'debit', 'credit', 'balance']
    if internal_type_field:
        aml_fields.append(internal_type_field)

    invoice_lines = odoo.search_read(
        'account.move.line',
        domain=[('move_id', 'in', invoice_ids)],
        fields=aml_fields
    )

    if not invoice_lines:
        return pd.DataFrame(), {}

    df_inv_lines = pd.DataFrame(invoice_lines)

    # Filtrar receivable/payable si tenemos el campo
    if internal_type_field and internal_type_field in df_inv_lines.columns:
        df_inv_lines = df_inv_lines[df_inv_lines[internal_type_field].isin(['receivable', 'payable'])]

    invoice_line_ids = df_inv_lines['id'].dropna().astype(int).unique().tolist()
    if not invoice_line_ids:
        return pd.DataFrame(), {}

    # 2) Obtener conciliaciones parciales para esas líneas
    pr_amount_field = get_first_existing_field(pr_fields_meta, ['amount', 'amount_currency'])
    pr_fields = ['id', 'debit_move_id', 'credit_move_id']
    if pr_amount_field and pr_amount_field not in pr_fields:
        pr_fields.append(pr_amount_field)
    if 'max_date' in pr_fields_meta:
        pr_fields.append('max_date')
    elif 'create_date' in pr_fields_meta:
        pr_fields.append('create_date')

    # En algunas instancias Odoo responde 400 si el dominio tiene demasiados IDs en el "in".
    # Para evitarlo, consultamos en batches y unimos los resultados.
    partials = []
    # Batch más pequeño para evitar 400 por payload/domains grandes
    batch_size = 50
    any_batch_ok = False
    for i in range(0, len(invoice_line_ids), batch_size):
        batch_ids = invoice_line_ids[i:i + batch_size]
        try:
            batch_partials = odoo.search_read(
                'account.partial.reconcile',
                domain=['|', ('debit_move_id', 'in', batch_ids), ('credit_move_id', 'in', batch_ids)],
                fields=pr_fields
            )
            any_batch_ok = True
            if batch_partials:
                partials.extend(batch_partials)
        except Exception:
            # Si un batch falla, continuamos con los otros (mejor "algo" que nada).
            continue

    # Si todos los batches fallaron, devolvemos vacío para que se use el fallback.
    if not any_batch_ok:
        return pd.DataFrame(), {}

    # Deduplicar por id
    if partials:
        seen = set()
        uniq = []
        for r in partials:
            rid = r.get('id')
            if rid in seen:
                continue
            seen.add(rid)
            uniq.append(r)
        partials = uniq

    if not partials:
        return pd.DataFrame(), {}

    df_pr = pd.DataFrame(partials)

    # 3) Obtener todas las líneas involucradas (para resolver el "otro lado" = pago)
    move_line_ids = set()
    for _, r in df_pr.iterrows():
        d = r.get('debit_move_id')
        c = r.get('credit_move_id')
        if isinstance(d, (list, tuple)) and d:
            move_line_ids.add(int(d[0]))
        if isinstance(c, (list, tuple)) and c:
            move_line_ids.add(int(c[0]))

    move_line_ids = sorted(move_line_ids)
    if not move_line_ids:
        return pd.DataFrame(), {}

    involved_lines = odoo.search_read(
        'account.move.line',
        domain=[('id', 'in', move_line_ids)],
        fields=aml_fields
    )
    df_lines = pd.DataFrame(involved_lines)
    if df_lines.empty:
        return pd.DataFrame(), {}

    # Map line_id -> move_id
    line_to_move = {}
    line_to_partner = {}
    line_to_date = {}
    for _, row in df_lines.iterrows():
        lid = int(row['id'])
        mv = row.get('move_id')
        line_to_move[lid] = mv[0] if isinstance(mv, (list, tuple)) and mv else None
        line_to_partner[lid] = safe_m2o_name(row.get('partner_id'))
        line_to_date[lid] = row.get('date')

    # 4) Determinar para cada partial reconcile: invoice_line vs payment_line
    invoice_line_id_set = set(invoice_line_ids)

    pay_rows = []
    applied_by_invoice = {}
    for _, r in df_pr.iterrows():
        d = r.get('debit_move_id')
        c = r.get('credit_move_id')
        d_id = int(d[0]) if isinstance(d, (list, tuple)) and d else None
        c_id = int(c[0]) if isinstance(c, (list, tuple)) and c else None
        if not d_id or not c_id:
            continue

        amount_applied = safe_float(r.get(pr_amount_field)) if pr_amount_field else 0.0
        if amount_applied == 0.0:
            continue

        # Caso A: debit es factura, credit es pago
        if d_id in invoice_line_id_set:
            invoice_move_id = line_to_move.get(d_id)
            payment_move_id = line_to_move.get(c_id)
        # Caso B: credit es factura, debit es pago
        elif c_id in invoice_line_id_set:
            invoice_move_id = line_to_move.get(c_id)
            payment_move_id = line_to_move.get(d_id)
        else:
            continue

        if not invoice_move_id or invoice_move_id not in invoices_dict:
            continue

        inv = invoices_dict[invoice_move_id]

        # Asegurar posted (por si el dict trae otros)
        if inv_state_field and inv.get(inv_state_field) != 'posted':
            continue

        applied_by_invoice[invoice_move_id] = applied_by_invoice.get(invoice_move_id, 0.0) + amount_applied

        pr_date = None
        if 'max_date' in r and r.get('max_date'):
            pr_date = r.get('max_date')
        elif 'create_date' in r and r.get('create_date'):
            pr_date = str(r.get('create_date'))

        pay_rows.append({
            'Factura ID': int(inv.get('id')),
            'Factura': inv.get('name', ''),
            'Factura Origen': inv.get('invoice_origin', ''),
            'Estado Pago Factura': inv.get(payment_state_field, '') if payment_state_field else '',
            'Pago Move ID': int(payment_move_id) if payment_move_id else None,
            'Fecha Conciliación': pr_date,
            'Monto Aplicado': float(amount_applied),
            'Cliente': safe_m2o_name(inv.get('partner_id')),
        })

    df_payments = pd.DataFrame(pay_rows)

    # 5) Enriquecer con account.payment si existe move_id
    if not df_payments.empty and 'Pago Move ID' in df_payments.columns:
        pay_fields_meta = odoo.fields_get('account.payment')
        if 'move_id' in pay_fields_meta:
            payment_move_ids = df_payments['Pago Move ID'].dropna().astype(int).unique().tolist()
            if payment_move_ids:
                payments = odoo.search_read(
                    'account.payment',
                    domain=[('move_id', 'in', payment_move_ids), ('state', '=', 'posted')],
                    fields=['id', 'name', 'date', 'amount', 'ref', 'journal_id', 'move_id']
                )

                move_to_payment = {}
                for p in payments:
                    mv = p.get('move_id')
                    mv_id = mv[0] if isinstance(mv, (list, tuple)) and mv else None
                    if mv_id:
                        move_to_payment[int(mv_id)] = p

                df_payments['Pago ID'] = df_payments['Pago Move ID'].apply(
                    lambda x: int(move_to_payment.get(int(x), {}).get('id')) if pd.notna(x) and int(x) in move_to_payment else None
                )
                df_payments['Pago'] = df_payments['Pago Move ID'].apply(
                    lambda x: move_to_payment.get(int(x), {}).get('name', '') if pd.notna(x) and int(x) in move_to_payment else ''
                )
                df_payments['Fecha Pago'] = df_payments['Pago Move ID'].apply(
                    lambda x: move_to_payment.get(int(x), {}).get('date', '') if pd.notna(x) and int(x) in move_to_payment else ''
                )
                df_payments['Monto Pago'] = df_payments['Pago Move ID'].apply(
                    lambda x: safe_float(move_to_payment.get(int(x), {}).get('amount')) if pd.notna(x) and int(x) in move_to_payment else 0.0
                )
                df_payments['Diario'] = df_payments['Pago Move ID'].apply(
                    lambda x: safe_m2o_name(move_to_payment.get(int(x), {}).get('journal_id')) if pd.notna(x) and int(x) in move_to_payment else ''
                )
                df_payments['Referencia'] = df_payments['Pago Move ID'].apply(
                    lambda x: move_to_payment.get(int(x), {}).get('ref', '') if pd.notna(x) and int(x) in move_to_payment else ''
                )

    return df_payments, applied_by_invoice


def build_productos_cl_table(odoo, template_ids, producto_prefix, codigo_cl_exacto=None):
    products = odoo.search_read(
        'product.product',
        domain=[('product_tmpl_id', 'in', template_ids)],
        fields=[
            'id', 'default_code', 'name', 'product_tmpl_id',
            'list_price',
            'x_studio_lote', 'x_studio_destino', 'x_studio_transporte',
            'x_studio_estado_viaje', 'x_studio_tipo_de_cupo',
            'x_studio_ida_fecha_salida', 'x_studio_boletos_totales',
            'x_studio_boletos_reservados', 'x_product_count_pagados_stat_inf',
            'x_studio_boletos_disponibles'
        ]
    )

    if codigo_cl_exacto:
        products = [p for p in products if str(p.get('default_code') or '') == str(codigo_cl_exacto)]

    if not products:
        return pd.DataFrame()

    df = pd.DataFrame(products)

    zeros = pd.Series([0] * len(df))

    df['Plazas Totales'] = (df['x_studio_boletos_totales'] if 'x_studio_boletos_totales' in df.columns else zeros).apply(lambda x: safe_float(x, 0.0))
    df['Plazas Reservadas'] = (df['x_studio_boletos_reservados'] if 'x_studio_boletos_reservados' in df.columns else zeros).apply(lambda x: safe_float(x, 0.0))
    df['Plazas Pagadas'] = (df['x_product_count_pagados_stat_inf'] if 'x_product_count_pagados_stat_inf' in df.columns else zeros).apply(lambda x: safe_float(x, 0.0))
    df['Plazas Disponibles'] = (df['x_studio_boletos_disponibles'] if 'x_studio_boletos_disponibles' in df.columns else zeros).apply(lambda x: safe_float(x, 0.0))

    df['Monto'] = (df['list_price'] if 'list_price' in df.columns else zeros).apply(lambda x: safe_float(x, 0.0))
    df['Total Pagado (CL)'] = df['Monto'] * df['Plazas Pagadas']

    # Estado de paquete (traducido) + tipo de cupo
    df['Estado de Paquete'] = df.get('x_studio_estado_viaje', '').apply(mapear_estado)
    df['Tipo de Cupo'] = df.get('x_studio_tipo_de_cupo', '').astype(str)

    # Formato fecha salida DD/MM/AAAA
    fecha_source = df['x_studio_ida_fecha_salida'] if 'x_studio_ida_fecha_salida' in df.columns else pd.Series([None] * len(df))
    fecha_dt = pd.to_datetime(fecha_source, errors='coerce')
    df['Fecha Salida (fmt)'] = fecha_dt.dt.strftime('%d/%m/%Y')

    df_out = df[[
        'default_code', 'name', 'Estado de Paquete', 'Tipo de Cupo', 'x_studio_destino', 'x_studio_lote', 'x_studio_transporte',
        'Fecha Salida (fmt)', 'Monto', 'Total Pagado (CL)',
        'Plazas Totales', 'Plazas Pagadas', 'Plazas Reservadas', 'Plazas Disponibles'
    ]].copy()

    df_out.columns = [
        'Código CL', 'Producto', 'Estado de Paquete', 'Tipo de Cupo', 'Destino', 'Lote', 'Transporte',
        'Fecha Salida', 'Monto', 'Total Pagado (CL)',
        'Plazas Totales', 'Plazas Pagadas', 'Plazas Reservadas', 'Plazas Disponibles'
    ]

    return df_out


def format_date_ddmmyyyy(series):
    dt = pd.to_datetime(series, errors='coerce')
    return dt.dt.strftime('%d/%m/%Y')


def format_datetime_ddmmyyyy(series):
    dt = pd.to_datetime(series, errors='coerce')
    return dt.dt.strftime('%d/%m/%Y')


def style_orders(df):
    def row_style(row):
        estado_fact = str(row.get('Estado Facturación Orden') or '').strip().lower()
        saldo = safe_float(row.get('Saldo Adeudado (posted)') or 0.0, 0.0)
        if saldo > 0:
            return ['background-color: #fff3cd'] * len(row)
        if estado_fact == 'nada que facturar':
            return ['background-color: #f8d7da'] * len(row)
        if estado_fact == 'por facturar':
            return ['background-color: #e7f1ff'] * len(row)
        return [''] * len(row)

    return df.style.apply(row_style, axis=1)


def style_productos_cl_descuadre(df):
    def row_style(row):
        diff = safe_float(row.get('Diferencia (CL - Facturado)') or 0.0, 0.0)
        if abs(diff) > 0.0001:
            return ['background-color: #f8d7da'] * len(row)
        return [''] * len(row)

    return df.style.apply(row_style, axis=1)


def style_payments(df):
    def row_style(row):
        estado = str(row.get('Estado Pago Factura') or '').strip().lower()
        if 'partial' in estado:
            return ['background-color: #fff3cd'] * len(row)
        return [''] * len(row)

    return df.style.apply(row_style, axis=1)


def mapear_estado(estado):
    if pd.isna(estado):
        return 'No definido'
    try:
        if isinstance(estado, (int, float)):
            return ESTADO_PAQUETE.get(int(estado), f'Estado {int(estado)}')
        if isinstance(estado, str) and estado.isdigit():
            return ESTADO_PAQUETE.get(int(estado), f'Estado {estado}')
        return str(estado)
    except Exception:
        return f'Estado {estado}' if pd.notna(estado) else 'No definido'


def build_orders_and_payments(odoo, template_ids, producto_prefix, codigo_cl_exacto=None):
    """Obtiene órdenes que contengan productos CL (por prefix) y construye tabla de órdenes + pagos."""

    # 1) Productos (variantes) para identificar los IDs vendidos
    products = odoo.search_read(
        'product.product',
        domain=[('product_tmpl_id', 'in', template_ids)],
        fields=['id', 'default_code', 'name', 'product_tmpl_id']
    )

    if codigo_cl_exacto:
        products = [p for p in products if str(p.get('default_code') or '') == str(codigo_cl_exacto)]

    product_ids = [p['id'] for p in products]
    products_dict = {p['id']: p for p in products}

    if not product_ids:
        return pd.DataFrame(), pd.DataFrame(), {
            'total_pagado': 0,
            'total_saldo': 0,
            'total_facturado_posted': 0,
        }

    # 2) Líneas de orden (acá se define la población: todas las órdenes que contienen esos productos)
    order_lines = odoo.search_read(
        'sale.order.line',
        domain=[('product_id', 'in', product_ids)],
        fields=['id', 'order_id', 'product_id', 'product_uom_qty', 'price_subtotal', 'name']
    )

    if not order_lines:
        return pd.DataFrame(), pd.DataFrame(), {
            'total_pagado': 0,
            'total_saldo': 0,
            'total_facturado_posted': 0,
        }

    order_ids = sorted({l['order_id'][0] for l in order_lines if l.get('order_id')})

    # 3) Órdenes
    order_fields = [
        'id', 'name', 'partner_id', 'date_order', 'amount_total',
        'invoice_status', 'user_id', 'team_id', 'state'
    ]

    # Si existe invoice_ids, lo traemos (para enlazar facturas)
    so_fields_meta = odoo.fields_get('sale.order')
    if 'invoice_ids' in so_fields_meta:
        order_fields.append('invoice_ids')

    orders = odoo.search_read(
        'sale.order',
        domain=[('id', 'in', order_ids)],
        fields=order_fields
    )
    orders_dict = {o['id']: o for o in orders}

    # 4) Facturas
    invoice_ids = []
    for o in orders:
        invs = o.get('invoice_ids') or []
        if invs:
            invoice_ids.extend(invs)

    invoice_ids = sorted(set(invoice_ids))

    inv_fields_meta = odoo.fields_get('account.move')
    inv_state_field = 'state' if 'state' in inv_fields_meta else None
    payment_state_field = get_first_existing_field(inv_fields_meta, ['payment_state', 'invoice_payment_state'])

    inv_fields = ['id', 'name', 'move_type', 'partner_id', 'invoice_origin', 'invoice_date', 'amount_total']
    if inv_state_field:
        inv_fields.append(inv_state_field)
    if payment_state_field:
        inv_fields.append(payment_state_field)
    if 'amount_residual' in inv_fields_meta:
        inv_fields.append('amount_residual')
    if 'amount_total_signed' in inv_fields_meta:
        inv_fields.append('amount_total_signed')
    if 'currency_id' in inv_fields_meta:
        inv_fields.append('currency_id')

    invoices = []
    if invoice_ids:
        invoice_domain = [('id', 'in', invoice_ids), ('move_type', 'in', ['out_invoice', 'out_refund', 'out_receipt'])]
        if inv_state_field:
            invoice_domain.append((inv_state_field, '=', 'posted'))

        invoices = odoo.search_read(
            'account.move',
            domain=invoice_domain,
            fields=inv_fields
        )

    invoices_dict = {inv['id']: inv for inv in invoices}

    # 5) Tabla de Órdenes (1 fila por orden) + agregados de facturas (posted)
    lines_by_order = {}
    for l in order_lines:
        if not l.get('order_id'):
            continue
        oid = l['order_id'][0]
        lines_by_order.setdefault(oid, []).append(l)

    order_rows = []
    cl_line_rows = []
    for order_id, lines in lines_by_order.items():
        o = orders_dict.get(order_id)
        if not o:
            continue

        # Agregación de líneas CL
        productos = []
        codigos = []
        cantidad_total = 0.0
        subtotal_total = 0.0
        for l in lines:
            pid = l['product_id'][0] if l.get('product_id') else None
            p = products_dict.get(pid, {}) if pid else {}
            codigo = ''
            if p:
                codigo = p.get('default_code', '')
            if p:
                productos.append(p.get('name', ''))
                codigos.append(codigo)
            cantidad_total += float(l.get('product_uom_qty') or 0)
            line_subtotal = float(l.get('price_subtotal') or 0)
            subtotal_total += line_subtotal

            if codigo:
                cl_line_rows.append({
                    'Orden': o.get('name', ''),
                    'Código CL': codigo,
                    'Subtotal Línea (CL)': line_subtotal,
                })

        productos = sorted({x for x in productos if x})
        codigos = sorted({x for x in codigos if x})

        order_invoice_ids = o.get('invoice_ids') or []
        order_invoices = [invoices_dict[iid] for iid in order_invoice_ids if iid in invoices_dict]

        total_facturado_posted = float(sum(float(inv.get('amount_total') or 0) for inv in order_invoices))
        total_residual_posted = float(sum(float(inv.get('amount_residual') or 0) for inv in order_invoices))
        total_pagado_posted = float(total_facturado_posted - total_residual_posted)

        payment_states = []
        if payment_state_field:
            payment_states = sorted({str(inv.get(payment_state_field)) for inv in order_invoices if inv.get(payment_state_field) is not None})

        order_rows.append({
            'Orden': o.get('name', ''),
            'Estado de Orden': o.get('state', ''),
            'Cliente': safe_m2o_name(o.get('partner_id')),
            'Fecha Orden': o.get('date_order', ''),
            'Agencia': safe_m2o_name(o.get('team_id')),
            'Vendedor': safe_m2o_name(o.get('user_id')),
            'Estado Facturación Orden': INVOICE_STATUS.get(o.get('invoice_status'), o.get('invoice_status')),
            'Códigos CL': ', '.join(codigos),
            'Productos CL': ', '.join(productos),
            'Cantidad Total (CL)': int(round(cantidad_total)),
            'Subtotal Total (CL)': subtotal_total,
            'Facturas (IDs)': ','.join(str(x) for x in order_invoice_ids) if order_invoice_ids else '',
            'Facturado (posted)': total_facturado_posted,
            'Pagado (posted)': total_pagado_posted,
            'Saldo Adeudado (posted)': total_residual_posted,
            'Estado Pago Factura (posted)': ', '.join(payment_states) if payment_states else ''
        })

    df_orders = pd.DataFrame(order_rows)

    # 5.b) Facturado (posted) asignado por Código CL (distribución proporcional por subtotal de líneas CL)
    df_facturado_por_cl = pd.DataFrame(columns=['Código CL', 'Facturado (posted)'])
    if cl_line_rows and not df_orders.empty:
        df_cl_lines = pd.DataFrame(cl_line_rows)
        df_ord_fact = df_orders[['Orden', 'Facturado (posted)']].copy()
        df_ord_fact['Facturado (posted)'] = df_ord_fact['Facturado (posted)'].apply(lambda x: safe_float(x, 0.0))

        df_cl_lines['Subtotal Línea (CL)'] = df_cl_lines['Subtotal Línea (CL)'].apply(lambda x: safe_float(x, 0.0))
        df_cl_tot = (
            df_cl_lines.groupby('Orden', as_index=False)
            .agg({'Subtotal Línea (CL)': 'sum'})
            .rename(columns={'Subtotal Línea (CL)': 'Subtotal Orden (CL)'})
        )
        df_cl_tot = df_cl_tot.merge(df_ord_fact, on='Orden', how='left')

        df_cl_lines = df_cl_lines.merge(df_cl_tot[['Orden', 'Subtotal Orden (CL)', 'Facturado (posted)']], on='Orden', how='left')
        df_cl_lines['Subtotal Orden (CL)'] = df_cl_lines['Subtotal Orden (CL)'].apply(lambda x: safe_float(x, 0.0))
        df_cl_lines['Facturado (posted)'] = df_cl_lines['Facturado (posted)'].apply(lambda x: safe_float(x, 0.0))

        def asignar_facturado(row):
            denom = safe_float(row.get('Subtotal Orden (CL)') or 0.0, 0.0)
            if denom <= 0:
                return 0.0
            return safe_float(row.get('Facturado (posted)') or 0.0, 0.0) * (safe_float(row.get('Subtotal Línea (CL)') or 0.0, 0.0) / denom)

        df_cl_lines['Facturado (posted) asignado'] = df_cl_lines.apply(asignar_facturado, axis=1)
        df_facturado_por_cl = df_cl_lines.groupby('Código CL', as_index=False)['Facturado (posted) asignado'].sum().rename(
            columns={'Facturado (posted) asignado': 'Facturado (posted)'}
        )

    # 6) Tabla de pagos (por conciliación): soporta pagos parciales y pagos repartidos
    df_payments, applied_by_invoice = extract_payment_applications_via_reconcile(
        odoo,
        invoice_ids=invoice_ids,
        invoices_dict=invoices_dict,
        inv_state_field=inv_state_field,
        payment_state_field=payment_state_field,
    )

    # Fallback (si no hay conciliaciones disponibles) a la vía estándar (menos precisa)
    if df_payments.empty:
        pay_fields_meta = odoo.fields_get('account.payment')
        if invoice_ids and 'reconciled_invoice_ids' in pay_fields_meta:
            pay_fields = ['id', 'name', 'date', 'amount', 'payment_type', 'partner_id', 'ref', 'journal_id', 'reconciled_invoice_ids', 'state']
            payments = odoo.search_read(
                'account.payment',
                domain=[('reconciled_invoice_ids', 'in', invoice_ids), ('state', '=', 'posted')],
                fields=pay_fields
            )

            pay_rows = []
            for p in payments:
                for inv_id in p.get('reconciled_invoice_ids') or []:
                    if inv_id not in invoices_dict:
                        continue
                    inv = invoices_dict[inv_id]
                    if inv_state_field and inv.get(inv_state_field) != 'posted':
                        continue
                    pay_rows.append({
                        'Pago ID': int(p.get('id')),
                        'Pago': p.get('name', ''),
                        'Fecha Pago': p.get('date', ''),
                        'Cliente': safe_m2o_name(p.get('partner_id')),
                        'Diario': safe_m2o_name(p.get('journal_id')),
                        'Monto Pago': float(p.get('amount') or 0),
                        'Referencia': p.get('ref', ''),
                        'Factura ID': int(inv.get('id')),
                        'Factura': inv.get('name', ''),
                        'Factura Origen': inv.get('invoice_origin', ''),
                        'Estado Pago Factura': inv.get(payment_state_field, '') if payment_state_field else '',
                        'Monto Aplicado': float(p.get('amount') or 0),
                    })
            df_payments = pd.DataFrame(pay_rows)

    total_pagos_unicos = 0.0
    if not df_payments.empty and 'Pago ID' in df_payments.columns:
        total_pagos_unicos = float(df_payments.drop_duplicates(subset=['Pago ID'])['Monto Pago'].sum())

    total_aplicado = float(df_payments['Monto Aplicado'].sum()) if (not df_payments.empty and 'Monto Aplicado' in df_payments.columns) else 0.0
    total_pagado_facturas = float(df_orders['Pagado (posted)'].sum()) if not df_orders.empty else 0.0
    gap_aplicado_vs_factura = float(total_aplicado - total_pagado_facturas)

    total_plazas = float(df_orders['Cantidad Total (CL)'].sum()) if (not df_orders.empty and 'Cantidad Total (CL)' in df_orders.columns) else 0.0

    totals = {
        'total_pagado': float(df_orders['Pagado (posted)'].sum()) if not df_orders.empty else 0,
        'total_saldo': float(df_orders['Saldo Adeudado (posted)'].sum()) if not df_orders.empty else 0,
        'total_facturado_posted': float(df_orders['Facturado (posted)'].sum()) if not df_orders.empty else 0,
        'total_pagos_detalle': float(df_payments['Monto Pago'].sum()) if not df_payments.empty else 0,
        'total_pagos_unicos': total_pagos_unicos,
        'total_aplicado': total_aplicado,
        'gap_aplicado_vs_pagado_factura': gap_aplicado_vs_factura,
        'total_plazas': total_plazas,
    }

    return df_orders, df_payments, totals, df_facturado_por_cl


# Título de la página
st.title("Cuadratura de Pagos Conciliados")

# Estado de sesión (evitar consultas pesadas en cada rerun)
if 'cuadratura_last_signature' not in st.session_state:
    st.session_state.cuadratura_last_signature = None
if 'cuadratura_result' not in st.session_state:
    st.session_state.cuadratura_result = None

try:
    client = OdooClient()

    # Obtener todos los paquetes (product.template) para replicar filtros de ocupación
    templates = client.search_read(
        'product.template',
        domain=[],
        fields=[
            'id', 'name', 'default_code', 'x_studio_lote', 'x_studio_destino',
            'x_studio_ida_fecha_salida', 'x_studio_tipo_de_cupo', 'x_studio_estado_viaje'
        ]
    )

    df_templates = pd.DataFrame(templates)
    if df_templates.empty:
        st.warning("No se encontraron paquetes en Odoo")
        st.stop()

    df_templates['Estado de Paquete Codigo'] = df_templates['x_studio_estado_viaje']
    df_templates['Estado de Paquete'] = df_templates['Estado de Paquete Codigo'].apply(mapear_estado)

    st.subheader("Filtros")
    filtros_container = st.container()

    with filtros_container:
        col1, col2 = st.columns(2)

        with col1:
            opciones_estados = sorted(df_templates['Estado de Paquete'].dropna().unique().tolist())
            default_estados = [e for e in ['Activo', 'Validación'] if e in opciones_estados]

            estados_seleccionados = st.multiselect(
                "Estado de Paquete",
                options=opciones_estados,
                default=default_estados
            )

            tipos_cupo_unicos = sorted(df_templates['x_studio_tipo_de_cupo'].dropna().astype(str).unique())
            tipos_cupo_seleccionados = st.multiselect(
                "Tipo de Cupo",
                options=tipos_cupo_unicos,
                default=[]
            )

            codigo_cl_filtro = st.text_input(
                "Filtrar por Código CL (opcional)",
                value="",
                help="Ej: CL1234. Si lo dejas vacío, se consideran todos los códigos que empiezan con CL."
            ).strip()

        with col2:
            lotes_unicos = sorted(df_templates['x_studio_lote'].dropna().unique())
            lote_seleccionado = st.selectbox(
                "Lote",
                options=["Todos"] + list(lotes_unicos),
                index=0
            )

            destinos_unicos = sorted(df_templates['x_studio_destino'].dropna().unique())
            destinos_seleccionados = st.multiselect(
                "Destinos",
                options=destinos_unicos,
                default=[]
            )

            fechas_salida = pd.to_datetime(df_templates['x_studio_ida_fecha_salida'], errors='coerce')
            meses_anio = []
            for fecha in fechas_salida.dropna():
                mes_anio = fecha.strftime('%B %Y')
                if mes_anio not in meses_anio:
                    meses_anio.append(mes_anio)
            meses_anio_ordenados = sorted(
                meses_anio,
                key=lambda x: pd.to_datetime(x, format='%B %Y', errors='coerce'),
                reverse=True
            )

            meses_anio_seleccionados = st.multiselect(
                "Mes-Año de Salida",
                options=meses_anio_ordenados,
                default=[]
            )

    # Botones (solo cuando se presiona Buscar se ejecutan queries pesadas)
    col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
    with col_btn1:
        limpiar_button = st.button("Limpiar")
    with col_btn3:
        buscar_button = st.button("Buscar", type="primary")

    if limpiar_button:
        st.session_state.cuadratura_last_signature = None
        st.session_state.cuadratura_result = None
        st.rerun()

    # Aplicar filtros a templates
    df_templates_filtrado = df_templates.copy()

    if estados_seleccionados:
        df_templates_filtrado = df_templates_filtrado[df_templates_filtrado['Estado de Paquete'].isin(estados_seleccionados)]

    if tipos_cupo_seleccionados:
        df_templates_filtrado = df_templates_filtrado[df_templates_filtrado['x_studio_tipo_de_cupo'].isin(tipos_cupo_seleccionados)]

    if lote_seleccionado != "Todos":
        df_templates_filtrado = df_templates_filtrado[df_templates_filtrado['x_studio_lote'] == lote_seleccionado]

    if destinos_seleccionados:
        df_templates_filtrado = df_templates_filtrado[df_templates_filtrado['x_studio_destino'].isin(destinos_seleccionados)]

    if meses_anio_seleccionados:
        temp = df_templates_filtrado.copy()
        temp['fecha_temp'] = pd.to_datetime(temp['x_studio_ida_fecha_salida'], errors='coerce')
        temp['mes_anio'] = temp['fecha_temp'].apply(lambda x: x.strftime('%B %Y') if pd.notna(x) else '')
        df_templates_filtrado = temp[temp['mes_anio'].isin(meses_anio_seleccionados)].drop(['fecha_temp', 'mes_anio'], axis=1)

    template_ids = df_templates_filtrado['id'].dropna().astype(int).unique().tolist()

    if not template_ids:
        st.warning("No se encontraron productos con los filtros seleccionados")
        st.stop()

    producto_prefix = None
    codigo_cl_exacto = codigo_cl_filtro if codigo_cl_filtro else None

    # Firma de filtros para cachear resultados
    filtro_signature = (
        tuple(sorted(estados_seleccionados)) if estados_seleccionados else tuple(),
        tuple(sorted(tipos_cupo_seleccionados)) if tipos_cupo_seleccionados else tuple(),
        str(lote_seleccionado),
        tuple(sorted(destinos_seleccionados)) if destinos_seleccionados else tuple(),
        tuple(sorted(meses_anio_seleccionados)) if meses_anio_seleccionados else tuple(),
        str(codigo_cl_exacto or ''),
        tuple(sorted(template_ids)),
    )

    if buscar_button:
        with st.spinner('Cargando órdenes, facturas y pagos...'):
            df_productos_cl = build_productos_cl_table(client, template_ids, producto_prefix, codigo_cl_exacto=codigo_cl_exacto)
            df_orders, df_payments, totals, df_facturado_por_cl = build_orders_and_payments(client, template_ids, producto_prefix, codigo_cl_exacto=codigo_cl_exacto)

        st.session_state.cuadratura_last_signature = filtro_signature
        st.session_state.cuadratura_result = {
            'df_productos_cl': df_productos_cl,
            'df_orders': df_orders,
            'df_payments': df_payments,
            'totals': totals,
            'df_facturado_por_cl': df_facturado_por_cl,
        }

    # Si no se ha presionado buscar (o cambió el filtro), no consultar
    if st.session_state.cuadratura_result is None:
        st.info('Configura los filtros y presiona "Buscar" para ejecutar la consulta.')
        st.stop()

    if st.session_state.cuadratura_last_signature != filtro_signature:
        st.warning('Los filtros cambiaron. Presiona "Buscar" para actualizar los resultados.')
        st.stop()

    df_productos_cl = st.session_state.cuadratura_result['df_productos_cl']
    df_orders = st.session_state.cuadratura_result['df_orders']
    df_payments = st.session_state.cuadratura_result['df_payments']
    totals = st.session_state.cuadratura_result['totals']
    df_facturado_por_cl = st.session_state.cuadratura_result.get('df_facturado_por_cl')

    total_productos_cl = int(len(df_productos_cl)) if df_productos_cl is not None and not df_productos_cl.empty else 0
    total_pagado_desde_cl = float(df_productos_cl['Total Pagado (CL)'].sum()) if df_productos_cl is not None and not df_productos_cl.empty else 0.0

    plazas_pagadas = float(df_productos_cl['Plazas Pagadas'].sum()) if df_productos_cl is not None and not df_productos_cl.empty else 0.0

    # Clasificación de órdenes según facturas posted (por saldo)
    df_orders_kpi = df_orders.copy() if df_orders is not None and not df_orders.empty else pd.DataFrame()
    if not df_orders_kpi.empty:
        df_orders_kpi['Estado de Orden'] = df_orders_kpi.get('Estado de Orden', '').astype(str)
        df_orders_kpi['Facturado (posted)'] = df_orders_kpi.get('Facturado (posted)', 0).apply(lambda x: safe_float(x, 0.0))
        df_orders_kpi['Pagado (posted)'] = df_orders_kpi.get('Pagado (posted)', 0).apply(lambda x: safe_float(x, 0.0))
        df_orders_kpi['Saldo Adeudado (posted)'] = df_orders_kpi.get('Saldo Adeudado (posted)', 0).apply(lambda x: safe_float(x, 0.0))
        df_orders_kpi['Subtotal Total (CL)'] = df_orders_kpi.get('Subtotal Total (CL)', 0).apply(lambda x: safe_float(x, 0.0))

        active_mask = ~df_orders_kpi['Estado de Orden'].isin(['cancel'])
        paid_orders_mask = active_mask & (df_orders_kpi['Facturado (posted)'] > 0) & (df_orders_kpi['Saldo Adeudado (posted)'] <= 0)
        partial_orders_mask = active_mask & (df_orders_kpi['Facturado (posted)'] > 0) & (df_orders_kpi['Saldo Adeudado (posted)'] > 0)
    else:
        paid_orders_mask = pd.Series([], dtype=bool)
        partial_orders_mask = pd.Series([], dtype=bool)

    cnt_ordenes_pagadas = int(paid_orders_mask.sum()) if not df_orders_kpi.empty else 0
    cnt_ordenes_parciales = int(partial_orders_mask.sum()) if not df_orders_kpi.empty else 0

    # Row 2 (nominal): CL vs Órdenes (Facturado Total desde facturas posted)
    monto_facturado_ordenes = float(df_orders_kpi['Facturado (posted)'].sum()) if not df_orders_kpi.empty else 0.0
    monto_diferencia_nominal = float(total_pagado_desde_cl - monto_facturado_ordenes)

    # Row 3 (facturas): Lo Facturado / Lo Pagado / Lo Adeudado (facturas posted)
    monto_facturado_posted = float(df_orders_kpi['Facturado (posted)'].sum()) if not df_orders_kpi.empty else 0.0
    monto_pagado_posted = float(df_orders_kpi['Pagado (posted)'].sum()) if not df_orders_kpi.empty else 0.0
    monto_adeudado_posted = float(df_orders_kpi['Saldo Adeudado (posted)'].sum()) if not df_orders_kpi.empty else 0.0

    # Row 4 (pagos conciliados): separar por estado de pago de factura
    df_pay_kpi = df_payments.copy() if df_payments is not None and not df_payments.empty else pd.DataFrame()
    total_pagos_conciliados = 0.0
    total_pagos_conciliados_parciales = 0.0
    if not df_pay_kpi.empty and 'Monto Aplicado' in df_pay_kpi.columns:
        df_pay_kpi['Monto Aplicado'] = df_pay_kpi['Monto Aplicado'].apply(lambda x: safe_float(x, 0.0))
        estado_pago = df_pay_kpi.get('Estado Pago Factura', '').astype(str).str.lower()
        paid_inv_mask = estado_pago.isin(['paid'])
        partial_inv_mask = estado_pago.isin(['partial'])
        total_pagos_conciliados = float(df_pay_kpi.loc[paid_inv_mask, 'Monto Aplicado'].sum())
        total_pagos_conciliados_parciales = float(df_pay_kpi.loc[partial_inv_mask, 'Monto Aplicado'].sum())

    total_pagos_conciliados_sum = float(total_pagos_conciliados + total_pagos_conciliados_parciales)

    st.subheader('Resumen General')

    st.write('### Conteos Generales')
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric('Cantidad de Productos CL', f"{int(total_productos_cl):,}".replace(',', '.'))
    with col2:
        st.metric('Cantidad de Plazas Pagadas', f"{int(plazas_pagadas):,}".replace(',', '.'))
    with col3:
        st.metric('Cantidad de Órdenes Pagadas', f"{int(cnt_ordenes_pagadas):,}".replace(',', '.'))
    with col4:
        st.metric('Cantidad Órdenes con pagos parciales', f"{int(cnt_ordenes_parciales):,}".replace(',', '.'))

    st.caption(
        "Origen: Productos viene de product.product (por los templates filtrados). Si especificas Código, se filtra por código exacto. "
        "Plazas pagadas viene de x_product_count_pagados_stat_inf. "
        "Órdenes pagadas/parciales se infiere desde facturas posted: saldo (amount_residual) == 0 vs > 0, excluyendo órdenes canceladas (state=cancel)."
    )

    st.write('### Cuadratura de Montos Nominales')
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric('Monto Total pagado desde CL', format_currency(total_pagado_desde_cl))
    with col2:
        st.metric('Monto pagado desde Órdenes (Facturado Total)', format_currency(monto_facturado_ordenes))
    with col3:
        diff_color = '#dc3545' if abs(monto_diferencia_nominal) > 0.0001 else '#198754'
        st.markdown(
            f"""
            <div style=\"padding: 0.25rem 0;\">
              <div style=\"font-size:0.9rem; color: rgba(49, 51, 63, 0.6);\">Monto Diferencia (CL - Órdenes)</div>
              <div style=\"font-size:1.6rem; font-weight:700; color:{diff_color};\">{format_currency(monto_diferencia_nominal)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.caption(
        "Objetivo: comparar el valor nominal pagado desde el CL (list_price * plazas pagadas) "
        "contra lo facturado real en facturas posted asociadas a las órdenes (sum Facturado (posted)). "
        "La diferencia ayuda a detectar descuadres por precios, descuentos, o registros inconsistentes."
    )

    st.write('### Cuadratura de Montos de Facturas Pagadas')
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric('Lo Facturado (facturas posted)', format_currency(monto_facturado_posted))
    with col2:
        st.metric('Lo Pagado (facturas posted = total - residual)', format_currency(monto_pagado_posted))
    with col3:
        adeudado_color = '#dc3545' if monto_adeudado_posted > 0.0001 else '#198754'
        st.markdown(
            f"""
            <div style=\"padding: 0.25rem 0;\">
              <div style=\"font-size:0.9rem; color: rgba(49, 51, 63, 0.6);\">Lo adeudado (Saldo facturas parciales)</div>
              <div style=\"font-size:1.6rem; font-weight:700; color:{adeudado_color};\">{format_currency(monto_adeudado_posted)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.caption(
        "Origen: montos calculados desde account.move (facturas) en estado posted ligadas a cada orden. "
        "Facturado = sum(amount_total). Pagado = sum(amount_total - amount_residual). Adeudado = sum(amount_residual)."
    )

    st.write('### Cuadratura de Pagos vs Facturas')
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric('Monto total de pagos conciliados (Pagadas + Parciales)', format_currency(total_pagos_conciliados_sum))
    with col2:
        st.metric('Monto pagos facturas pagadas (paid)', format_currency(total_pagos_conciliados))
    with col3:
        st.metric('Monto pagos facturas parciales (partial)', format_currency(total_pagos_conciliados_parciales))

    st.caption(
        "Origen: pagos conciliados desde account.partial.reconcile (Monto Aplicado). "
        "Se separa según Estado Pago Factura (paid vs partial) reportado por la factura posted. "
        "Esto permite comparar el mundo contable (conciliación) vs el estado/valores de la factura."
    )

    st.markdown('---')

    st.markdown('---')

    st.subheader('Productos CL (detalle)')
    col1, col2 = st.columns([3, 1])
    with col2:
        if df_productos_cl is not None and not df_productos_cl.empty:
            df_productos_xlsx = df_productos_cl.copy()
            if df_facturado_por_cl is not None and not df_facturado_por_cl.empty:
                df_fact = df_facturado_por_cl.copy()
                df_fact['Facturado (posted)'] = df_fact['Facturado (posted)'].apply(lambda x: safe_float(x, 0.0))
                df_productos_xlsx['Total Pagado (CL)'] = df_productos_xlsx['Total Pagado (CL)'].apply(lambda x: safe_float(x, 0.0))
                df_productos_xlsx = df_productos_xlsx.merge(df_fact, how='left', on='Código CL')
                df_productos_xlsx['Facturado (posted)'] = df_productos_xlsx['Facturado (posted)'].fillna(0).apply(lambda x: safe_float(x, 0.0))
                df_productos_xlsx['Diferencia (CL - Facturado)'] = df_productos_xlsx['Total Pagado (CL)'] - df_productos_xlsx['Facturado (posted)']

            export_dataframe_to_excel(df_productos_xlsx, 'cuadratura_productos_cl.xlsx', styler=style_productos_cl_descuadre(df_productos_xlsx))

    if df_productos_cl is None or df_productos_cl.empty:
        st.warning('No se encontraron Productos CL con los filtros seleccionados')
    else:
        df_productos_view = df_productos_cl.copy()
        if df_facturado_por_cl is not None and not df_facturado_por_cl.empty:
            df_fact = df_facturado_por_cl.copy()
            df_fact['Facturado (posted)'] = df_fact['Facturado (posted)'].apply(lambda x: safe_float(x, 0.0))
            df_productos_view['Total Pagado (CL)'] = df_productos_view['Total Pagado (CL)'].apply(lambda x: safe_float(x, 0.0))
            df_productos_view = df_productos_view.merge(df_fact, how='left', on='Código CL')
            df_productos_view['Facturado (posted)'] = df_productos_view['Facturado (posted)'].fillna(0).apply(lambda x: safe_float(x, 0.0))
            df_productos_view['Diferencia (CL - Facturado)'] = df_productos_view['Total Pagado (CL)'] - df_productos_view['Facturado (posted)']

        if 'Diferencia (CL - Facturado)' in df_productos_view.columns:
            st.markdown(
                """
                <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap;">
                  <div><span style="display:inline-block;width:14px;height:14px;background:#f8d7da;border:1px solid #ccc;margin-right:6px;"></span>CL con descuadre (Total Pagado CL != Facturado posted asignado)</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        resumen_productos = pd.DataFrame([
            {
                'Productos CL': int(len(df_productos_cl)),
                'Total pagado desde CL': float(df_productos_cl['Total Pagado (CL)'].sum()),
                'Plazas Totales': float(df_productos_cl['Plazas Totales'].sum()),
                'Plazas Pagadas': float(df_productos_cl['Plazas Pagadas'].sum()),
                'Plazas Reservadas': float(df_productos_cl['Plazas Reservadas'].sum()),
                'Plazas Disponibles': float(df_productos_cl['Plazas Disponibles'].sum()),
            }
        ])
        st.dataframe(resumen_productos.style.format({
            'Total pagado desde CL': lambda x: format_currency(x),
            'Plazas Totales': lambda x: f"{int(x):,}".replace(',', '.'),
            'Plazas Pagadas': lambda x: f"{int(x):,}".replace(',', '.'),
            'Plazas Reservadas': lambda x: f"{int(x):,}".replace(',', '.'),
            'Plazas Disponibles': lambda x: f"{int(x):,}".replace(',', '.'),
        }), hide_index=True, use_container_width=True)

        styler_prod = style_productos_cl_descuadre(df_productos_view) if 'Diferencia (CL - Facturado)' in df_productos_view.columns else df_productos_view.style
        st.dataframe(styler_prod.format({
            'Monto': lambda x: format_currency(x),
            'Total Pagado (CL)': lambda x: format_currency(x),
            'Facturado (posted)': lambda x: format_currency(x),
            'Diferencia (CL - Facturado)': lambda x: format_currency(x),
            'Plazas Totales': lambda x: f"{int(x):,}".replace(',', '.'),
            'Plazas Pagadas': lambda x: f"{int(x):,}".replace(',', '.'),
            'Plazas Reservadas': lambda x: f"{int(x):,}".replace(',', '.'),
            'Plazas Disponibles': lambda x: f"{int(x):,}".replace(',', '.'),
        }), hide_index=True, use_container_width=True)

    st.markdown('---')

    st.subheader('Órdenes (Productos CL)')
    col1, col2 = st.columns([3, 1])
    with col2:
        if not df_orders.empty:
            df_orders_xlsx = df_orders.copy()
            if 'Fecha Orden' in df_orders_xlsx.columns:
                df_orders_xlsx['Fecha Orden'] = format_datetime_ddmmyyyy(df_orders_xlsx['Fecha Orden'])
            export_dataframe_to_excel(df_orders_xlsx, 'cuadratura_ordenes_cl.xlsx', styler=style_orders(df_orders_xlsx))

    if not df_orders.empty:
        # Indicadores de estado de órdenes
        df_tmp = df_orders.copy()
        df_tmp['Estado de Orden'] = df_tmp.get('Estado de Orden', '').astype(str)
        df_tmp['Saldo Adeudado (posted)'] = df_tmp.get('Saldo Adeudado (posted)', 0).apply(lambda x: safe_float(x, 0.0))
        df_tmp['Facturado (posted)'] = df_tmp.get('Facturado (posted)', 0).apply(lambda x: safe_float(x, 0.0))

        ordenes_canceladas = int((df_tmp['Estado de Orden'].isin(['cancel'])).sum())
        ordenes_pagadas = int(((df_tmp['Saldo Adeudado (posted)'] <= 0) & (df_tmp['Facturado (posted)'] > 0) & (~df_tmp['Estado de Orden'].isin(['cancel']))).sum())
        ordenes_por_pagar = int(((df_tmp['Saldo Adeudado (posted)'] > 0) & (~df_tmp['Estado de Orden'].isin(['cancel']))).sum())

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric('Órdenes pagadas (por saldo factura)', f"{ordenes_pagadas:,}".replace(',', '.'))
        with col2:
            st.metric('Órdenes canceladas/anuladas (state=cancel)', f"{ordenes_canceladas:,}".replace(',', '.'))
        with col3:
            st.metric('Órdenes por pagar (saldo > 0)', f"{ordenes_por_pagar:,}".replace(',', '.'))

    if df_orders.empty:
        st.warning('No hay órdenes para mostrar con los filtros seleccionados')
    else:
        st.markdown(
            """
            <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap;">
              <div><span style="display:inline-block;width:14px;height:14px;background:#f8d7da;border:1px solid #ccc;margin-right:6px;"></span>Nada que facturar</div>
              <div><span style="display:inline-block;width:14px;height:14px;background:#e7f1ff;border:1px solid #ccc;margin-right:6px;"></span>Por facturar</div>
              <div><span style="display:inline-block;width:14px;height:14px;background:#fff3cd;border:1px solid #ccc;margin-right:6px;"></span>Saldo adeudado (facturas posted)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        df_orders_view = df_orders.copy()
        if 'Fecha Orden' in df_orders_view.columns:
            df_orders_view['Fecha Orden'] = format_datetime_ddmmyyyy(df_orders_view['Fecha Orden'])

        # Resumen de montos en tabla
        resumen_ordenes = pd.DataFrame([
            {
                'Facturado (posted)': float(df_orders['Facturado (posted)'].sum()),
                'Pagado (posted)': float(df_orders['Pagado (posted)'].sum()),
                'Saldo Adeudado (posted)': float(df_orders['Saldo Adeudado (posted)'].sum()),
                'Órdenes': int(len(df_orders))
            }
        ])
        st.dataframe(resumen_ordenes.style.format({
            'Facturado (posted)': lambda x: format_currency(x),
            'Pagado (posted)': lambda x: format_currency(x),
            'Saldo Adeudado (posted)': lambda x: format_currency(x)
        }), hide_index=True, use_container_width=True)

        st.dataframe(style_orders(df_orders_view).format({
            'Subtotal Total (CL)': lambda x: format_currency(x),
            'Facturado (posted)': lambda x: format_currency(x),
            'Pagado (posted)': lambda x: format_currency(x),
            'Saldo Adeudado (posted)': lambda x: format_currency(x)
        }), hide_index=True, use_container_width=True)

    st.markdown('---')

    st.subheader('Pagos (detalle por factura)')
    col1, col2 = st.columns([3, 1])
    with col2:
        if not df_payments.empty:
            df_payments_xlsx = df_payments.copy()
            if 'Factura Origen' in df_payments_xlsx.columns and 'Orden' in df_orders.columns:
                df_map = df_orders[['Orden', 'Códigos CL']].drop_duplicates().copy()
                df_payments_xlsx = df_payments_xlsx.merge(
                    df_map,
                    how='left',
                    left_on='Factura Origen',
                    right_on='Orden'
                )
                df_payments_xlsx = df_payments_xlsx.drop(columns=['Orden']).rename(columns={'Códigos CL': 'Código CL'})

            for c in ['Fecha Conciliación', 'Fecha Pago']:
                if c in df_payments_xlsx.columns:
                    df_payments_xlsx[c] = format_datetime_ddmmyyyy(df_payments_xlsx[c])

            export_dataframe_to_excel(df_payments_xlsx, 'cuadratura_pagos.xlsx', styler=style_payments(df_payments_xlsx))

    if df_payments.empty:
        st.info(
            "No se encontraron pagos conciliados para las facturas filtradas. "
            "Si esperabas pagos, revisa que existan conciliaciones en las líneas de cuentas (receivable/payable)."
        )
    else:
        st.markdown(
            """
            <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap;">
              <div><span style="display:inline-block;width:14px;height:14px;background:#fff3cd;border:1px solid #ccc;margin-right:6px;"></span>Factura con pago parcial (partial)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        df_payments_view = df_payments.copy()
        if 'Factura Origen' in df_payments_view.columns and 'Orden' in df_orders.columns:
            df_map = df_orders[['Orden', 'Códigos CL']].drop_duplicates().copy()
            df_payments_view = df_payments_view.merge(
                df_map,
                how='left',
                left_on='Factura Origen',
                right_on='Orden'
            )
            df_payments_view = df_payments_view.drop(columns=['Orden']).rename(columns={'Códigos CL': 'Código CL'})

        for c in ['Fecha Conciliación', 'Fecha Pago']:
            if c in df_payments_view.columns:
                df_payments_view[c] = format_datetime_ddmmyyyy(df_payments_view[c])

        resumen_pagos = pd.DataFrame([
            {
                'Monto Total Pagos (únicos)': float(df_payments.drop_duplicates(subset=['Pago ID'])['Monto Pago'].sum()) if 'Pago ID' in df_payments.columns else float(df_payments['Monto Pago'].sum()),
                'Monto Total Aplicado (detalle)': float(df_payments['Monto Aplicado'].sum()) if 'Monto Aplicado' in df_payments.columns else 0.0,
                'Monto Aplicado a Facturas Parciales': float(df_payments.loc[df_payments.get('Estado Pago Factura', '').astype(str).str.lower().isin(['partial']), 'Monto Aplicado'].sum()) if 'Monto Aplicado' in df_payments.columns else 0.0,
                'Cantidad de Pagos (filas)': int(len(df_payments))
            }
        ])

        st.caption(
            "Leyenda: 'Monto Total Pagos (únicos)' suma el MONTO TOTAL de cada pago (account.payment) una sola vez (deduplicado por Pago ID). "
            "'Monto Total Aplicado (detalle)' suma el MONTO EFECTIVAMENTE APLICADO a las facturas del reporte (conciliaciones account.partial.reconcile), por lo que puede ser menor si parte del pago quedó como anticipo/no aplicado o se aplicó a facturas fuera del filtro."
        )
        st.dataframe(resumen_pagos.style.format({
            'Monto Total Pagos (únicos)': lambda x: format_currency(x),
            'Monto Total Aplicado (detalle)': lambda x: format_currency(x),
            'Monto Aplicado a Facturas Parciales': lambda x: format_currency(x)
        }), hide_index=True, use_container_width=True)

        st.dataframe(style_payments(df_payments_view).format({
            'Monto Pago': lambda x: format_currency(x),
            'Monto Aplicado': lambda x: format_currency(x)
        }), hide_index=True, use_container_width=True)

except Exception as e:
    st.error(f"Error: {str(e)}")
    st.write("Detalles del error para debugging:", e)
