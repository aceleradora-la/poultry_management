# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductCategory(models.Model):
    _inherit = 'product.category'

    poultry_cover_window_days = fields.Float(
        string='Días ventana consumo',
        default=7.0,
        digits=(16, 1),
        help='Días calendario cerrados (TZ de la compañía) para sumar salidas: desde el día (hoy−N) '
             '00:00 hasta ayer 23:59. No incluye el día en curso. El total se divide entre N.',
    )

    @api.constrains('poultry_cover_window_days')
    def _check_poultry_cover_category_params(self):
        for categ in self:
            if categ.poultry_cover_window_days <= 0:
                raise ValidationError(
                    'En la categoría, los días de ventana de consumo deben ser mayores que cero.'
                )
