# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PoultryIndicator(models.Model):
    _name = 'poultry.indicator'
    _description = 'Indicador de Estándar de Genética'
    _order = 'sequence, name'

    name = fields.Char(string='Nombre', required=True, index=True)
    code = fields.Char(string='Código', index=True)
    uom_id = fields.Many2one('uom.uom', string='Unidad de Medida', required=True)
    category = fields.Selection([
        ('mortality', 'Mortalidad'),
        ('weight', 'Peso Corporal'),
        ('feed_consumption', 'Consumo de Alimento'),
        ('water_consumption', 'Consumo de Agua'),
        ('uniformity', 'Uniformidad'),
        ('egg_production', 'Producción de Huevos'),
        ('egg_mass', 'Masa de Huevo'),
        ('egg_weight', 'Peso del Huevo'),
    ], string='Categoría', index=True,
        help='Agrupación funcional del indicador, según las tablas de rendimiento del '
             'proveedor de genética (Período de Crianza / Período de Producción).')
    sequence = fields.Integer(string='Secuencia', default=10)
    active = fields.Boolean(string='Activo', default=True)
    notes = fields.Text(string='Notas')
    real_value_source = fields.Char(
        string='Origen de Valor Real',
        help="Referencia técnica (informativa, aún no utilizada por el sistema) al dato "
             "real de Odoo que en el futuro se comparará contra este indicador. "
             "Formato sugerido 'modelo:campo', por ejemplo 'poultry.mortality:dead_count' "
             "o 'poultry.egg.collection:average_weight_elaborated'."
    )

    standard_ids = fields.One2many('poultry.genetics.standard', 'indicator_id', string='Estándares')
    standard_count = fields.Integer(string='Cantidad de Estándares', compute='_compute_standard_count')

    @api.depends('standard_ids')
    def _compute_standard_count(self):
        for indicator in self:
            indicator.standard_count = len(indicator.standard_ids)
