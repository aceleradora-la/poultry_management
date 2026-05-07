# -*- coding: utf-8 -*-
"""
Tablero de cobertura de stock: consumo medio diario (salidas últimos 7 días / 7) y semáforo por umbrales en plantilla.
"""
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools.float_utils import float_compare, float_is_zero, float_round


class ProductProduct(models.Model):
    _inherit = 'product.product'

    poultry_cover_daily_avg = fields.Float(
        string='Consumo diario (7 días)',
        digits='Product Unit of Measure',
        compute='_compute_poultry_cover_metrics',
        help='Promedio diario de salidas desde stock interno en los últimos 7 días (UdM del producto).',
    )
    poultry_cover_days = fields.Float(
        string='Días de cobertura',
        compute='_compute_poultry_cover_metrics',
        digits=(16, 2),
        help='Stock a la mano / consumo diario. Vacío si no hubo consumo en el período.',
    )
    poultry_cover_days_display = fields.Char(
        string='Días cobertura',
        compute='_compute_poultry_cover_metrics',
    )
    poultry_cover_signal = fields.Selection(
        selection=[
            ('green', 'Verde'),
            ('yellow', 'Amarillo'),
            ('red', 'Rojo'),
            ('neutral', 'Sin datos'),
        ],
        string='Semáforo cobertura',
        compute='_compute_poultry_cover_metrics',
    )

    def _poultry_sum_outgoing_product_uom(self, product_ids):
        """Salidas done en ventana móvil de 7 días: internal → no internal."""
        if not product_ids:
            return {}
        date_from = fields.Datetime.now() - timedelta(days=7)
        domain = [
            ('state', '=', 'done'),
            # En stock.move.line, `date` puede ser fecha de creación/actualización.
            # En stock.move, `date` es fecha programada y, al quedar done, pasa a ser la fecha real del movimiento.
            ('move_id.date', '>=', date_from),
            ('product_id', 'in', list(product_ids)),
            ('location_id.usage', '=', 'internal'),
            ('location_dest_id.usage', '!=', 'internal'),
        ]
        # Nota: este tablero es analítico. Para que el cálculo no dependa de reglas de registro
        # (que pueden ocultar movimientos) lo calculamos con sudo.
        MoveLine = self.env['stock.move.line'].sudo()
        groups = MoveLine.read_group(domain, ['quantity_product_uom:sum'], ['product_id'])
        result = {}
        for row in groups:
            p = row.get('product_id')
            if not p:
                continue
            pid = p[0] if isinstance(p, (list, tuple)) else p
            qty = None
            for key, val in row.items():
                if key == 'product_id' or key == '__domain':
                    continue
                if key.endswith('_sum'):
                    qty = val
                    break
            if qty is None:
                qty = row.get('quantity_product_uom') or 0.0
            result[pid] = qty or 0.0
        return result

    @api.depends(
        'qty_available',
        'uom_id',
        'product_tmpl_id.poultry_cover_green_days',
        'product_tmpl_id.poultry_cover_yellow_days',
    )
    def _compute_poultry_cover_metrics(self):
        consumption_map = self._poultry_sum_outgoing_product_uom(set(self.ids))
        for product in self:
            tmpl = product.product_tmpl_id
            rounding = product.uom_id.rounding or 0.0001
            green_th = tmpl.poultry_cover_green_days
            yellow_th = tmpl.poultry_cover_yellow_days
            total_out = consumption_map.get(product.id, 0.0)
            daily = total_out / 7.0
            product.poultry_cover_daily_avg = float_round(daily, precision_rounding=rounding)
            qty = product.qty_available

            if float_is_zero(daily, precision_rounding=rounding):
                product.poultry_cover_days = False
                if float_is_zero(qty, precision_rounding=rounding):
                    product.poultry_cover_days_display = '—'
                    product.poultry_cover_signal = 'neutral'
                else:
                    product.poultry_cover_days_display = '∞'
                    product.poultry_cover_signal = 'green'
                continue

            days = qty / daily if daily else 0.0
            product.poultry_cover_days = float_round(days, precision_rounding=0.01)
            product.poultry_cover_days_display = str(float_round(days, precision_rounding=0.01))

            if float_compare(days, green_th, precision_digits=2) >= 0:
                product.poultry_cover_signal = 'green'
            elif float_compare(days, yellow_th, precision_digits=2) >= 0:
                product.poultry_cover_signal = 'yellow'
            else:
                product.poultry_cover_signal = 'red'

    @api.model
    def action_open_poultry_stock_dashboard(self):
        """Dominio: almacenables + categorías opcionales por compañía (child_of)."""
        domain = [('is_storable', '=', True), ('active', '=', True)]
        cats = self.env.company.poultry_stock_dashboard_category_ids
        if cats:
            domain.append(('categ_id', 'child_of', cats.ids))
        kanban_view = self.env.ref('poultry_management.product_product_kanban_poultry_cover')
        list_view = self.env.ref('poultry_management.product_product_tree_poultry_cover')
        search_view = self.env.ref('poultry_management.product_product_search_poultry_cover')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cobertura de stock',
            'res_model': 'product.product',
            'view_mode': 'kanban,list',
            'views': [(kanban_view.id, 'kanban'), (list_view.id, 'list')],
            'search_view_id': search_view.id,
            'domain': domain,
            'context': {},
        }
