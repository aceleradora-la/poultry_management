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
        ('viability', 'Viabilidad'),
        ('weight', 'Peso Corporal'),
        ('feed_consumption', 'Consumo de Alimento'),
        ('water_consumption', 'Consumo de Agua'),
        ('uniformity', 'Uniformidad'),
        ('egg_production', 'Producción de Huevos'),
        ('egg_mass', 'Masa de Huevo'),
        ('egg_weight', 'Peso del Huevo'),
        ('feed_conversion', 'Conversión Alimenticia (Alimento/Huevos)'),
        ('feed_egg_mass_conversion', 'Conversión Alimenticia (Alimento/Masa de Huevo)'),
    ], string='Categoría', index=True,
        help='Agrupación funcional del indicador, según las tablas de rendimiento del '
             'proveedor de genética (Período de Crianza / Período de Producción).')
    sequence = fields.Integer(string='Secuencia', default=10)
    active = fields.Boolean(string='Activo', default=True)
    accumulation_type = fields.Selection([
        ('none', 'Ninguno (valor independiente cada día)'),
        ('live', 'Acumulado (suma corrida) sobre Aves Vivas'),
        ('housed', 'Acumulado (suma corrida) sobre Aves Alojadas'),
        ('original_rate', 'Diario (sin acumular) sobre Aves Originales del Lote'),
        ('original_cumulative', 'Acumulado / Estado sobre Aves Originales del Lote'),
        ('ratio_cumulative', 'Acumulado desde Inicio de Producción (cociente de acumulados)'),
    ], string='Tipo de Acumulación', default='none', required=True,
        help='OJO: esto NO indica si el cálculo divide por aves vivas, alojadas u '
             'originales (eso ya lo hace la fórmula de cada indicador, sea cual sea '
             'este campo). Lo que distingue es si el valor de HOY se guarda solo, o '
             'se le SUMA/actualiza sobre el de AYER. "Ninguno" y "Diario sobre Aves '
             'Originales del Lote": valor independiente cada día (ej. Consumo de '
             'Alimento, % Ave-Día, % Postura sobre Aves Originales); se agrega por '
             'semana como suma(numerador)/suma(denominador). "Acumulado sobre Aves '
             'Vivas/Alojadas/Originales del Lote": suma corrida o estado del lote '
             '(ej. % Viabilidad Acumulada), usando como base la población viva de '
             'hoy, la alojada al inicio de producción (fija), o la cantidad total '
             'de aves que ingresaron al lote (fija), según corresponda. '
             '"Acumulado desde Inicio de Producción (cociente de acumulados)": para '
             'indicadores que NO son un porcentaje sobre una base fija de aves, sino '
             'la razón entre dos magnitudes que crecen día a día (ej. Conversión '
             'Alimenticia = kg de alimento acumulado / huevos o kg de masa de huevo '
             'acumulados); a diferencia de los demás acumulados, acá se guardan por '
             'separado el numerador y el denominador acumulados desde el Inicio de '
             'Producción, y el valor de cada día es su cociente (nunca se suman '
             'razones diarias entre sí, porque el denominador cambia día a día). Los '
             'acumulados no se suman ni promedian por semana: se muestra el último '
             'valor con fecha dentro del período. Solo puede haber UN indicador '
             'activo por combinación de Categoría + Tipo de Acumulación (si no, el '
             'cálculo no sabría a cuál de los dos escribirle).'
    )
    egg_group_size = fields.Integer(
        string='Huevos por Unidad (Conversión Alimenticia)', default=12,
        help='Solo aplica a la categoría Conversión Alimenticia (Alimento/Huevos): '
             'cantidad de huevos que forman la unidad contra la que se divide el '
             'consumo de alimento (12 = docena, 30 = cajón, 1 = por huevo individual, '
             'etc., según cómo se quiera expresar el indicador).'
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
    applicable_version_ids = fields.Many2many(
        'poultry.genetics.standard.version', string='Versiones de Estándar Aplicables',
        help='En qué Versiones de Estándar de Genética aplica este indicador (puede ser '
             'más de una, incluso de genéticas distintas). El Reporte de Seguimiento de '
             'Estándares usa esto para decidir qué columnas mostrar al elegir una Versión: '
             'si se deja vacío, el indicador se considera aplicable a TODAS las versiones '
             '(compatibilidad con indicadores ya existentes que no se etiquetaron).'
    )

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
