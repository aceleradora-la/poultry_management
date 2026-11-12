# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.tools import SQL


class StockMove(models.Model):
    _inherit = 'stock.move'

    poultry_landed_line_ids = fields.One2many(
        'stock.valuation.adjustment.lines', 'move_id',
        string='Ajustes de costos en destino',
    )


class PurchaseOrderLine(models.Model):
    """Cantidad realmente comprada y costos en destino de cada línea de compra.

    - Cantidad efectiva: lo recibido más lo que sigue pendiente de recibir. Si una
      recepción se cerró sin dejar entrega pendiente (o se canceló), esa diferencia
      ya no cuenta. Los servicios no tienen recepción: cuentan por lo pedido. Los
      productos de costo en destino (Flete, Costo Adicional) cuentan cero, porque su
      importe ya está repartido sobre los productos recibidos.
    - Costos en destino: suma del Costo adicional de los ajustes de valuación validados.

    Se calcula con precio de la orden y Costo adicional, no con stock.move.value, para
    que una valuación errónea de un movimiento no distorsione el análisis de compras.
    """
    _inherit = 'purchase.order.line'

    poultry_qty_effective = fields.Float(
        string='Cantidad efectiva', digits='Product Unit',
        compute='_compute_poultry_purchase_cost', store=True,
        help='Recibido + pendiente de recibir, en la unidad de la línea.',
    )
    poultry_landed_cost = fields.Float(
        string='Costos en destino', digits=(16, 2),
        compute='_compute_poultry_purchase_cost', store=True,
        help='Costo adicional validado sobre las recepciones de esta línea, en moneda de la compañía.',
    )

    @api.depends(
        'product_qty', 'product_id.type', 'product_id.landed_cost_ok', 'qty_received',
        'move_ids.state', 'move_ids.product_uom_qty', 'move_ids.product_uom',
        'move_ids.poultry_landed_line_ids.additional_landed_cost',
        'move_ids.poultry_landed_line_ids.cost_id.state',
    )
    def _compute_poultry_purchase_cost(self):
        for line in self:
            moves = line.move_ids
            line.poultry_landed_cost = sum(
                adjustment.additional_landed_cost
                for adjustment in moves.poultry_landed_line_ids
                if adjustment.cost_id.state == 'done'
            )
            product = line.product_id
            if not product or product.landed_cost_ok:
                line.poultry_qty_effective = 0.0
            elif product.type == 'service':
                line.poultry_qty_effective = line.product_qty
            else:
                pending = sum(
                    move.product_uom._compute_quantity(move.product_uom_qty, line.product_uom_id)
                    for move in moves
                    if move.state not in ('done', 'cancel') and move.location_id.usage == 'supplier'
                )
                line.poultry_qty_effective = line.qty_received + pending


class PurchaseReport(models.Model):
    """Agrega al Análisis de compras el costo total: efectivo más costos en destino."""
    _inherit = 'purchase.report'

    qty_effective = fields.Float(string='Cantidad efectiva', readonly=True)
    amount_effective = fields.Monetary(string='Importe efectivo', readonly=True)
    landed_cost_total = fields.Monetary(string='Costos en destino', readonly=True)
    total_cost = fields.Monetary(string='Costo total', readonly=True)
    unit_cost = fields.Monetary(
        string='Costo unitario total', readonly=True, aggregator='avg',
        help='Costo total / Cantidad efectiva. Al agrupar es un promedio ponderado.',
    )

    _depends = {
        'purchase.order.line': ['poultry_qty_effective', 'poultry_landed_cost'],
    }

    def _select(self) -> SQL:
        amount = SQL(
            '''sum(
                    CASE WHEN l.product_qty <> 0
                         THEN l.price_subtotal * l.poultry_qty_effective / l.product_qty
                         ELSE 0 END
                    / COALESCE(po.currency_rate, 1.0)
                )::decimal(16,2) * account_currency_table.rate'''
        )
        landed = SQL('sum(l.poultry_landed_cost)::decimal(16,2) * account_currency_table.rate')
        qty = SQL('sum(l.poultry_qty_effective * line_uom.factor / product_uom.factor)')
        return SQL(
            '''%(base)s,
                %(qty)s AS qty_effective,
                %(amount)s AS amount_effective,
                %(landed)s AS landed_cost_total,
                %(amount)s + %(landed)s AS total_cost,
                COALESCE((%(amount)s + %(landed)s) / NULLIF(%(qty)s, 0.0), 0.0) AS unit_cost
            ''',
            base=super()._select(), qty=qty, amount=amount, landed=landed,
        )

    def _read_group_select(self, aggregate_spec: str, query) -> SQL:
        """Costo unitario ponderado al agrupar: SUM(costo total) / SUM(cantidad efectiva)."""
        if aggregate_spec != 'unit_cost:avg':
            return super()._read_group_select(aggregate_spec, query)
        return SQL(
            'COALESCE(SUM(%(f_cost)s) / NULLIF(SUM(%(f_qty)s), 0.0), 0)',
            f_cost=self._field_to_sql(self._table, 'total_cost', query),
            f_qty=self._field_to_sql(self._table, 'qty_effective', query),
        )
