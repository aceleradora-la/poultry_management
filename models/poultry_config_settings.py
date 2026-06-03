# -*- coding: utf-8 -*-

from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    poultry_unclassified_egg_product_id = fields.Many2one(
        'product.product',
        string='Producto para Huevo sin Clasificar',
        config_parameter='poultry_management.unclassified_egg_product_id',
        domain="[('type', '=', 'consu'), ('active', '=', True)]",
        help='Producto que se utilizará para representar el huevo sin clasificar en las recolecciones de producción'
    )
