# -*- coding: utf-8 -*-

from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_egg_production = fields.Boolean(
        string='Usar en Producción de Huevos',
        default=False,
        help='Marque este campo si este producto se utiliza en el proceso de producción de huevos.'
    )

