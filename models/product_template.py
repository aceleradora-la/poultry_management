# -*- coding: utf-8 -*-

from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

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

