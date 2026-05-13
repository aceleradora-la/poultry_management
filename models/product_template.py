# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # False = heredar de la categoría del producto (product.category).
    poultry_cover_window_days = fields.Float(
        string='Días ventana consumo',
        digits=(16, 1),
        help='Días hacia atrás para sumar salidas y dividir el total (consumo diario). '
             'Vacío: usar el valor de la categoría del producto.',
    )
    poultry_cover_green_days = fields.Float(
        string='Umbral verde (días de cobertura)',
        help='Semáforo verde cuando los días de cobertura son mayores o iguales a este valor. '
             'Vacío: usar el valor de la categoría del producto.',
    )
    poultry_cover_yellow_days = fields.Float(
        string='Umbral amarillo (días de cobertura)',
        help='Semáforo amarillo cuando los días están entre este valor (inclusive) y el umbral verde (excl.). '
             'Por debajo del amarillo: rojo. Vacío: usar la categoría.',
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

    @api.constrains(
        'poultry_cover_window_days',
        'poultry_cover_green_days',
        'poultry_cover_yellow_days',
        'categ_id',
    )
    def _check_poultry_cover_thresholds(self):
        for tmpl in self:
            if tmpl.poultry_cover_window_days is not False and tmpl.poultry_cover_window_days <= 0:
                raise ValidationError('Los días de ventana de consumo deben ser mayores que cero.')
            g = tmpl._poultry_effective_cover_green_days()
            y = tmpl._poultry_effective_cover_yellow_days()
            if g <= 0 or y <= 0:
                raise ValidationError('Los umbrales efectivos de cobertura deben ser positivos (revise producto y categoría).')
            if g <= y:
                raise ValidationError(
                    'El umbral verde efectivo debe ser mayor que el amarillo efectivo (combine producto y categoría).'
                )

    def _poultry_effective_cover_window_days(self):
        self.ensure_one()
        categ = self.categ_id
        w = self.poultry_cover_window_days if self.poultry_cover_window_days is not False else categ.poultry_cover_window_days
        w = float(w or 7.0)
        return max(w, 1.0)

    def _poultry_effective_cover_green_days(self):
        self.ensure_one()
        categ = self.categ_id
        v = self.poultry_cover_green_days if self.poultry_cover_green_days is not False else categ.poultry_cover_green_days
        return float(v or 14.0)

    def _poultry_effective_cover_yellow_days(self):
        self.ensure_one()
        categ = self.categ_id
        v = self.poultry_cover_yellow_days if self.poultry_cover_yellow_days is not False else categ.poultry_cover_yellow_days
        return float(v or 7.0)

