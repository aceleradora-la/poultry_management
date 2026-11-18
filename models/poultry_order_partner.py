# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.tools import SQL


class AccountMoveLine(models.Model):
    """Cliente del pedido de venta del que viene cada línea de factura de cliente.

    Una factura puede salir a nombre de otra empresa (Dirección de factura), pero para
    analizar ventas por cliente interesa quién hizo el pedido. Las líneas que no vienen
    de un pedido quedan vacías; el Análisis de facturas usa entonces el cliente de la
    factura.
    """
    _inherit = 'account.move.line'

    poultry_order_partner_id = fields.Many2one(
        'res.partner', string='Cliente del pedido',
        compute='_compute_poultry_order_partner_id', store=True, index='btree_not_null',
        help='Entidad comercial del cliente del pedido de venta de origen.',
    )

    @api.depends('display_type', 'move_id.move_type',
                 'sale_line_ids.order_id.partner_id.commercial_partner_id')
    def _compute_poultry_order_partner_id(self):
        for line in self:
            if line.display_type == 'product' and line.move_id.move_type in (
                    'out_invoice', 'out_refund', 'out_receipt'):
                orders = line.sale_line_ids.order_id.sorted('id')
                line.poultry_order_partner_id = orders[:1].partner_id.commercial_partner_id
            else:
                line.poultry_order_partner_id = False


class AccountInvoiceReport(models.Model):
    """Análisis de facturas: Cliente del pedido (o el de la factura si no hay pedido)."""
    _inherit = 'account.invoice.report'

    order_partner_id = fields.Many2one('res.partner', string='Cliente del pedido', readonly=True)

    _depends = {
        'account.move.line': ['poultry_order_partner_id'],
    }

    @api.model
    def _select(self) -> SQL:
        return SQL(
            '''%s,
                COALESCE(line.poultry_order_partner_id, line.partner_id) AS order_partner_id
            ''',
            super()._select(),
        )
