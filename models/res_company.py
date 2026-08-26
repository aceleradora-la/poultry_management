# -*- coding: utf-8 -*-

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    poultry_stock_dashboard_category_ids = fields.Many2many(
        'product.category',
        'res_company_poultry_stock_dashboard_category_rel',
        'company_id',
        'category_id',
        string='Tablero cobertura: categorías',
        help='Si está vacío, el tablero incluye todos los productos almacenables. '
             'Si selecciona categorías, solo se muestran variantes cuya categoría está en la lista.',
    )
