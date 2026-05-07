# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.tools.float_utils import float_compare, float_is_zero, float_round


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    poultry_cover_daily_avg = fields.Float(
        string='Consumo diario (7 días)',
        related='product_id.poultry_cover_daily_avg',
        readonly=True,
        digits='Product Unit of Measure',
    )
    poultry_cover_days = fields.Float(
        string='Días de cobertura',
        compute='_compute_poultry_cover_quant_metrics',
        digits=(16, 2),
    )
    poultry_cover_days_display = fields.Char(
        string='Días cobertura',
        compute='_compute_poultry_cover_quant_metrics',
    )
    poultry_cover_signal = fields.Selection(
        selection=[
            ('green', 'Verde'),
            ('yellow', 'Amarillo'),
            ('red', 'Rojo'),
            ('neutral', 'Sin datos'),
        ],
        string='Semáforo cobertura',
        compute='_compute_poultry_cover_quant_metrics',
    )

    @api.depends(
        'quantity',
        'product_id.poultry_cover_daily_avg',
        'product_id.product_tmpl_id.poultry_cover_green_days',
        'product_id.product_tmpl_id.poultry_cover_yellow_days',
    )
    def _compute_poultry_cover_quant_metrics(self):
        for quant in self:
            product = quant.product_id
            tmpl = product.product_tmpl_id
            rounding = product.uom_id.rounding or 0.0001

            daily = product.poultry_cover_daily_avg or 0.0
            qty = quant.quantity or 0.0

            if float_is_zero(daily, precision_rounding=rounding):
                quant.poultry_cover_days = False
                if float_is_zero(qty, precision_rounding=rounding):
                    quant.poultry_cover_days_display = '—'
                    quant.poultry_cover_signal = 'neutral'
                else:
                    quant.poultry_cover_days_display = '∞'
                    quant.poultry_cover_signal = 'green'
                continue

            days = qty / daily if daily else 0.0
            quant.poultry_cover_days = float_round(days, precision_rounding=0.01)
            quant.poultry_cover_days_display = str(float_round(days, precision_rounding=0.01))

            if float_compare(days, tmpl.poultry_cover_green_days, precision_digits=2) >= 0:
                quant.poultry_cover_signal = 'green'
            elif float_compare(days, tmpl.poultry_cover_yellow_days, precision_digits=2) >= 0:
                quant.poultry_cover_signal = 'yellow'
            else:
                quant.poultry_cover_signal = 'red'

