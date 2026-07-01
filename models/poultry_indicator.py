# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


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
    accumulation_type = fields.Selection([
        ('none', 'Ninguno (valor independiente cada día)'),
        ('live', 'Acumulado (suma corrida) sobre Aves Vivas'),
        ('housed', 'Acumulado (suma corrida) sobre Aves Alojadas'),
    ], string='Tipo de Acumulación', default='none', required=True,
        help='OJO: esto NO indica si el cálculo divide por aves vivas o alojadas '
             '(eso ya lo hace la fórmula de cada indicador, sea cual sea este campo). '
             'Lo que distingue es si el valor de HOY se guarda solo, o se le SUMA al de '
             'AYER y sigue creciendo día tras día. "Ninguno": valor independiente cada '
             'día (ej. Consumo de Alimento, % Ave-Día: hoy puede dar más o menos que '
             'ayer); se agrega por semana como suma(numerador)/suma(denominador). '
             '"Acumulado sobre Aves Vivas": suma corrida desde el inicio de postura, '
             'nunca baja. "Acumulado sobre Aves Alojadas": misma suma corrida, pero '
             'usando como base la cantidad de aves alojadas al inicio (fija). Los '
             'acumulados no se suman ni promedian por semana: se muestra el último valor '
             'con fecha dentro del período. Solo puede haber UN indicador activo por '
             'combinación de Categoría + Tipo de Acumulación (si no, el cálculo no '
             'sabría a cuál de los dos escribirle).'
    )
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

    @api.constrains('category', 'accumulation_type', 'active')
    def _check_unique_category_accumulation_type(self):
        """El cálculo automático (mrp_production._poultry_compute_*) busca el
        indicador de una categoría+tipo de acumulación con limit=1: si hay más de
        uno activo, el resultado de esa búsqueda es arbitrario y silencioso, como
        pasó con % Ave-Día y Huevos Acumulados Ave-Día compartiendo el mismo tipo."""
        for indicator in self.filtered(lambda i: i.active and i.category):
            others = self.search_count([
                ('category', '=', indicator.category),
                ('accumulation_type', '=', indicator.accumulation_type),
                ('active', '=', True),
                ('id', '!=', indicator.id),
            ])
            if others:
                raise ValidationError(
                    f'Ya existe otro indicador activo con la misma Categoría '
                    f'({dict(indicator._fields["category"].selection).get(indicator.category)}) '
                    f'y el mismo Tipo de Acumulación. El cálculo automático no podría '
                    f'distinguir a cuál de los dos escribirle.'
                )
