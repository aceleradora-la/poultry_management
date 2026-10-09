# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.tools import SQL


class PoultryAccountInvoiceReport(models.Model):
    """
    Extiende el Análisis de facturas (account.invoice.report) con las cantidades en
    Huevos y Cajones y el Precio por cajón.

    Las cantidades salen de los campos almacenados de account.move.line
    (quantity_huevos / quantity_cajones) y se les aplica la misma convención de signo
    que usa el análisis para `quantity`: negativo en facturas de proveedor, notas de
    crédito de cliente y recibos de compra.

    El Precio por cajón es un promedio PONDERADO: al agrupar, Odoo calcula
    SUM(importe sin impuestos) / SUM(cajones), igual que hace el análisis estándar con
    el Precio promedio. Por eso un pivote (o un tablero) que use esta medida con
    agregación "promedio" obtiene el precio correcto por mes, cliente, producto, etc.
    """
    _inherit = 'account.invoice.report'

    quantity_huevos = fields.Float(string='Huevos', readonly=True)
    quantity_cajones = fields.Float(string='Cajones', readonly=True)
    price_per_cajon = fields.Float(
        string='Precio por cajón',
        readonly=True,
        aggregator='avg',
        help='Importe sin impuestos / Cajones. Al agrupar es un promedio ponderado por cajones.',
    )

    _depends = {
        'account.move.line': ['quantity_huevos', 'quantity_cajones'],
    }

    @api.model
    def _select(self) -> SQL:
        return SQL(
            '''%s,
                ABS(COALESCE(line.quantity_huevos, 0.0))
                    * (CASE WHEN move.move_type IN ('in_invoice','out_refund','in_receipt') THEN -1 ELSE 1 END)
                                                                            AS quantity_huevos,
                ABS(COALESCE(line.quantity_cajones, 0.0))
                    * (CASE WHEN move.move_type IN ('in_invoice','out_refund','in_receipt') THEN -1 ELSE 1 END)
                                                                            AS quantity_cajones,
                COALESCE(
                    -line.balance * account_currency_table.rate
                    / NULLIF(
                        ABS(COALESCE(line.quantity_cajones, 0.0))
                        * (CASE WHEN move.move_type IN ('in_invoice','out_refund','in_receipt') THEN -1 ELSE 1 END),
                        0.0),
                    0.0)                                                    AS price_per_cajon
            ''',
            super()._select(),
        )

    def _read_group_select(self, aggregate_spec: str, query) -> SQL:
        """Precio por cajón ponderado al agrupar: SUM(importe) / SUM(cajones)."""
        if aggregate_spec != 'price_per_cajon:avg':
            return super()._read_group_select(aggregate_spec, query)
        return SQL(
            'COALESCE(SUM(%(f_price)s) / NULLIF(SUM(%(f_qty)s), 0.0), 0)',
            f_qty=self._field_to_sql(self._table, 'quantity_cajones', query),
            f_price=self._field_to_sql(self._table, 'price_subtotal', query),
        )
