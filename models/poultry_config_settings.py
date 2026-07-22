# -*- coding: utf-8 -*-

from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Mantenido en el modelo (sin vista en Ajustes) para que validaciones globales de
    # res.config.settings no fallen si quedó arch huérfano en BD. Configuración real: res.company.
    poultry_stock_dashboard_category_ids = fields.Many2many(
        'product.category',
        related='company_id.poultry_stock_dashboard_category_ids',
        readonly=False,
        string='Tablero cobertura: categorías',
    )

    poultry_unclassified_egg_product_id = fields.Many2one(
        'product.product',
        string='Producto para Huevo sin Clasificar',
        config_parameter='poultry_management.unclassified_egg_product_id',
        domain="[('type', '=', 'consu'), ('active', '=', True)]",
        help='Producto que se utilizará para representar el huevo sin clasificar en las recolecciones de producción'
    )

    poultry_week_start_day = fields.Selection([
        ('birth', 'Día de nacimiento del lote'),
        ('monday', 'Lunes'),
        ('tuesday', 'Martes'),
        ('wednesday', 'Miércoles'),
        ('thursday', 'Jueves'),
        ('friday', 'Viernes'),
        ('saturday', 'Sábado'),
        ('sunday', 'Domingo'),
    ], string='Inicio de la Semana de Vida', default='birth',
        config_parameter='poultry_management.week_start_day',
        help='Cómo se numeran las Semanas de Vida de los lotes en indicadores y '
             'reportes. "Día de nacimiento del lote": la Semana 1 arranca el día '
             'que nació el lote. Un día fijo (ej. Lunes): la Semana 1 arranca el '
             'primer lunes desde el nacimiento y todas las semanas cortan de lunes '
             'a domingo, igual que las planillas de la granja. Después de cambiar '
             'este ajuste hay que correr "Recalcular Indicadores de Producción" '
             'para renumerar los valores semanales ya calculados. La vacunación '
             'no usa este ajuste (la semana del plan es edad biológica: semana N '
             '= N x 7 días de vida).')
