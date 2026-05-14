# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductCategory(models.Model):
    _inherit = 'product.category'

    poultry_cover_window_days = fields.Float(
        string='Días ventana consumo',
        default=7.0,
        digits=(16, 1),
        help='Cantidad de días hacia atrás para sumar salidas y dividir el total (promedio diario de consumo).',
    )

    @api.constrains('poultry_cover_window_days')
    def _check_poultry_cover_category_params(self):
        for categ in self:
            if categ.poultry_cover_window_days <= 0:
                raise ValidationError(
                    'En la categoría, los días de ventana de consumo deben ser mayores que cero.'
                )
