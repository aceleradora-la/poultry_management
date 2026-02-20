# -*- coding: utf-8 -*-

from odoo import models, fields, api
import math
import logging

_logger = logging.getLogger(__name__)


class PoultryEggCollectionLine(models.Model):
    _name = 'poultry.egg.collection.line'
    _description = 'Línea de Recolección de Producción de Huevos'
    _order = 'collection_id, product_variant_id'

    collection_id = fields.Many2one('poultry.egg.collection', string='Recolección', 
                                     required=True, ondelete='cascade', index=True)
    product_variant_id = fields.Many2one('product.product', string='Variante del Producto', 
                                          required=True, domain="[('type', '=', 'product')]")
    product_variant_name = fields.Char(string='Producto', related='product_variant_id.name', 
                                        readonly=True, store=True)
    
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
    
    # % de distribución basado en peso
    weight_distribution_percent = fields.Float(string='% Distribución', 
                                                compute='_compute_weight_distribution',
                                                store=True, digits=(16, 2),
                                                help='Porcentaje de distribución según el peso total')
    
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
            variant = line.product_variant_id
            # product_template_attribute_value_ids contiene los valores que definen esta variante
            ptavs = getattr(variant, 'product_template_attribute_value_ids', None)
            if not ptavs:
                line.attribute_value_id = False
                continue
            # Buscar atributo Calibre (o el primero si no existe)
            calibre_attr = self.env['product.attribute'].search([('name', 'ilike', 'Calibre')], limit=1)
            if calibre_attr:
                ptav = ptavs.filtered(
                    lambda p: p.product_attribute_value_id.attribute_id == calibre_attr
                )
                if ptav:
                    line.attribute_value_id = ptav[0].product_attribute_value_id
                else:
                    line.attribute_value_id = ptavs[0].product_attribute_value_id
            else:
                line.attribute_value_id = ptavs[0].product_attribute_value_id
    
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
        """
        fields_list = fields or []
        # Remover average_weight_elaborated_aggregated de fields para calcularlo manualmente
        # Esto evita que Odoo use el valor almacenado (que es un promedio simple) y lo agregue incorrectamente
        if 'average_weight_elaborated_aggregated' in fields_list:
            fields_without_avg = [f for f in fields_list if f != 'average_weight_elaborated_aggregated']
            if fields_without_avg:
                result = super().read_group(domain, fields_without_avg, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)
            else:
                # Si solo está average_weight_elaborated_aggregated, llamar sin fields para obtener la estructura
                result = super().read_group(domain, [], groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)
        else:
            result = super().read_group(domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)
        
        # Calcular average_weight_elaborated_aggregated usando promedio ponderado
        # IMPORTANTE: Siempre calcular desde los registros base, nunca desde valores agregados
        # Esto evita el problema de "promedio de promedios" en el Total general
        # Calculamos siempre, incluso si el campo no está en fields_list, porque Odoo puede necesitarlo para el Total
        if groupby:
            for group in result:
                # Obtener el dominio para este grupo
                group_domain = list(domain)
                if group.get('__domain'):
                    group_domain.extend(group['__domain'])
                
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
        'product_variant_name', # Producto
        'product_variant_id',   # Variante del Producto
    }

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        res = super().fields_get(allfields=allfields, attributes=attributes)
        # Ocultar del dropdown de la tabla dinámica los campos no deseados
        for fname in res:
            if fname not in self.PIVOT_GROUPABLE_FIELDS:
                res[fname]['selectable'] = False
        return res

    _sql_constraints = [
        ('unique_collection_variant', 'unique(collection_id, product_variant_id)',
         'Ya existe una línea para esta variante en esta recolección.'),
    ]
