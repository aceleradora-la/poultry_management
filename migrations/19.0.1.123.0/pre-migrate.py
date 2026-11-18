# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Crea y completa por SQL el Cliente del pedido de las líneas de factura existentes,
    para que la actualización no lo recalcule línea por línea en Python. Toma el cliente
    (entidad comercial) del primer pedido de venta vinculado a cada línea de producto de
    las facturas, notas de crédito y recibos de cliente."""
    if not version:
        return
    cr.execute("""
        ALTER TABLE account_move_line
        ADD COLUMN IF NOT EXISTS poultry_order_partner_id integer
    """)
    # Una base sin Ventas instalado (se instala en esta misma actualización, por la
    # dependencia nueva) no tiene pedidos: la columna queda vacía y listo.
    cr.execute("SELECT to_regclass('sale_order_line_invoice_rel') IS NOT NULL")
    if not cr.fetchone()[0]:
        return
    cr.execute("""
        UPDATE account_move_line aml
           SET poultry_order_partner_id = src.partner_id
          FROM (
                SELECT DISTINCT ON (rel.invoice_line_id)
                       rel.invoice_line_id AS line_id,
                       partner.commercial_partner_id AS partner_id
                  FROM sale_order_line_invoice_rel rel
                  JOIN sale_order_line sol ON sol.id = rel.order_line_id
                  JOIN sale_order so ON so.id = sol.order_id
                  JOIN res_partner partner ON partner.id = so.partner_id
                 ORDER BY rel.invoice_line_id, so.id
               ) src,
               account_move move
         WHERE src.line_id = aml.id
           AND move.id = aml.move_id
           AND move.move_type IN ('out_invoice', 'out_refund', 'out_receipt')
           AND aml.display_type = 'product'
    """)
