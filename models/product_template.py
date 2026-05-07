# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    poultry_cover_green_days = fields.Float(
        string='Umbral verde (días de cobertura)',
        default=14.0,
        help='Semáforo verde cuando los días de cobertura son mayores o iguales a este valor.',
    )
    poultry_cover_yellow_days = fields.Float(
        string='Umbral amarillo (días de cobertura)',
        default=7.0,
        help='Semáforo amarillo cuando los días están entre este valor (inclusive) y el umbral verde (excl.). '
             'Por debajo del amarillo: rojo.',
    )

    is_egg_production = fields.Boolean(
        string='Usar en Producción de Huevos',
        default=False,
        help='Marque este campo si este producto se utiliza en el proceso de producción de huevos.'
    )

    poultry_validate_kit_consumption = fields.Boolean(
        string='Mix Producto Avicola',
        default=False,
        help=(
            'Si está activo, al finalizar una Orden de Fabricación se valida que la suma de las '
            'cantidades consumidas de sus componentes (convertidas a la UdM del producto final) '
            'sea igual a la cantidad producida.'
        ),
    )

    @api.constrains('poultry_cover_green_days', 'poultry_cover_yellow_days')
    def _check_poultry_cover_thresholds(self):
        for tmpl in self:
            if tmpl.poultry_cover_yellow_days < 0 or tmpl.poultry_cover_green_days < 0:
                raise ValidationError('Los umbrales de cobertura deben ser positivos.')
            if tmpl.poultry_cover_green_days <= tmpl.poultry_cover_yellow_days:
                raise ValidationError(
                    'El umbral verde debe ser mayor que el umbral amarillo (días de cobertura).'
                )

