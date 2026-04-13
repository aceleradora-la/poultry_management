# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.osv import expression
import math
import logging

_logger = logging.getLogger(__name__)


class PoultryEggCollectionLine(models.Model):
    _name = 'poultry.egg.collection.line'
    _description = 'Línea de Recolección de Producción de Huevos'
    _order = 'collection_date desc, collection_id, product_variant_id'

    collection_id = fields.Many2one('poultry.egg.collection', string='Recolección', 
                                     required=True, ondelete='cascade', index=True)
    product_variant_id = fields.Many2one('product.product', string='Variante del Producto', 
                                          required=True, domain="[('type', '=', 'product')]")
    product_variant_name = fields.Char(string='Producto', related='product_variant_id.name', 
                                        readonly=True)
    
    # Campos relacionados para usar en vistas pivot y reportes
    collection_date = fields.Date(string='Fecha de Recolección', 
                                  related='collection_id.date', 
                                  store=True, 
                                  readonly=True, 
                                  index=True)
    collection_coop_id = fields.Many2one('poultry.coop', string='Galpón',
                                         related='collection_id.coop_id',
                                         store=True,
                                         readonly=True)

    # Valor del atributo (ej. Calibre: 1, 2, 3, X, S) para agrupar en pivot
    attribute_value_id = fields.Many2one('product.attribute.value', string='Valor Atributo',
                                         compute='_compute_attribute_value_id',
                                         store=True, readonly=True, index=True,
                                         help='Valor del atributo principal (ej. Calibre) para agrupar por 1, 2, 3, X, S, etc.')
    attribute_value_name = fields.Char(
        string='Valor del Atributo',
        compute='_compute_attribute_value_name',
        readonly=True,
        help='Texto corto del valor del atributo para mostrar en líneas del parte.'
    )
    
    # Relación con valores de unidades de medida (nuevo sistema dinámico)
    uom_value_ids = fields.One2many('poultry.egg.collection.line.uom', 'line_id',
                                     string='Valores por Unidad de Medida')
    
    # Campos legacy (mantener por compatibilidad, pero deprecados)
    # Estos se mantienen para migración gradual
    uom_box_id = fields.Many2one('uom.uom', string='Unidad Cajón', 
                                  compute='_compute_uom_ids', store=False)
    uom_map_id = fields.Many2one('uom.uom', string='Unidad Maple', 
                                  compute='_compute_uom_ids', store=False)
    uom_egg_id = fields.Many2one('uom.uom', string='Unidad Huevo', 
                                  compute='_compute_uom_ids', store=False)
    
    # Campos sincronizados con uom_value_ids
    # Estos campos se sincronizan bidireccionalmente con uom_value_ids para mostrar en el tree
    # Usamos campos normales (no computed) y sincronizamos manualmente en write() y onchange
    initial_box = fields.Float(string='Inicial PT', default=0.0, digits=(16, 2))
    initial_map = fields.Float(string='Inicial PI', default=0.0, digits=(16, 2))
    initial_egg = fields.Float(string='Inicial Huevo', default=0.0, digits=(16, 2))
    
    final_box = fields.Float(string='Bruto PT', default=0.0, digits=(16, 2))
    final_map = fields.Float(string='Bruto PI', default=0.0, digits=(16, 2))
    final_egg = fields.Float(string='Bruto Huevo', default=0.0, digits=(16, 2))
    
    # Peso Medio por variante
    average_weight = fields.Float(string='Peso Medio', default=0.0, digits=(16, 3),
                                   help='Peso medio en gramos por huevo de esta variante')
    
    # Total de huevos brutos calculados (para % de distribución)
    total_eggs_gross = fields.Float(string='Total Huevos Bruto', 
                                     compute='_compute_total_eggs_gross',
                                     store=True, digits=(16, 2),
                                     help='Total de huevos brutos convertidos a unidad de referencia')
    
    # % de cada línea respecto al total del mismo parte (no usar como medida en pivot: suma de % no es 100%).
    weight_distribution_percent = fields.Float(
        string='% del Parte',
        compute='_compute_weight_distribution',
        store=True,
        digits=(16, 4),
        aggregator=None,
        help='Participación de la línea en el total de huevos de ese parte/recolección. '
             'Solo tiene sentido en vista lista/detalle; no agregar en tabla dinámica.',
    )
    
    # Medida única de % en pivot: celda / total de fila (read_group). Fracción 0..1 (mostrar como % en cliente).
    pivot_row_distribution_percent = fields.Float(
        string='% Distribución',
        compute='_compute_pivot_row_distribution_percent',
        store=True,
        digits=(16, 4),
        aggregator='avg',
        help='Tabla dinámica (0..1): celda/total de fila; en totales de fila o columna, celda/total del informe.',
    )
    
    @api.model
    def _update_field_strings(self):
        """Actualiza los nombres de los campos legacy dinámicamente basándose en uom_value_ids"""
        # Este método se puede llamar desde la vista o desde un cron para actualizar los nombres
        # Por ahora, los nombres se manejarán en la vista usando los campos uom_X_name
        pass
    
    produced_box = fields.Float(string='Final PT', compute='_compute_production', 
                                 store=True, digits=(16, 2))
    produced_map = fields.Float(string='Final PI', compute='_compute_production', 
                                 store=True, digits=(16, 2))
    produced_egg = fields.Float(string='Final Huevo', compute='_compute_production', 
                                 store=True, digits=(16, 2))
    
    # Campo para almacenar el total de producción en unidad de referencia
    total_produced_reference = fields.Float(string='Total Producido (Unidad Ref)', 
                                             compute='_compute_production', 
                                             store=True, digits=(16, 2),
                                             help='Total producido en la unidad de medida de referencia (Huevo)')
    
    # Total de cajones producidos (Total Huevos / 360)
    total_boxes = fields.Float(string='Total Cajones', 
                               compute='_compute_total_boxes',
                               store=True, digits=(16, 2),
                               help='Total de cajones producidos (Total Huevos / 360)')
    
    # Campos para calcular peso medio elaborado agregado
    weight_total_grams = fields.Float(string='Peso Total (g)', 
                                      compute='_compute_weight_total_grams',
                                      store=True, digits=(16, 2),
                                      help='Peso total en gramos: average_weight * total_produced_reference (solo si average_weight > 0)')
    
    eggs_with_weight = fields.Float(string='Huevos con Peso', 
                                    compute='_compute_weight_total_grams',
                                    store=True, digits=(16, 2),
                                    help='Total de huevos que tienen peso medio definido')
    
    # Peso medio elaborado agregado (para usar en pivot)
    # Sin group_operator para que read_group calcule el promedio ponderado correctamente
    # store=True permite que el campo esté disponible, pero el cálculo se hace en read_group
    average_weight_elaborated_aggregated = fields.Float(string='Peso Medio Elaborado (g)', 
                                                         compute='_compute_average_weight_elaborated_aggregated',
                                                         store=True, digits=(16, 3),
                                                         help='Peso medio elaborado agregado: suma de (peso * huevos) / suma de huevos (solo variantes con peso medio)')
    
    @api.depends('product_variant_id')
    def _compute_uom_ids(self):
        """Obtiene las unidades de medida (método legacy)"""
        for line in self:
            # Buscar las unidades de medida por nombre en cualquier categoría
            box_uom = self.env['uom.uom'].search([
                ('name', 'ilike', 'Cajón'),
            ], limit=1)
            if not box_uom:
                box_uom = self.env['uom.uom'].search([
                    ('name', 'ilike', 'Cajon'),
                ], limit=1)
            
            map_uom = self.env['uom.uom'].search([
                ('name', 'ilike', 'Maple'),
            ], limit=1)
            
            egg_uom = self.env['uom.uom'].search([
                ('name', 'ilike', 'Huevo'),
            ], limit=1)
            if not egg_uom:
                egg_uom = self.env['uom.uom'].search([
                    ('name', 'ilike', 'Unidades'),
                ], limit=1)
            
            line.uom_box_id = box_uom.id if box_uom else False
            line.uom_map_id = map_uom.id if map_uom else False
            line.uom_egg_id = egg_uom.id if egg_uom else False

    @api.depends('product_variant_id')
    def _compute_attribute_value_id(self):
        """
        Obtiene el valor del atributo principal (ej. Calibre) de la variante.
        Permite agrupar en el pivot por 1, 2, 3, X, S, C, D, etc.
        """
        for line in self:
            if not line.product_variant_id:
                line.attribute_value_id = False
                continue
            line.attribute_value_id = self._get_main_attribute_value_from_variant(line.product_variant_id)

    @api.depends('attribute_value_id')
    def _compute_attribute_value_name(self):
        """
        Campo de presentación para mostrar solo el valor del atributo
        (ej. 1, 2, 3, X, S) en las líneas del parte.
        """
        for line in self:
            line.attribute_value_name = line.attribute_value_id.name if line.attribute_value_id else False

    @api.model
    def _get_main_attribute_value_from_variant(self, variant):
        """
        Retorna el valor principal del atributo para una variante.
        Prioriza atributo 'Calibre' y, si no existe, usa el primer atributo disponible.
        """
        if not variant:
            return False
        ptavs = getattr(variant, 'product_template_attribute_value_ids', None)
        if not ptavs:
            return False

        calibre_attr = self.env['product.attribute'].search([('name', 'ilike', 'Calibre')], limit=1)
        if calibre_attr:
            ptav = ptavs.filtered(lambda p: p.product_attribute_value_id.attribute_id == calibre_attr)
            if ptav:
                return ptav[0].product_attribute_value_id
        return ptavs[0].product_attribute_value_id

    @api.model
    def _get_attribute_column_label(self, collection_id=False):
        """
        Retorna el nombre del atributo usado para la columna (ej. 'Calibre').
        """
        collection = self.env['poultry.egg.collection'].browse(collection_id) if collection_id else self.env['poultry.egg.collection']
        variant = False
        if collection_id and collection.exists():
            variant = (collection.line_ids[:1].product_variant_id or collection.product_tmpl_id.product_variant_ids[:1])
        if variant:
            attr_value = self._get_main_attribute_value_from_variant(variant)
            if attr_value and attr_value.attribute_id:
                return attr_value.attribute_id.name
        return 'Valor del Atributo'
    
    @api.model
    def _get_poultry_uoms(self, product_variant):
        """Obtiene las unidades de medida configuradas para Poultry Management del producto"""
        if not product_variant:
            return self.env['uom.uom']
        
        # Obtener la categoría de unidad de medida del producto
        uom_category = product_variant.uom_id.category_id
        
        # Buscar todas las unidades de medida de esa categoría que estén marcadas para usar en poultry
        # No podemos usar order='ratio desc' porque ratio es computed no almacenado
        uoms = self.env['uom.uom'].search([
            ('category_id', '=', uom_category.id),
            ('use_in_poultry', '=', True),
            ('active', '=', True),
        ])
        
        # Ordenar en Python por ratio descendente (mayor a menor)
        uoms = uoms.sorted(key=lambda u: u.ratio or 0.0, reverse=True)
        
        return uoms
    
    @api.model
    def _get_reference_uom(self, product_variant):
        """Obtiene la unidad de medida de referencia (ratio = 1.0)"""
        if not product_variant:
            return False
        
        uom_category = product_variant.uom_id.category_id
        # No podemos filtrar por ratio directamente porque es computed no almacenado
        # Buscar todas las unidades de la categoría y filtrar en Python
        uoms = self.env['uom.uom'].search([
            ('category_id', '=', uom_category.id),
            ('active', '=', True),
        ])
        
        # Buscar la unidad con ratio = 1.0
        reference_uom = uoms.filtered(lambda u: u.ratio == 1.0)
        
        return reference_uom[0] if reference_uom else False
    
    @api.depends('final_box', 'final_map', 'final_egg',
                 'uom_value_ids.final_qty', 'uom_value_ids.uom_ratio',
                 'product_variant_id')
    def _compute_total_eggs_gross(self):
        """Calcula el total de huevos brutos convertidos a la unidad de referencia (huevo)."""
        for line in self:
            total_reference = 0.0

            # Usar el sistema dinámico si hay valores de UoM
            if line.uom_value_ids:
                for uom_val in line.uom_value_ids:
                    qty = uom_val.final_qty or 0.0
                    ratio = uom_val.uom_ratio or 0.0
                    # ratio es cuántas unidades de referencia (huevos) hay en 1 unidad de esta UoM
                    total_reference += qty * ratio
            else:
                # Método legacy: convertir PT/PI/Huevo a huevos usando sus ratios
                box_ratio = line.uom_box_id.ratio if line.uom_box_id else 0.0
                map_ratio = line.uom_map_id.ratio if line.uom_map_id else 0.0
                egg_ratio = line.uom_egg_id.ratio if line.uom_egg_id else 0.0

                total_reference += (line.final_box or 0.0) * box_ratio
                total_reference += (line.final_map or 0.0) * map_ratio
                total_reference += (line.final_egg or 0.0) * egg_ratio

            line.total_eggs_gross = total_reference
    
    @api.depends('collection_id', 'collection_id.line_ids.total_produced_reference',
                 'total_produced_reference')
    def _compute_weight_distribution(self):
        """
        Calcula el % de distribución según el total de huevos producidos de todas las variantes.

        Nota: `widget="percentage"` en Odoo espera una fracción (0..1), no 0..100.
        """
        # Procesar todas las líneas de todas las collections afectadas
        all_collections = self.mapped('collection_id')
        for collection in all_collections:
            if not collection:
                continue
            
            # Calcular total de huevos producidos de todas las líneas de la collection
            total_eggs = 0.0
            for line in collection.line_ids:
                if line.total_produced_reference:
                    total_eggs += line.total_produced_reference
            
            # Calcular % para cada línea de esta collection
            for line in collection.line_ids:
                if total_eggs > 0 and line.total_produced_reference:
                    # Fracción 0..1 (el widget percentage lo muestra como 0..100%)
                    # % = (Huevos producidos de esta variante / Total de huevos producidos) * 100
                    line.weight_distribution_percent = (line.total_produced_reference / total_eggs)
                else:
                    line.weight_distribution_percent = 0.0
    
    @api.depends('total_produced_reference')
    def _compute_pivot_row_distribution_percent(self):
        """El valor real se calcula en read_group para el pivot; en listado/form queda 0."""
        for line in self:
            line.pivot_row_distribution_percent = 0.0
    
    @api.model
    def _groupby_spec_base_field(self, spec):
        """Convierte p.ej. collection_date:day -> collection_date (nombre de campo en dominio)."""
        if not spec or not isinstance(spec, str):
            return None
        base = spec.split(':', 1)[0].strip()
        return base or None
    
    @api.model
    def _pivot_column_base_fields(self, groupby):
        """
        Campos que actúan como columnas en el pivot: van al denominador del % de fila
        (se eliminan del dominio de la celda para obtener el total de la fila).
        """
        ctx = self.env.context or {}
        col_specs = ctx.get('pivot_column_groupby')
        if col_specs:
            return {b for b in (self._groupby_spec_base_field(s) for s in col_specs) if b}
        # Respaldo: sufijos de groupby tras las filas definidas en contexto
        row_specs = ctx.get('pivot_row_groupby') or []
        if isinstance(groupby, str):
            gb = [groupby]
        else:
            gb = list(groupby or [])
        if len(gb) <= len(row_specs):
            return set()
        tail = gb[len(row_specs):]
        return {b for b in (self._groupby_spec_base_field(s) for s in tail) if b}
    
    @api.model
    def _pivot_row_base_fields(self, groupby):
        """Campos de filas del pivot (desde contexto o restando columnas del groupby)."""
        ctx = self.env.context or {}
        row_specs = ctx.get('pivot_row_groupby')
        if row_specs:
            return {b for b in (self._groupby_spec_base_field(s) for s in row_specs) if b}
        col_fs = self._pivot_column_base_fields(groupby)
        gb = [groupby] if isinstance(groupby, str) else list(groupby or [])
        if not gb:
            return set()
        if not col_fs:
            return {b for b in (self._groupby_spec_base_field(s) for s in gb) if b}
        return {
            b for b in (self._groupby_spec_base_field(s) for s in gb)
            if b and b not in col_fs
        }

    @api.model
    def _choose_distribution_dimension(self, groupby):
        """
        Decide sobre qué dimensión calcular el % distribución.

        Regla (auto):
        - Si hay 2+ niveles de filas, distribuir por el ÚLTIMO nivel de filas (p.ej. Calibre dentro de Fecha),
          manteniendo fijas las columnas.
        - Si no, y hay columnas, distribuir por el ÚLTIMO nivel de columnas (p.ej. Galpón dentro de Fecha),
          manteniendo fijas las filas.
        - Si no hay columnas, distribuir por el último nivel de filas.
        """
        ctx = self.env.context or {}
        row_specs = ctx.get('pivot_row_groupby') or []
        col_specs = ctx.get('pivot_column_groupby') or []
        row_bases = [self._groupby_spec_base_field(s) for s in row_specs]
        col_bases = [self._groupby_spec_base_field(s) for s in col_specs]
        row_bases = [b for b in row_bases if b]
        col_bases = [b for b in col_bases if b]

        if len(row_bases) >= 2:
            return ('row', row_bases[-1])
        if col_bases:
            return ('col', col_bases[-1])
        if row_bases:
            return ('row', row_bases[-1])

        # Fallback si el contexto no trae row/col groupby (raro): inferir desde groupby
        gb = [groupby] if isinstance(groupby, str) else list(groupby or [])
        bases = [self._groupby_spec_base_field(s) for s in gb]
        bases = [b for b in bases if b]
        return ('row', bases[-1]) if bases else (None, None)
    
    @api.model
    def _domain_touches_field(self, domain, field_name):
        """True si el dominio acota el campo (incl. collection_date con rangos)."""
        if not domain or not field_name:
            return False
        try:
            norm = expression.normalize_domain(domain)
        except Exception:
            return False
        for item in norm:
            if isinstance(item, tuple) and len(item) >= 3 and item[0] == field_name:
                return True
        return False
    
    @api.model
    def _domain_without_fields(self, domain, field_names):
        """AND sin condiciones sobre los campos dados (p. ej. dimensiones de columna del pivot)."""
        if not domain:
            return []
        if not field_names:
            return domain
        try:
            norm = expression.normalize_domain(domain)
        except Exception:
            return domain
        leaves = [
            item for item in norm
            if isinstance(item, tuple) and len(item) >= 3 and item[0] not in field_names
        ]
        if not leaves:
            return []
        if len(leaves) == 1:
            return leaves
        return expression.AND([[leaf] for leaf in leaves])
    
    @api.model
    def _read_group_requests_field(self, fields_list, field_name):
        """Odoo 18 pasa medidas como 'pivot_row_distribution_percent:avg', no solo el nombre."""
        if not fields_list:
            return False
        for spec in fields_list:
            if spec == '__count':
                continue
            if not isinstance(spec, str):
                continue
            if spec == field_name or spec.startswith(field_name + ':'):
                return True
        if field_name in (self.env.context.get('pivot_measures') or []):
            return True
        return False
    
    @api.model
    def _read_group_strip_field_specs(self, fields_list, field_names):
        """Quita especificaciones 'field' o 'field:agg' del listado pasado a super().read_group."""
        if not fields_list:
            return fields_list
        out = []
        for spec in fields_list:
            skip = False
            if not isinstance(spec, str):
                out.append(spec)
                continue
            for name in field_names:
                if spec == name or spec.startswith(name + ':'):
                    skip = True
                    break
            if not skip:
                out.append(spec)
        return out
    
    @api.depends('total_produced_reference')
    def _compute_total_boxes(self):
        """Calcula el total de cajones producidos (Total Huevos / 360)"""
        for line in self:
            if line.total_produced_reference > 0:
                line.total_boxes = line.total_produced_reference / 360.0
            else:
                line.total_boxes = 0.0
    
    @api.depends('average_weight', 'total_produced_reference')
    def _compute_weight_total_grams(self):
        """Calcula el peso total en gramos y huevos con peso para cálculo agregado"""
        for line in self:
            if line.average_weight and line.average_weight > 0 and line.total_produced_reference:
                line.weight_total_grams = line.average_weight * line.total_produced_reference
                line.eggs_with_weight = line.total_produced_reference
            else:
                line.weight_total_grams = 0.0
                line.eggs_with_weight = 0.0
    
    @api.depends('average_weight', 'total_produced_reference', 'weight_total_grams', 'eggs_with_weight')
    def _compute_average_weight_elaborated_aggregated(self):
        """
        Calcula el peso medio elaborado agregado.
        Para líneas individuales, retorna el average_weight si existe.
        En el pivot, read_group calculará el promedio ponderado agregado correctamente.
        """
        for line in self:
            if line.eggs_with_weight and line.eggs_with_weight > 0:
                # Para una línea individual, el promedio es simplemente average_weight
                line.average_weight_elaborated_aggregated = line.average_weight if line.average_weight > 0 else 0.0
            else:
                line.average_weight_elaborated_aggregated = 0.0
    
    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        """
        Sobrescribe read_group para calcular average_weight_elaborated_aggregated
        correctamente en las agrupaciones del pivot usando promedio ponderado.
        Siempre calcula desde los registros base para evitar promedios de promedios.
        Fuerza orden decreciente por collection_date cuando es el primer groupby (pivot).
        """
        # Pivot: cuando el primer groupby es collection_date, forzar orden desc
        if groupby and not orderby:
            first_group = groupby[0] if isinstance(groupby, (list, tuple)) else groupby
            if isinstance(first_group, str) and first_group.startswith('collection_date'):
                orderby = 'collection_date desc'
        fields_list = list(fields or [])
        original_fields = list(fields or [])
        _special_measures = ('average_weight_elaborated_aggregated', 'pivot_row_distribution_percent')
        need_row_distrib_pct = self._read_group_requests_field(original_fields, 'pivot_row_distribution_percent')
        has_special_measure = (
            self._read_group_requests_field(original_fields, 'average_weight_elaborated_aggregated')
            or need_row_distrib_pct
        )
        fields_for_super = self._read_group_strip_field_specs(fields_list, _special_measures)
        # Remover medidas especiales de fields para calcularlas manualmente (evitar SQL agregando 0)
        if has_special_measure:
            if fields_for_super:
                result = super().read_group(domain, fields_for_super, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)
            else:
                result = super().read_group(domain, [], groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)
        else:
            result = super().read_group(domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)
        
        # Calcular average_weight_elaborated_aggregated usando promedio ponderado
        # IMPORTANTE: Siempre calcular desde los registros base, nunca desde valores agregados
        # Esto evita el problema de "promedio de promedios" en el Total general
        # Calculamos siempre, incluso si el campo no está en fields_list, porque Odoo puede necesitarlo para el Total
        if groupby:
            grand_eggs_holder = [None]

            def get_grand_total_eggs():
                if grand_eggs_holder[0] is None:
                    glines = self.search(list(domain or []))
                    grand_eggs_holder[0] = sum(glines.mapped('total_produced_reference')) or 0.0
                return grand_eggs_holder[0]

            # En modo lazy, el pivot hace llamadas jerárquicas y __domain puede no incluir
            # todas las dimensiones visuales a la vez. Preferimos usar el set configurado
            # en el contexto (pivot_row_groupby / pivot_column_groupby) para decidir qué
            # quitar del denominador, y usamos el dominio base del informe como “gran total”.
            for group in result:
                # Dominio del grupo: informe + slice del pivot (fecha, galpón, atributo, etc.)
                if group.get('__domain'):
                    group_domain = expression.AND([list(domain or []), list(group['__domain'])])
                else:
                    group_domain = list(domain or [])
                
                # Buscar los registros BASE en este grupo (no usar valores agregados)
                lines = self.search(group_domain)
                
                if lines:
                    # Calcular promedio ponderado desde los registros base:
                    # suma(weight_total_grams) / suma(eggs_with_weight)
                    # Esto asegura que cada grupo (incluido el Total) se calcule correctamente
                    total_weight = sum(lines.mapped('weight_total_grams'))
                    total_eggs = sum(lines.mapped('eggs_with_weight'))
                    
                    if total_eggs and total_eggs > 0:
                        calculated_avg = total_weight / total_eggs
                        # Sobrescribir el valor calculado automáticamente por Odoo
                        # Esto es crítico: siempre sobrescribir, incluso si Odoo ya calculó un valor
                        group['average_weight_elaborated_aggregated'] = calculated_avg
                        _logger.debug(f"read_group: Calculado promedio ponderado {calculated_avg} para grupo (peso_total={total_weight}, huevos={total_eggs}, registros={len(lines)})")
                    else:
                        group['average_weight_elaborated_aggregated'] = 0.0
                else:
                    group['average_weight_elaborated_aggregated'] = 0.0
                
                # % Distrib.: interior = celda/fila; total fila = columna/gran total; total columna = fila/gran total
                if need_row_distrib_pct:
                    if not lines:
                        group['pivot_row_distribution_percent'] = 0.0
                    else:
                        eggs_cell = sum(lines.mapped('total_produced_reference'))
                        axis, dim_field = self._choose_distribution_dimension(groupby)
                        # Si este grupo NO está acotado por la dimensión elegida, es un total sobre esa dimensión -> 100%
                        if dim_field and not self._domain_touches_field(group_domain, dim_field):
                            ratio = 1.0 if eggs_cell else 0.0
                        else:
                            denom_domain = self._domain_without_fields(group_domain, {dim_field} if dim_field else set())
                            eggs_denom = sum(self.search(denom_domain).mapped('total_produced_reference')) if denom_domain else 0.0
                            ratio = (eggs_cell / eggs_denom) if eggs_denom else 0.0
                        group['pivot_row_distribution_percent'] = min(max(ratio, 0.0), 1.0)
        
        return result
    
    def _sync_uom_values_to_legacy(self):
        """Sincroniza valores de uom_value_ids a campos legacy para mostrar en el tree"""
        for line in self:
            if not line.uom_value_ids:
                return
            
            # Ordenar por ratio descendente
            sorted_uoms = sorted(line.uom_value_ids, 
                               key=lambda x: x.uom_ratio or 0.0, 
                               reverse=True)
            
            # Mapear a los primeros 3 campos legacy
            if len(sorted_uoms) > 0:
                line.initial_box = sorted_uoms[0].initial_qty
                line.final_box = sorted_uoms[0].final_qty
            if len(sorted_uoms) > 1:
                line.initial_map = sorted_uoms[1].initial_qty
                line.final_map = sorted_uoms[1].final_qty
            if len(sorted_uoms) > 2:
                line.initial_egg = sorted_uoms[2].initial_qty
                line.final_egg = sorted_uoms[2].final_qty
    
    def _sync_legacy_to_uom_values(self):
        """Sincroniza valores de campos legacy a uom_value_ids al guardar"""
        for line in self:
            if not line.product_variant_id:
                continue
            
            # Obtener las unidades de medida configuradas
            uoms = self._get_poultry_uoms(line.product_variant_id)
            if not uoms:
                continue
            
            # Asegurar que existan los registros uom_value_ids
            line._ensure_uom_value_ids()
            
            # Ordenar por ratio descendente
            sorted_uoms = uoms[:3]  # Solo las primeras 3
            
            # Mapear desde campos legacy
            if len(sorted_uoms) > 0:
                uom_val = line.uom_value_ids.filtered(lambda x: x.uom_id.id == sorted_uoms[0].id)
                if uom_val:
                    uom_val.initial_qty = line.initial_box
                    uom_val.final_qty = line.final_box
            if len(sorted_uoms) > 1:
                uom_val = line.uom_value_ids.filtered(lambda x: x.uom_id.id == sorted_uoms[1].id)
                if uom_val:
                    uom_val.initial_qty = line.initial_map
                    uom_val.final_qty = line.final_map
            if len(sorted_uoms) > 2:
                uom_val = line.uom_value_ids.filtered(lambda x: x.uom_id.id == sorted_uoms[2].id)
                if uom_val:
                    uom_val.initial_qty = line.initial_egg
                    uom_val.final_qty = line.final_egg
    
    @api.onchange('initial_box', 'initial_map', 'initial_egg')
    def _onchange_initial_values(self):
        """Sincroniza valores iniciales a uom_value_ids cuando se editan en el tree"""
        self._sync_legacy_to_uom_values()
    
    @api.onchange('final_box', 'final_map', 'final_egg')
    def _onchange_final_values(self):
        """Sincroniza valores finales a uom_value_ids cuando se editan en el tree"""
        self._sync_legacy_to_uom_values()
    
    @api.onchange('product_variant_id')
    def _onchange_product_variant(self):
        """Cuando se cambia el producto, asegurar que existan los uom_value_ids"""
        if self.product_variant_id:
            self._ensure_uom_value_ids()
            self._sync_uom_values_to_legacy()
    
    def _ensure_uom_value_ids(self):
        """Asegura que existan los registros uom_value_ids para este producto"""
        for line in self:
            # Solo crear uom_value_ids si la línea ya tiene un ID (está guardada)
            if not line.id:
                continue
                
            if not line.product_variant_id:
                continue
            
            # Obtener las unidades de medida configuradas
            uoms = self._get_poultry_uoms(line.product_variant_id)
            if not uoms:
                # Si no hay unidades configuradas, no hacer nada
                continue
            
            # Obtener la unidad de referencia
            reference_uom = self._get_reference_uom(line.product_variant_id)
            if not reference_uom:
                # Si no hay unidad de referencia, no podemos calcular
                continue
            
            # Verificar qué uom_value_ids ya existen
            existing_uoms = line.uom_value_ids.mapped('uom_id')
            
            # Crear los que faltan (solo las primeras 3 unidades ordenadas por ratio)
            for uom in uoms[:3]:
                if uom not in existing_uoms:
                    self.env['poultry.egg.collection.line.uom'].create({
                        'line_id': line.id,
                        'uom_id': uom.id,
                        'initial_qty': 0.0,
                        'final_qty': 0.0,
                        'produced_qty': 0.0,
                    })
            
            # Recargar para obtener los nuevos registros
            line.invalidate_recordset(['uom_value_ids'])
    
    @api.depends('initial_box', 'initial_map', 'initial_egg',
                 'final_box', 'final_map', 'final_egg',
                 'uom_value_ids.initial_qty', 'uom_value_ids.final_qty',
                 'uom_value_ids.produced_qty', 'uom_value_ids.uom_ratio',
                 'product_variant_id')
    def _compute_production(self):
        """
        Calcula los valores producidos (Final - Inicial) usando el sistema dinámico de UoM.
        Si hay uom_value_ids, usa esos valores. Si no, usa el método legacy.
        """
        for line in self:
            # Asegurar que existan los uom_value_ids
            line._ensure_uom_value_ids()
            
            # Obtener la unidad de referencia
            reference_uom = self._get_reference_uom(line.product_variant_id)
            if not reference_uom:
                # Fallback a método legacy si no hay unidad de referencia
                line.produced_box = line.final_box - line.initial_box
                line.produced_map = line.final_map - line.initial_map
                line.produced_egg = line.final_egg - line.initial_egg
                line.total_produced_reference = 0.0
                continue
            
            # Usar el sistema dinámico si hay uom_value_ids
            if line.uom_value_ids:
                # Calcular produced_qty para cada uom_value
                uom_values_to_write = {}
                total_produced_ref = 0.0
                
                for uom_val in line.uom_value_ids:
                    # Calcular produced_qty = final_qty - initial_qty
                    produced_qty = (uom_val.final_qty or 0.0) - (uom_val.initial_qty or 0.0)
                    uom_val.produced_qty = produced_qty
                    
                    # Calcular el total en unidad de referencia
                    ratio = uom_val.uom_ratio or 0.0
                    total_produced_ref += produced_qty * ratio
                    
                    uom_values_to_write[uom_val.id] = produced_qty
                
                # Distribuir el total producido entre las unidades de medida
                # Primero, calcular cuánto se produjo en total (en unidad de referencia)
                remaining_produced = total_produced_ref
                
                # Ordenar uom_values por ratio descendente (excluyendo la unidad de referencia)
                sorted_uom_values = sorted(
                    [uv for uv in line.uom_value_ids if uv.uom_id.id != reference_uom.id],
                    key=lambda x: x.uom_ratio or 0.0,
                    reverse=True
                )
                
                # Distribuir primero a las unidades mayores (excluyendo referencia)
                for uom_val in sorted_uom_values:
                    ratio = uom_val.uom_ratio or 1.0
                    if ratio > 0:
                        # Calcular cuántas unidades completas de esta medida se pueden hacer
                        produced_units = math.floor(remaining_produced / ratio)
                        uom_values_to_write[uom_val.id] = produced_units
                        # Restar lo que ya se asignó
                        remaining_produced -= (produced_units * ratio)
                    else:
                        uom_values_to_write[uom_val.id] = 0.0
                
                # Asignar el resto a la unidad de referencia (siempre debe quedar algo o 0)
                ref_uom_val = line.uom_value_ids.filtered(
                    lambda x: x.uom_id.id == reference_uom.id
                )
                if ref_uom_val:
                    # El resto siempre va a la unidad de referencia
                    uom_values_to_write[ref_uom_val.id] = remaining_produced
                
                # Escribir los valores calculados usando sudo para evitar problemas de permisos
                # y hacerlo fuera del contexto del computed
                uom_records = self.env['poultry.egg.collection.line.uom'].browse(uom_values_to_write.keys())
                for uom_record in uom_records:
                    if uom_record.id in uom_values_to_write:
                        uom_record.sudo().write({
                            'produced_qty': uom_values_to_write[uom_record.id]
                        })
                
                # Mantener compatibilidad con campos legacy (mapear a los primeros 3)
                uom_list = sorted(line.uom_value_ids, 
                                 key=lambda x: x.uom_ratio or 0.0, 
                                 reverse=True)
                
                if len(uom_list) > 0:
                    line.produced_box = uom_list[0].produced_qty
                else:
                    line.produced_box = 0.0
                    
                if len(uom_list) > 1:
                    line.produced_map = uom_list[1].produced_qty
                else:
                    line.produced_map = 0.0
                    
                if len(uom_list) > 2:
                    line.produced_egg = uom_list[2].produced_qty
                else:
                    # Si hay unidad de referencia, usar su valor
                    ref_uom_val = line.uom_value_ids.filtered(
                        lambda x: x.uom_id.id == reference_uom.id
                    )
                    line.produced_egg = ref_uom_val.produced_qty if ref_uom_val else 0.0
            else:
                # Fallback a método legacy
                line.produced_box = line.final_box - line.initial_box
                line.produced_map = line.final_map - line.initial_map
                line.produced_egg = line.final_egg - line.initial_egg
                line.total_produced_reference = 0.0
            
            # Calcular total_produced_reference
            if line.uom_value_ids:
                total_ref = 0.0
                for uom_val in line.uom_value_ids:
                    produced = uom_val.produced_qty or 0.0
                    ratio = uom_val.uom_ratio or 0.0
                    total_ref += produced * ratio
                line.total_produced_reference = total_ref
            else:
                # Método legacy
                box_ratio = line.uom_box_id.ratio if line.uom_box_id else 0.0
                map_ratio = line.uom_map_id.ratio if line.uom_map_id else 0.0
                egg_ratio = line.uom_egg_id.ratio if line.uom_egg_id else 0.0
                
                line.total_produced_reference = (
                    (line.produced_box or 0.0) * box_ratio +
                    (line.produced_map or 0.0) * map_ratio +
                    (line.produced_egg or 0.0) * egg_ratio
                )
    
    @api.model_create_multi
    def create(self, vals_list):
        """Crea las líneas y luego asegura que existan los uom_value_ids"""
        lines = super().create(vals_list)
        # Después de crear, asegurar que existan los uom_value_ids
        for line in lines:
            if line.product_variant_id:
                line._ensure_uom_value_ids()
        return lines
    
    def write(self, vals):
        """Actualiza las líneas y asegura que existan los uom_value_ids si cambió el producto o los valores legacy"""
        result = super().write(vals)
        
        # Campos legacy que requieren sincronización
        legacy_fields = ['product_variant_id', 'initial_box', 'initial_map', 'initial_egg', 
                         'final_box', 'final_map', 'final_egg']
        
        # Si cambió alguno de estos campos, sincronizar
        if any(field in vals for field in legacy_fields):
            for line in self:
                if line.product_variant_id:
                    # Asegurar que existan los uom_value_ids
                    line._ensure_uom_value_ids()
                    # Sincronizar valores legacy a uom_value_ids
                    line._sync_legacy_to_uom_values()
        
        return result
    
    # Campos permitidos para agrupar en la tabla dinámica (pivot)
    PIVOT_GROUPABLE_FIELDS = {
        'collection_date',      # Fecha de Recolección
        'collection_coop_id',   # Galpón
        'collection_id',        # Recolección
        'attribute_value_id',   # Valor del Atributo
        'product_variant_id',   # Producto (variante)
    }

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        res = super().fields_get(allfields=allfields, attributes=attributes)
        if 'attribute_value_name' in res:
            ctx = self.env.context or {}
            collection_id = ctx.get('default_collection_id')
            if not collection_id and ctx.get('active_model') == 'poultry.egg.collection':
                collection_id = ctx.get('active_id')
            res['attribute_value_name']['string'] = self._get_attribute_column_label(collection_id=collection_id)
        # Ocultar del dropdown de la tabla dinámica los campos no deseados
        for fname in res:
            if fname not in self.PIVOT_GROUPABLE_FIELDS:
                res[fname]['selectable'] = False
                res[fname]['sortable'] = False
                res[fname]['groupable'] = False
        return res

    _sql_constraints = [
        ('unique_collection_variant', 'unique(collection_id, product_variant_id)',
         'Ya existe una línea para esta variante en esta recolección.'),
    ]
