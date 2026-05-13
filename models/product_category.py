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
    poultry_cover_green_days = fields.Float(
        string='Umbral verde (días cobertura)',
        default=14.0,
        digits=(16, 2),
        help='Semáforo verde si los días de cobertura son mayores o iguales a este valor.',
    )
    poultry_cover_yellow_days = fields.Float(
        string='Umbral amarillo (días cobertura)',
        default=7.0,
        digits=(16, 2),
        help='Semáforo amarillo entre este valor (incl.) y el verde (excl.). Por debajo: rojo.',
    )

    @api.constrains(
        'poultry_cover_window_days',
        'poultry_cover_green_days',
        'poultry_cover_yellow_days',
    )
    def _check_poultry_cover_category_params(self):
        for categ in self:
            if categ.poultry_cover_window_days <= 0:
                raise ValidationError('En la categoría, los días de ventana de consumo deben ser mayores que cero.')
            if categ.poultry_cover_green_days <= 0 or categ.poultry_cover_yellow_days <= 0:
                raise ValidationError('Los umbrales de cobertura en la categoría deben ser positivos.')
            if categ.poultry_cover_green_days <= categ.poultry_cover_yellow_days:
                raise ValidationError(
                    'En la categoría, el umbral verde debe ser mayor que el umbral amarillo.'
                )
