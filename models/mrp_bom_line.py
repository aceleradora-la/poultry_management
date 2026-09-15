# -*- coding: utf-8 -*-

from odoo import models, fields


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    poultry_consumption_type = fields.Selection([
        ('none', 'Ninguno'),
        ('feed', 'Alimento'),
        ('water', 'Agua'),
    ], string='Tipo de Consumo Avícola', default='none',
        help='Marca esta línea de componente como Alimento o Agua para que Gestión '
             'Avícola calcule el consumo real (g/ave-día, ml/ave-día) al cerrar la '
             'Orden de Fabricación de Huevo sin Clasificar.')

    # Auxiliar para mostrar la columna solo en BOMs de productos de producción de huevos.
    product_is_egg_production = fields.Boolean(
        related='bom_id.product_tmpl_id.is_egg_production',
        readonly=True,
    )
