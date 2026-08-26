# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class PoultryIndicator(models.Model):
    _name = 'poultry.indicator'
    _description = 'Indicador de Estándar de Genética'
    _order = 'sequence, name'

    name = fields.Char(string='Nombre', required=True, index=True)
    code = fields.Char(string='Código', index=True)
    uom_id = fields.Many2one('uom.uom', string='Unidad de Medida', required=True)
    # Gobierna QUÉ se completa en el formulario: la Fórmula o la configuración del
    # cálculo interno. Es un campo de presentación -el motor sigue decidiendo por
    # formula_mode-, pero mantenerlos sincronizados (ver _onchange y el constraint)
    # evita el estado confuso de tener las dos configuraciones a la vez.
    calculation_source = fields.Selection([
        ('formula', 'Fórmula configurable'),
        ('legacy', 'Cálculo interno del sistema'),
    ], string='Cómo se calcula', default='formula', required=True,
        help='"Fórmula configurable": el Valor Real se define acá mismo eligiendo '
             'Numerador, Denominador y Modo de Cálculo. Es la forma recomendada y '
             'permite crear variantes (ej. el mismo indicador sobre Aves Vivas y '
             'sobre Aves Alojadas).\n'
             '"Cálculo interno del sistema": el valor lo calcula el código del '
             'módulo, identificando al indicador por su Categoría y Tipo de '
             'Acumulación. Es como funcionaba antes; sirve para volver atrás si una '
             'fórmula no da lo esperado.')
    formula_preview = fields.Char(
        string='Fórmula', compute='_compute_formula_preview',
        help='Cómo queda la fórmula configurada, en una línea.')
    values_outdated = fields.Boolean(
        string='Valores desactualizados', default=False, copy=False,
        help='Se marca solo cuando cambia la forma de calcular este indicador: los '
             'Valores Reales ya guardados siguen siendo los de la configuración '
             'anterior hasta que se recalculen.')
    category = fields.Selection([
        ('mortality', 'Mortalidad'),
        # Categoría propia (no 'mortality'): los cálculos eligen el indicador de
        # cada métrica por (categoría, tipo de acumulación) con limit=1, y si la
        # cantidad compartiera categoría con el % podría robarle el lugar según
        # la secuencia. Con categoría separada no hay ambigüedad posible.
        ('mortality_count', 'Mortalidad (Cantidad de Aves)'),
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
             'proveedor de genética (Período de Crianza / Período de Producción).\n'
             'Si el indicador tiene FÓRMULA cargada, este campo es solo organizativo '
             '(agrupa y filtra en las listas): el cálculo sale de la fórmula. Es '
             'obligatorio en cambio para los indicadores que usan el cálculo interno, '
             'porque es como el sistema sabe cuál es cuál.')
    sequence = fields.Integer(string='Secuencia', default=10)
    active = fields.Boolean(string='Activo', default=True)
    visible_by_default = fields.Boolean(
        string='Mostrar por defecto en los reportes', default=True,
        help='Sin tildar, el indicador no aparece al abrir el reporte y el usuario lo '
             'agrega cuando lo necesita desde el desplegable Indicadores. Útil para los '
             'de consulta ocasional, sin tener que ocultarlos a mano cada vez. No afecta '
             'el cálculo: el valor se guarda igual.')
    period_scope = fields.Selection([
        ('crianza', 'Crianza'),
        ('produccion', 'Producción'),
        ('both', 'Crianza y Producción'),
    ], string='Período', default='both', required=True,
        help='En qué reporte de Seguimiento de Estándares aparece este indicador: '
             'solo en el de Crianza, solo en el de Producción, o en ambos (para '
             'indicadores compartidos como Mortandad o Peso Corporal).')
    accumulation_type = fields.Selection([
        ('none', 'Ninguno (valor independiente cada día)'),
        ('live', 'Acumulado (suma corrida) sobre Aves Vivas'),
        ('housed', 'Acumulado (suma corrida) sobre Aves Alojadas'),
        ('original_rate', 'Diario (sin acumular) sobre Aves Originales del Lote'),
        ('original_cumulative', 'Acumulado / Estado sobre Aves Originales del Lote'),
        ('ratio_cumulative', 'Acumulado desde Inicio de Producción (cociente de acumulados)'),
    ], string='Tipo de Acumulación', default='none', required=True,
        help='Si el indicador tiene FÓRMULA cargada, este campo es solo organizativo: '
             'lo que manda es el Modo de Cálculo de la fórmula. Aplica a los '
             'indicadores que usan el cálculo interno.\n'
             'OJO: esto NO indica si el cálculo divide por aves vivas, alojadas u '
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
    # -- Fórmula configurable ---------------------------------------------------
    # Reemplaza el cableado de cada fórmula en el código: el cálculo automático
    # toma el numerador, el denominador y el modo de acá. Un indicador SIN Modo de
    # Cálculo sigue usando el cálculo cableado de siempre (respaldo intacto), así
    # que vaciar el Modo revierte ese indicador sin necesidad de tocar código.
    # Las etiquetas son las del campo real de Odoo que cada opción toma, con el
    # modelo de origen entre paréntesis, para que sean reconocibles en pantalla.
    formula_numerator = fields.Selection([
        # Del Cierre de Galpón / OF de Huevo sin Clasificar
        ('eggs', 'Total Huevos (Parte de Producción)'),
        ('egg_mass_g', 'Total Peso Estimado en g (Parte de Producción)'),
        ('egg_mass_kg', 'Total Peso Estimado en Kg (Parte de Producción)'),
        ('measured_egg_g', 'Total Peso Medido en g (Parte de Producción)'),
        ('dead_birds', 'Cantidad de Aves Muertas (Registro de Aves Muertas)'),
        ('feed_g', 'Alimento consumido en g (OF, componentes tipo Alimento)'),
        ('feed_kg', 'Alimento consumido en Kg (OF, componentes tipo Alimento)'),
        ('water_ml', 'Agua consumida en ml (OF, componentes tipo Agua)'),
        ('water_l', 'Agua consumida en l (OF, componentes tipo Agua)'),
        ('live_birds', 'Aves Vivas (Lote de Aves)'),
        ('production_cost', 'Costo de la OF (botón Valoración de la Orden de Fabricación)'),
        # Del Parte de Registro de Peso
        ('weighed_g', 'Peso Total en g (Parte de Registro de Peso)'),
        ('uniform_birds', 'Aves dentro de la Banda de Uniformidad (Parte de Registro de Peso)'),
    ], string='Numerador',
        help='Dato del día que va ARRIBA en la división. Los datos del galpón '
             '(huevos, masa, alimento, agua, costo) se reparten entre los lotes '
             'presentes según su población viva, igual que hasta ahora.\n'
             'El "Costo de la OF" es la suma de las capas de valuación de los '
             'componentes consumidos: lo mismo que muestra el botón Valoración de '
             'la Orden de Fabricación. Solo existe una vez que la OF está Hecha; '
             'si no hay valuación, el indicador no se calcula ese día (en vez de '
             'mostrar cero).')
    formula_denominator = fields.Selection([
        ('live_birds', 'Aves Vivas del día (Lote de Aves)'),
        # Base del % de Mortandad: las vivas ANTES de las muertas del día
        # (vivas al cierre + muertas), no las que quedaron.
        ('live_birds_start', 'Aves Vivas al inicio del día (Lote de Aves)'),
        ('housed_birds', 'Aves Alojadas (Lote de Aves, base fija)'),
        ('housed_or_original_birds',
         'Aves Alojadas, o Cantidad de Aves si el lote no entró en producción (Lote de Aves)'),
        ('original_birds', 'Cantidad de Aves (Lote de Aves, base fija)'),
        ('eggs', 'Total Huevos (Parte de Producción)'),
        ('egg_units', 'Unidades de huevo (Total Huevos / Huevos por Unidad)'),
        # Divide por la CONSTANTE Huevos por Unidad, para expresar una cantidad en
        # docenas, cajones, etc. (ej. Huevos de la Semana en cajones = huevos / 360).
        # Distinto de 'egg_units', que divide por la cantidad de unidades producidas
        # y sirve para la Conversión Alimenticia (kg de alimento por docena).
        ('egg_group_size', 'Huevos por Unidad (constante: 12 docena, 360 cajón...)'),
        ('egg_mass_kg', 'Total Peso Estimado en Kg (Parte de Producción)'),
        ('eggs_with_weight', 'Huevos con Peso Medio cargado (Parte de Producción)'),
        ('weighed_birds', 'Aves Pesadas (Parte de Registro de Peso)'),
        ('one', 'Ninguno (cantidad cruda, sin dividir)'),
    ], string='Denominador',
        help='Dato del día que va ABAJO en la división, o "Ninguno" para guardar '
             'la cantidad cruda. Acá se elige la BASE del indicador: la población '
             'viva del día, las Aves Alojadas (foto fija a la Entrada en '
             'Producción) o la Cantidad de Aves original del lote.')
    formula_factor = fields.Selection([
        ('1', 'Ninguno'),
        ('100', 'Porcentaje (×100)'),
    ], string='Factor', default='1',
        help='Multiplicador final. Usar Porcentaje cuando el indicador se expresa '
             'en %. Las conversiones de unidad (Kg a g, l a ml) ya están en las '
             'opciones del Numerador, no se hacen con el factor.')
    weekly_aggregation = fields.Selection([
        ('auto', 'Automática según la fórmula'),
        ('sum', 'Suma del período'),
        ('last', 'Último valor del período'),
    ], string='Agregación Semanal', default='auto', required=True,
        help='Cómo se combinan los valores DIARIOS al mostrar la semana (o el mes, o '
             'un rango) en el reporte.\n'
             '"Automática": lo que corresponde a la fórmula — las tasas se agregan '
             'como suma(numerador)/suma(denominador) (promedio ponderado real, no '
             'promedio de promedios) y los acumulados muestran el último valor.\n'
             '"Suma del período": para CANTIDADES, no tasas (ej. Huevos de la Semana, '
             'Aves Muertas, Kg de Alimento): 8 + 5 + 7 = 20. Sin esto una cantidad '
             'se mostraría como promedio diario y las cuentas darían mal.\n'
             '"Último valor": el del último día con dato del período (estados).')

    formula_mode = fields.Selection([
        ('daily', 'Valor del día (independiente)'),
        ('running_sum', 'Suma corrida (acumula el aporte de cada día)'),
        ('snapshot', 'Estado del lote a la fecha (foto, no suma)'),
        ('ratio_cumulative', 'Cociente de acumulados (numerador y denominador acumulados)'),
    ], string='Modo de Cálculo',
        help='Cómo se combina el valor de HOY con el histórico. VACÍO = este '
             'indicador usa el cálculo cableado de siempre (no el motor de '
             'fórmulas): vaciarlo es la forma de revertir un indicador. '
             '"Valor del día": independiente cada día (ej. % Ave-Día, Consumo). '
             '"Suma corrida": el aporte del día se suma al acumulado previo, '
             'empalmando con el histórico cargado a mano (ej. Huevos Acumulados, '
             'MORT. Acumulada). "Estado del lote": foto directa a la fecha, sin '
             'sumar (ej. % de Viabilidad). "Cociente de acumulados": se acumulan '
             'numerador y denominador por separado y el valor es su cociente '
             '(ej. Conversión Alimenticia acumulada; nunca se suman razones '
             'diarias entre sí porque el denominador cambia día a día).')

    egg_group_size = fields.Integer(
        string='Huevos por Unidad', default=12,
        help='Cuántos huevos forman la unidad en la que se expresa el indicador: '
             '12 = docena, 360 = cajón, 1 = por huevo individual.\n'
             'Lo usan los dos denominadores que hablan de unidades de huevo:\n'
             '- "Huevos por Unidad": para ver una CANTIDAD en esa unidad '
             '(ej. Huevos de la Semana en cajones = huevos / 360).\n'
             '- "Unidades de huevo": para dividir POR las unidades producidas '
             '(ej. Conversión Alimenticia = Kg de alimento por docena).'
    )
    color_below = fields.Char(
        string='Color por Debajo del Rango', default='#dc3545',
        help='Color del Valor Real en el reporte cuando queda por DEBAJO del rango '
             'Bajo-Alto del estándar. Depende de qué se mide: en % de Postura estar '
             'por debajo es malo (rojo), pero en Mortandad puede ser bueno (verde).')
    color_within = fields.Char(
        string='Color Dentro del Rango',
        help='Color del Valor Real cuando está DENTRO del rango Bajo-Alto. '
             'Vacío = color de texto normal (negro).')
    color_above = fields.Char(
        string='Color por Encima del Rango', default='#dc3545',
        help='Color del Valor Real cuando SUPERA el rango Bajo-Alto. Depende de qué '
             'se mide: en Mortandad superar el rango es malo (rojo), pero en % de '
             'Postura puede ser bueno (verde).')
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

    # Etiquetas cortas para la vista previa (las del Selection son largas a
    # propósito, para que se entiendan al elegirlas en el desplegable).
    _POULTRY_SHORT_LABELS = {
        'eggs': 'Huevos', 'egg_mass_g': 'Masa de huevo (g)',
        'egg_mass_kg': 'Masa de huevo (Kg)', 'measured_egg_g': 'Peso medido (g)',
        'dead_birds': 'Aves muertas', 'feed_g': 'Alimento (g)', 'feed_kg': 'Alimento (Kg)',
        'water_ml': 'Agua (ml)', 'water_l': 'Agua (l)', 'live_birds': 'Aves vivas',
        'weighed_g': 'Peso pesado (g)', 'uniform_birds': 'Aves en banda',
        'production_cost': 'Costo de la OF',
        'live_birds_start': 'Aves vivas al inicio del día',
        'housed_birds': 'Aves alojadas',
        'housed_or_original_birds': 'Aves alojadas (o cantidad de aves)',
        'original_birds': 'Cantidad de aves', 'egg_units': 'Unidades de huevo',
        'eggs_with_weight': 'Huevos con peso', 'weighed_birds': 'Aves pesadas',
    }
    _POULTRY_MODE_LABELS = {
        'daily': 'valor del día', 'running_sum': 'suma corrida',
        'snapshot': 'estado a la fecha', 'ratio_cumulative': 'cociente de acumulados',
    }
    _POULTRY_AGGREGATION_LABELS = {
        'sum': 'suma del período', 'last': 'último valor del período',
    }

    @api.depends('calculation_source', 'formula_numerator', 'formula_denominator',
                 'formula_factor', 'formula_mode', 'weekly_aggregation',
                 'egg_group_size', 'category', 'accumulation_type')
    def _compute_formula_preview(self):
        """Resumen legible de cómo se calcula el indicador, para verlo de un vistazo
        en la lista y en el formulario sin tener que leer cuatro campos."""
        categories = dict(self._fields['category'].selection)
        for indicator in self:
            if indicator.calculation_source != 'formula' or not indicator.formula_mode:
                label = categories.get(indicator.category) or 'sin configurar'
                indicator.formula_preview = f'Cálculo interno del sistema ({label})'
                continue
            numerator = self._POULTRY_SHORT_LABELS.get(
                indicator.formula_numerator, indicator.formula_numerator or '?')
            if indicator.formula_denominator == 'one':
                expression = numerator
            elif indicator.formula_denominator == 'egg_group_size':
                expression = f'{numerator} ÷ {indicator.egg_group_size or 12}'
            else:
                denominator = self._POULTRY_SHORT_LABELS.get(
                    indicator.formula_denominator, indicator.formula_denominator or '?')
                if indicator.formula_denominator == 'egg_units':
                    denominator = f'{denominator} (÷{indicator.egg_group_size or 12})'
                expression = f'{numerator} ÷ {denominator}'
            if indicator.formula_factor == '100':
                expression += ' × 100'
            detail = self._POULTRY_MODE_LABELS.get(indicator.formula_mode, '')
            aggregation = self._POULTRY_AGGREGATION_LABELS.get(indicator.weekly_aggregation)
            if aggregation:
                detail = f'{detail}, {aggregation}' if detail else aggregation
            indicator.formula_preview = f'{expression} · {detail}' if detail else expression

    # Cambiar cualquiera de estos campos cambia el número que da el indicador, así
    # que los valores ya guardados quedan viejos hasta recalcular.
    _POULTRY_CALCULATION_FIELDS = (
        'calculation_source', 'formula_numerator', 'formula_denominator',
        'formula_factor', 'formula_mode', 'weekly_aggregation', 'egg_group_size',
        'category', 'accumulation_type',
    )

    def write(self, vals):
        """Marca el indicador como desactualizado cuando cambia su forma de calcular:
        los Valores Reales guardados se calcularon con la configuración anterior y no
        se rehacen solos. La ficha muestra un aviso con el botón para recalcular."""
        touched = [f for f in self._POULTRY_CALCULATION_FIELDS if f in vals]
        outdated = self.browse()
        if touched and 'values_outdated' not in vals:
            # Se compara ANTES del super: después los valores viejos ya no están.
            outdated = self.filtered(
                lambda i: any((vals[f] or False) != (i[f] or False) for f in touched))
        result = super().write(vals)
        if outdated:
            super(PoultryIndicator, outdated).write({'values_outdated': True})
        return result

    def action_recompute_indicator(self):
        """Recalcula los Valores Reales de ESTE indicador (y solo de este), en toda
        la historia. Es el recálculo acotado del aviso "valores desactualizados":
        los indicadores restantes no se tocan."""
        self.ensure_one()
        if self.calculation_source != 'formula':
            raise UserError(
                'Este indicador usa el Cálculo interno del sistema, que identifica los '
                'indicadores por Categoría: no se puede recalcular de a uno. Usá '
                'Configuración → Configuración General → Recalcular Indicadores de '
                'Producción.'
            )
        count = self.env['poultry.coop.close'].sudo()._poultry_rebuild_all_indicator_values(
            only_indicators=self)
        self.values_outdated = False
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Indicador recalculado',
                'message': (f'Se recalcularon los valores de "{self.name}" en '
                            f'{count} Cierres de Galpón. El resto de los indicadores '
                            f'no se tocó.'),
                'type': 'success',
                'sticky': False,
            },
        }

    @api.onchange('calculation_source')
    def _onchange_calculation_source(self):
        """Deja una sola configuración cargada: al elegir Cálculo interno se limpia
        la fórmula (así el motor no lo toma), y al elegir Fórmula se propone el modo
        más común para no dejar el campo obligatorio vacío."""
        for indicator in self:
            if indicator.calculation_source == 'legacy':
                indicator.formula_numerator = False
                indicator.formula_denominator = False
                indicator.formula_mode = False
                indicator.weekly_aggregation = 'auto'
            elif not indicator.formula_mode:
                indicator.formula_mode = 'daily'

    # -- Motor de fórmulas: resolución ------------------------------------------

    @api.model
    def _poultry_legacy_indicator(self, category, accumulation_type):
        """Indicador de una categoría+tipo que TODAVÍA usa el cálculo cableado, es
        decir el que no tiene fórmula cargada. Todos los cálculos cableados buscan
        por acá para no pisar lo que ya escribe el motor de fórmulas: con fórmula
        lo calcula el motor, sin fórmula lo calcula el código. Nunca los dos.

        accumulation_type acepta un valor o una tupla/lista (la Viabilidad admite
        dos tipos históricos)."""
        operator = 'in' if isinstance(accumulation_type, (list, tuple)) else '='
        return self.search([
            ('category', '=', category),
            ('accumulation_type', operator,
             list(accumulation_type) if operator == 'in' else accumulation_type),
            ('active', '=', True),
            ('formula_mode', '=', False),
        ], limit=1)

    @api.model
    def _poultry_formula_indicators(self, source='coop_close'):
        """Indicadores activos con fórmula cargada para una fuente de datos.
        source='coop_close' (Cierre de Galpón / OF) o 'weight_record' (Parte de
        Registro de Peso). Los que no tienen Modo de Cálculo quedan afuera: esos
        los sigue calculando el código cableado."""
        domain = [('active', '=', True), ('formula_mode', '!=', False)]
        if source == 'weight_record':
            domain.append(('formula_numerator', 'in', list(self._POULTRY_WEIGHT_SOURCE_NUMERATORS)))
        else:
            domain.append(('formula_numerator', 'not in', list(self._POULTRY_WEIGHT_SOURCE_NUMERATORS)))
        return self.search(domain)

    def _poultry_formula_denominator_value(self, magnitudes):
        """Denominador de la fórmula para un lote. Los dos casos que dependen de
        Huevos por Unidad se resuelven acá y no en el recolector, porque esa
        cantidad es propia de cada indicador (12 = docena, 360 = cajón...):
        - 'egg_units': cantidad de unidades producidas (huevos / Huevos por Unidad).
          Es el denominador de la Conversión Alimenticia (kg de alimento por docena).
        - 'egg_group_size': la constante misma, para expresar una CANTIDAD en esa
          unidad (ej. Huevos de la Semana en cajones = huevos / 360)."""
        self.ensure_one()
        group_size = self.egg_group_size or 12
        if self.formula_denominator == 'egg_units':
            return magnitudes.get('_eggs_for_units', 0.0) / group_size if group_size else 0.0
        if self.formula_denominator == 'egg_group_size':
            return float(group_size)
        return magnitudes.get(self.formula_denominator, 0.0)

    @api.model
    def _poultry_apply_formulas(self, magnitudes_by_batch, coop, target_date,
                                production=None, source='coop_close', only_indicators=None):
        """Calcula y guarda el valor del día de cada indicador con fórmula, a partir
        de los datos crudos que recolectó la fuente (mrp.production o
        poultry.weight.record). Es el reemplazo genérico de los cálculos cableados:
        la fórmula sale de la ficha del indicador, no del código.

        Modos:
        - 'daily': el valor del día es numerador/denominador × factor.
        - 'running_sum': ese aporte se SUMA al acumulado previo, empalmando con el
          histórico cargado a mano (_poultry_previous_accumulated), para que los
          acumulados no se reinicien donde arranca el dato del sistema.
        - 'snapshot': foto del estado a la fecha (no suma nada).
        - 'ratio_cumulative': acumula numerador y denominador POR SEPARADO desde el
          día anterior y el valor es su cociente (nunca se suman razones diarias
          entre sí, porque el denominador cambia día a día).

        Se guarda numerator/denominator crudos (sin el factor) igual que los
        cálculos cableados, para que la agregación semanal no cambie."""
        indicators = self._poultry_formula_indicators(source)
        if only_indicators is not None:
            # Recálculo acotado a un indicador (botón de la ficha): no se tocan los
            # valores de los demás.
            indicators = indicators & only_indicators
        if not indicators or not magnitudes_by_batch:
            return
        Value = self.env['poultry.batch.indicator.value'].sudo()
        # El helper del empalme es genérico (no usa el registro de la OF), así que
        # se puede llamar sobre un recordset vacío de mrp.production.
        Production = self.env['mrp.production'].sudo()
        for magnitudes in magnitudes_by_batch.values():
            batch = magnitudes['batch']
            in_production = bool(
                batch.housed_bird_count and batch.production_start_date
                and target_date >= batch.production_start_date)
            for indicator in indicators:
                numerator = magnitudes.get(indicator.formula_numerator)
                if numerator is None:
                    continue
                denominator = indicator._poultry_formula_denominator_value(magnitudes)
                # Mismos guards que el cálculo cableado: las bases fijas de Aves
                # Alojadas y los cocientes de acumulados solo corren desde la
                # Fecha de Entrada en Producción (antes no hay base válida).
                needs_production = (indicator.formula_denominator == 'housed_birds'
                                    or indicator.formula_mode == 'ratio_cumulative')
                if needs_production and not in_production:
                    continue
                if not denominator:
                    continue
                factor = float(indicator.formula_factor or '1')
                daily_value = numerator / denominator * factor

                if indicator.formula_mode == 'ratio_cumulative':
                    previous = Value.search([
                        ('batch_id', '=', batch.id),
                        ('indicator_id', '=', indicator.id),
                        ('date', '<', target_date),
                    ], order='date desc', limit=1)
                    new_numerator = (previous.numerator if previous else 0.0) + numerator
                    new_denominator = (previous.denominator if previous else 0.0) + denominator
                    value = (new_numerator / new_denominator * factor) if new_denominator else 0.0
                    Value._set_value(batch, coop, target_date, indicator, value,
                                     numerator=new_numerator, denominator=new_denominator,
                                     production=production)
                    continue

                value = daily_value
                if indicator.formula_mode == 'running_sum':
                    value += Production._poultry_previous_accumulated(
                        batch, indicator, target_date)
                Value._set_value(batch, coop, target_date, indicator, value,
                                 numerator=numerator * factor, denominator=denominator,
                                 production=production)

    # Datos que solo existen en el Parte de Registro de Peso (otra fuente y otro
    # momento que el Cierre de Galpón): no se pueden mezclar con los de la OF.
    _POULTRY_WEIGHT_SOURCE_NUMERATORS = ('weighed_g', 'uniform_birds')
    _POULTRY_WEIGHT_SOURCE_DENOMINATORS = ('weighed_birds',)

    def _poultry_formula_key(self):
        """Identidad de la fórmula de un indicador (lo que lo hace único ante el
        motor). Dos indicadores pueden compartir Categoría y Tipo de Acumulación
        si sus fórmulas difieren -eso es justamente lo que habilita tener, por
        ejemplo, % de Postura sobre Aves Vivas y sobre Aves Alojadas a la vez."""
        self.ensure_one()
        return (self.formula_numerator, self.formula_denominator,
                self.formula_factor, self.formula_mode)

    @api.constrains('category', 'accumulation_type', 'active',
                    'formula_numerator', 'formula_denominator', 'formula_factor',
                    'formula_mode')
    def _check_unique_calculation_target(self):
        """Dos indicadores activos no pueden competir por el mismo cálculo:

        - CON fórmula (Modo de Cálculo cargado): la fórmula es la identidad, así
          que se prohíbe repetir la MISMA combinación numerador+denominador+
          factor+modo. Categoría y Tipo de Acumulación pueden repetirse: dos
          variantes con distinta base son un caso legítimo y deseado.
        - SIN fórmula: siguen usando el cálculo cableado, que busca por
          Categoría + Tipo de Acumulación con limit=1; ahí sí no puede haber dos
          (la búsqueda elegiría uno arbitrario y en silencio, como pasó con
          % Ave-Día y Huevos Acumulados Ave-Día compartiendo el mismo tipo)."""
        for indicator in self.filtered(lambda i: i.active):
            if indicator.formula_mode:
                twins = self.search([
                    ('active', '=', True),
                    ('id', '!=', indicator.id),
                    ('formula_mode', '=', indicator.formula_mode),
                    ('formula_numerator', '=', indicator.formula_numerator),
                    ('formula_denominator', '=', indicator.formula_denominator),
                    ('formula_factor', '=', indicator.formula_factor),
                ])
                if twins:
                    raise ValidationError(
                        f'El indicador "{twins[0].name}" ya tiene exactamente esta misma '
                        f'fórmula (mismo Numerador, Denominador, Factor y Modo de Cálculo). '
                        f'Dos indicadores con la misma fórmula recibirían el mismo valor: '
                        f'cambiá alguno de esos campos o desactivá uno de los dos.'
                    )
                continue
            if not indicator.category:
                continue
            others = self.search_count([
                ('category', '=', indicator.category),
                ('accumulation_type', '=', indicator.accumulation_type),
                ('active', '=', True),
                ('formula_mode', '=', False),
                ('id', '!=', indicator.id),
            ])
            if others:
                raise ValidationError(
                    f'Ya existe otro indicador activo SIN fórmula con la misma Categoría '
                    f'({dict(indicator._fields["category"].selection).get(indicator.category)}) '
                    f'y el mismo Tipo de Acumulación. El cálculo cableado no podría '
                    f'distinguir a cuál de los dos escribirle.'
                )

    @api.constrains('calculation_source', 'formula_numerator', 'formula_denominator',
                    'formula_mode', 'category')
    def _check_formula_coherence(self):
        """La configuración tiene que estar completa y ser una sola: o la fórmula, o
        el cálculo interno. Además, la fórmula no puede mezclar fuentes: los datos
        del Parte de Registro de Peso no conviven con los del Cierre de Galpón (se
        publican en momentos distintos y desde modelos distintos)."""
        for indicator in self:
            if indicator.calculation_source == 'legacy':
                if indicator.formula_mode:
                    raise ValidationError(
                        f'El indicador "{indicator.name}" está configurado como Cálculo '
                        f'interno del sistema, así que no puede tener una fórmula cargada. '
                        f'Elegí "Fórmula configurable" o vaciá el Modo de Cálculo.'
                    )
                if not indicator.category:
                    raise ValidationError(
                        f'El indicador "{indicator.name}" usa el Cálculo interno del '
                        f'sistema: hay que indicar la Categoría, que es como el sistema '
                        f'sabe qué valor le corresponde.'
                    )
                continue
            if not (indicator.formula_mode and indicator.formula_numerator
                    and indicator.formula_denominator):
                raise ValidationError(
                    f'El indicador "{indicator.name}" usa Fórmula configurable: hay que '
                    f'cargar Numerador, Denominador y Modo de Cálculo. Si querés que lo '
                    f'calcule el sistema, elegí "Cálculo interno del sistema".'
                )
            num_is_weight = indicator.formula_numerator in self._POULTRY_WEIGHT_SOURCE_NUMERATORS
            den_is_weight = indicator.formula_denominator in self._POULTRY_WEIGHT_SOURCE_DENOMINATORS
            if num_is_weight and not (den_is_weight or indicator.formula_denominator == 'one'):
                raise ValidationError(
                    'El Numerador elegido viene del Parte de Registro de Peso, así que el '
                    'Denominador debe ser Aves Pesadas (o Ninguno).'
                )
            if den_is_weight and not num_is_weight:
                raise ValidationError(
                    'El Denominador Aves Pesadas solo se puede usar con un Numerador del '
                    'Parte de Registro de Peso.'
                )
