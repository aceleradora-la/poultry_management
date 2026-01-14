# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class PoultryEggCollection(models.Model):
    _name = 'poultry.egg.collection'
    _description = 'Recolección de Producción de Huevos'
    _order = 'date desc, coop_id'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        """Solo permite eliminar partes de producción en estado Inicio (Borrador)"""
        for record in self:
            if record.state != 'draft':
                raise UserError('Solo se pueden eliminar partes de producción en estado Inicio (Borrador).')
    
    @api.model
    def _read_group_groupby(self, groupby_spec, query):
        """Override para evitar errores cuando se usa product_tmpl_id o product_id en pivot"""
        # Si el groupby es product_tmpl_id o product_id, redirigir a product_variant_id
        # Manejar tanto string simple como formato con intervalo (ej: 'product_tmpl_id:day')
        if isinstance(groupby_spec, str):
            if groupby_spec.startswith('product_tmpl_id') or groupby_spec.startswith('product_id'):
                # Si tiene formato con intervalo, mantenerlo pero cambiar el campo
                if ':' in groupby_spec:
                    interval = groupby_spec.split(':', 1)[1]
                    groupby_spec = f'product_variant_id:{interval}'
                else:
                    groupby_spec = 'product_variant_id'
        return super()._read_group_groupby(groupby_spec, query)

    name = fields.Char(string='Referencia', required=True, copy=False, index=True,
                       default='NUEVA', readonly=False,
                       help='Se genera automáticamente al seleccionar el galpón')
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True, 
                               domain="[('active', '=', True)]", tracking=True)
    product_tmpl_id = fields.Many2one('product.template', string='Producto Base', required=True,
                                      domain=[('type', '=', 'product'), ('active', '=', True), ('is_egg_production', '=', True)],
                                      help='Producto base para la recolección. Se mostrarán todas las variantes de este producto en las líneas.', tracking=True)
    
    product_tmpl_name = fields.Char(string='Nombre Producto Template', 
                                    compute='_compute_product_tmpl_name', 
                                    store=True, readonly=True, index=True,
                                    help='Nombre del producto base (almacenado para uso en reportes)')
    
    product_id = fields.Many2one('product.product', string='Producto', 
                                 related='product_tmpl_id.product_variant_id',
                                 readonly=True, store=False,
                                 help='Primera variante del producto base (solo lectura)')
    
    # Campo Many2one almacenado para uso en pivot (similar a mrp.production)
    product_variant_id = fields.Many2one('product.product', string='Variante Producto',
                                        compute='_compute_product_variant_id',
                                        store=True, readonly=True, index=True,
                                        help='Primera variante del producto (almacenado para uso en pivot)')
    
    product_variant_name = fields.Char(string='Nombre Variante Producto', 
                                      compute='_compute_product_variant_name', 
                                      store=True, readonly=True, index=True,
                                      help='Nombre de la variante del producto (almacenado para uso en reportes)')
    date = fields.Date(string='Fecha de Recolección', required=True, default=fields.Date.today, tracking=True)
    operator_id = fields.Many2one('hr.employee', string='Operador', 
                                  domain="[('active', '=', True)]",
                                  help='Empleado responsable de la recolección', tracking=True)
    state = fields.Selection([
        ('draft', 'Inicio'),
        ('counted', 'Bruto'),
        ('completed', 'Completada'),
        ('done', 'Procesada'),
    ], string='Estado', default='draft', tracking=True)
    
    # Líneas de recolección
    line_ids = fields.One2many('poultry.egg.collection.line', 'collection_id', 
                                string='Líneas de Recolección')
    
    # Órdenes de fabricación generadas
    production_ids = fields.One2many('mrp.production', 'egg_collection_id', 
                                      string='Órdenes de Fabricación Generadas')
    production_count = fields.Integer(string='Cantidad de OF', compute='_compute_production_count')
    
    
    # Totales Finales (nuevos)
    total_eggs = fields.Float(string='Total Huevos', compute='_compute_final_totals', store=True,
                              help='Suma de huevos producidos de todas las variantes')
    total_weight = fields.Float(string='Total Peso (kg)', compute='_compute_final_totals', store=True,
                                help='Suma del Peso de todas las variantes que contengan Peso Medio')
    total_boxes = fields.Float(string='Total Cajones', compute='_compute_final_totals', store=True,
                               help='Total Huevos / 360')
    average_weight_elaborated = fields.Float(string='Peso Medio Elaborado (g)', 
                                              compute='_compute_final_totals', store=True,
                                              help='Peso medio elaborado en gramos: Total de Gramos / Total de Huevos Finales (solo variantes con Peso Medio)')
    
    notes = fields.Text(string='Notas')
    
    @api.depends('product_tmpl_id')
    def _compute_product_tmpl_name(self):
        """Calcula el nombre del producto template para uso en reportes (valor traducido)"""
        for collection in self:
            if collection.product_tmpl_id:
                # Obtener el nombre traducido usando with_context para el idioma del usuario
                # Esto asegura que obtenemos el valor traducido, no el JSON
                lang = self.env.user.lang or self.env.context.get('lang') or 'en_US'
                product = collection.product_tmpl_id.with_context(lang=lang)
                # Acceder al campo name que ya está traducido por el contexto
                collection.product_tmpl_name = product.name or ''
            else:
                collection.product_tmpl_name = False
    
    @api.depends('product_tmpl_id', 'line_ids', 'line_ids.product_variant_id')
    def _compute_product_variant_id(self):
        """Calcula y almacena la primera variante del producto para uso en pivot"""
        for collection in self:
            variant = False
            # Prioridad 1: Usar la primera línea si existe (tiene la variante real)
            if collection.line_ids and collection.line_ids[0].product_variant_id:
                variant = collection.line_ids[0].product_variant_id
            # Prioridad 2: Si no hay líneas, obtener la primera variante del template
            elif collection.product_tmpl_id:
                # Buscar directamente en la base de datos para evitar campos related no almacenados
                variants = self.env['product.product'].search([
                    ('product_tmpl_id', '=', collection.product_tmpl_id.id)
                ], limit=1, order='id')
                if variants:
                    variant = variants[0]
            collection.product_variant_id = variant.id if variant else False
    
    @api.depends('product_variant_id')
    def _compute_product_variant_name(self):
        """Calcula el nombre de la variante del producto para uso en reportes (valor traducido)"""
        for collection in self:
            if collection.product_variant_id:
                lang = self.env.user.lang or self.env.context.get('lang') or 'en_US'
                variant = collection.product_variant_id.with_context(lang=lang)
                # Usar display_name que incluye los atributos de variante si existen
                # display_name es un campo computed que ya maneja las traducciones
                variant_name = variant.display_name
                
                # Si display_name no está disponible, usar name directamente
                if not variant_name:
                    variant_name = variant.name
                
                # Si es un dict (JSON de traducción), extraer el valor del idioma
                if isinstance(variant_name, dict):
                    variant_name = variant_name.get(lang) or variant_name.get('en_US') or ''
                
                collection.product_variant_name = variant_name or ''
            else:
                collection.product_variant_name = False
    
    @api.depends('line_ids', 'line_ids.initial_box', 'line_ids.initial_map', 'line_ids.initial_egg',
                 'line_ids.final_box', 'line_ids.final_map', 'line_ids.final_egg',
                 'line_ids.produced_box', 'line_ids.produced_map', 'line_ids.produced_egg',
                 'line_ids.uom_value_ids', 'line_ids.uom_value_ids.produced_qty',
                 'line_ids.uom_value_ids.initial_qty', 'line_ids.uom_value_ids.final_qty')
    def _compute_totals(self):
        """Calcula los totales de todas las líneas"""
        for collection in self:
            # Asegurar que los campos computed de las líneas estén calculados
            if collection.line_ids:
                collection.line_ids._compute_production()
            
            # Usar el nuevo sistema dinámico si hay uom_value_ids, sino usar legacy
            use_dynamic = any(line.uom_value_ids for line in collection.line_ids)
            
            if use_dynamic:
                # Calcular totales desde uom_value_ids
                # Agrupar por posición (primera, segunda, tercera unidad ordenada por ratio)
                total_initial_uom1 = 0.0
                total_initial_uom2 = 0.0
                total_initial_uom3 = 0.0
                total_final_uom1 = 0.0
                total_final_uom2 = 0.0
                total_final_uom3 = 0.0
                total_produced_uom1 = 0.0
                total_produced_uom2 = 0.0
                total_produced_uom3 = 0.0
                
                for line in collection.line_ids:
                    if line.uom_value_ids:
                        # Ordenar por ratio descendente
                        sorted_uoms = sorted(line.uom_value_ids, 
                                           key=lambda x: x.uom_ratio or 0.0, 
                                           reverse=True)
                        
                        if len(sorted_uoms) > 0:
                            total_initial_uom1 += sorted_uoms[0].initial_qty
                            total_final_uom1 += sorted_uoms[0].final_qty
                            total_produced_uom1 += sorted_uoms[0].produced_qty
                        if len(sorted_uoms) > 1:
                            total_initial_uom2 += sorted_uoms[1].initial_qty
                            total_final_uom2 += sorted_uoms[1].final_qty
                            total_produced_uom2 += sorted_uoms[1].produced_qty
                        if len(sorted_uoms) > 2:
                            total_initial_uom3 += sorted_uoms[2].initial_qty
                            total_final_uom3 += sorted_uoms[2].final_qty
                            total_produced_uom3 += sorted_uoms[2].produced_qty
                
                collection.total_initial_boxes = total_initial_uom1
                collection.total_initial_maps = total_initial_uom2
                collection.total_initial_eggs = total_initial_uom3
                collection.total_final_boxes = total_final_uom1
                collection.total_final_maps = total_final_uom2
                collection.total_final_eggs = total_final_uom3
                collection.total_produced_boxes = total_produced_uom1
                collection.total_produced_maps = total_produced_uom2
                collection.total_produced_eggs = total_produced_uom3
            else:
                # Método legacy: usar campos legacy
                collection.total_initial_boxes = sum(collection.line_ids.mapped('initial_box') or [0.0])
                collection.total_initial_maps = sum(collection.line_ids.mapped('initial_map') or [0.0])
                collection.total_initial_eggs = sum(collection.line_ids.mapped('initial_egg') or [0.0])
                collection.total_final_boxes = sum(collection.line_ids.mapped('final_box') or [0.0])
                collection.total_final_maps = sum(collection.line_ids.mapped('final_map') or [0.0])
                collection.total_final_eggs = sum(collection.line_ids.mapped('final_egg') or [0.0])
                collection.total_produced_boxes = sum(collection.line_ids.mapped('produced_box') or [0.0])
                collection.total_produced_maps = sum(collection.line_ids.mapped('produced_map') or [0.0])
                collection.total_produced_eggs = sum(collection.line_ids.mapped('produced_egg') or [0.0])
    
    @api.depends('line_ids', 'line_ids.total_produced_reference',
                 'line_ids.average_weight')
    def _compute_final_totals(self):
        """Calcula los totales finales: Total Huevos, Total Peso, Total Cajones, Peso Medio Elaborado"""
        for collection in self:
            # Total Huevos: suma de total_produced_reference de todas las variantes
            collection.total_eggs = sum(collection.line_ids.mapped('total_produced_reference') or [0.0])
            
            # Total Peso: suma de (peso medio * huevos) de todas las variantes que tengan peso medio, en KILOGRAMOS
            total_weight_grams = 0.0
            total_eggs_with_weight = 0.0  # Suma de huevos finales solo de variantes con peso medio
            
            for line in collection.line_ids:
                if line.average_weight and line.total_produced_reference:
                    total_weight_grams += line.average_weight * line.total_produced_reference
                    total_eggs_with_weight += line.total_produced_reference
            
            # Convertir gramos a kilogramos
            collection.total_weight = total_weight_grams / 1000.0
            
            # Peso Medio Elaborado: Total de Gramos / Total de Huevos Finales (solo variantes con Peso Medio)
            if total_eggs_with_weight > 0:
                collection.average_weight_elaborated = total_weight_grams / total_eggs_with_weight
            else:
                collection.average_weight_elaborated = 0.0
            
            # Total Cajones: Total Huevos / 360
            if collection.total_eggs > 0:
                collection.total_boxes = collection.total_eggs / 360.0
            else:
                collection.total_boxes = 0.0
    
    @api.depends('production_ids')
    def _compute_production_count(self):
        """Cuenta las órdenes de fabricación generadas"""
        for collection in self:
            collection.production_count = len(collection.production_ids)
    
    @api.model
    def _get_sequence_for_coop(self, coop_id):
        """
        Obtiene o crea una secuencia para el galpón basándose en su prefijo.
        Si el galpón tiene un prefijo personalizado, busca o crea una secuencia con ese prefijo.
        """
        if not coop_id:
            # Si no hay galpón, usar la secuencia por defecto
            return self.env['ir.sequence'].search([('code', '=', 'poultry.egg.collection')], limit=1)
        
        coop = self.env['poultry.coop'].browse(coop_id)
        if not coop.exists():
            return self.env['ir.sequence'].search([('code', '=', 'poultry.egg.collection')], limit=1)
        
        # Obtener el prefijo del galpón (limpiar espacios y convertir a mayúsculas)
        prefix = (coop.sequence_prefix or 'REC').strip().upper()
        if not prefix:
            prefix = 'REC'
        
        # Buscar o crear una secuencia con el código basado en el prefijo
        sequence_code = f'poultry.egg.collection.{prefix}'
        sequence = self.env['ir.sequence'].search([('code', '=', sequence_code)], limit=1)
        
        if not sequence:
            # Crear una nueva secuencia para este prefijo
            sequence = self.env['ir.sequence'].create({
                'name': f'Secuencia de Recolección - {prefix}',
                'code': sequence_code,
                'prefix': f'{prefix}-',
                'padding': 4,
                'number_increment': 1,
                'number_next': 1,
            })
        
        return sequence
    
    @api.model_create_multi
    def create(self, vals_list):
        """Genera referencia automática usando secuencia numérica basada en el prefijo del galpón"""
        # Si vals_list es un diccionario único (compatibilidad), convertirlo a lista
        if isinstance(vals_list, dict):
            vals_list = [vals_list]
        
        # Procesar cada conjunto de valores
        for vals in vals_list:
            # Siempre generar el nombre si no se proporciona o si es el valor por defecto
            if not vals.get('name') or vals.get('name') == 'NUEVA':
                # Obtener la secuencia basada en el galpón
                coop_id = vals.get('coop_id')
                sequence = self._get_sequence_for_coop(coop_id)
                if sequence:
                    vals['name'] = sequence.next_by_id() or 'NUEVA'
                else:
                    # Fallback a secuencia por defecto
                    vals['name'] = self.env['ir.sequence'].next_by_code('poultry.egg.collection') or 'NUEVA'
        
        # Crear todos los registros
        records = super().create(vals_list)
        
        # Procesar cada registro creado
        for record in records:
            # Si el nombre sigue siendo 'NUEVA' o vacío después de crear, regenerarlo
            if record.name == 'NUEVA' or not record.name:
                coop_id = record.coop_id.id if record.coop_id else None
                sequence = self._get_sequence_for_coop(coop_id)
                if sequence:
                    record.name = sequence.next_by_id() or 'NUEVA'
            
            # Forzar recálculo de product_variant_name después de crear
            if record.product_tmpl_id:
                record._compute_product_variant_name()
        
        return records
    
    @api.onchange('coop_id')
    def _onchange_coop_id(self):
        """Al cambiar el galpón, regenerar el nombre automáticamente"""
        if self.coop_id:
            sequence = self._get_sequence_for_coop(self.coop_id.id)
            if sequence:
                # Generar nuevo nombre basado en el prefijo del galpón
                self.name = sequence.next_by_id() or 'NUEVA'
            else:
                # Fallback a secuencia por defecto
                self.name = self.env['ir.sequence'].next_by_code('poultry.egg.collection') or 'NUEVA'
    
    @api.model
    def renumber_existing_collections(self):
        """
        Renumera todos los registros existentes usando la secuencia numérica basada en el prefijo del galpón.
        Se ejecuta automáticamente al actualizar el módulo o se puede llamar manualmente.
        """
        # Obtener todos los registros ordenados por fecha de creación
        collections = self.search([], order='create_date asc, id asc')
        count = 0
        
        for collection in collections:
            if not collection.coop_id:
                continue
            
            # Obtener la secuencia basada en el prefijo del galpón
            sequence = collection._get_sequence_for_coop(collection.coop_id.id)
            if not sequence:
                continue
            
            # Generar nuevo número de secuencia
            new_name = sequence.next_by_id() or f'{collection.coop_id.sequence_prefix or "REC"}-{collection.id:04d}'
            
            # Actualizar solo si el nombre actual no sigue el formato correcto
            # o si es un nombre genérico
            current_name = collection.name or ''
            prefix = (collection.coop_id.sequence_prefix or 'REC').strip().upper()
            expected_prefix = f'{prefix}-'
            
            if (not current_name.startswith(expected_prefix) or 
                current_name == 'Nueva Recolección' or 
                current_name == 'NUEVA' or
                len(current_name) < len(expected_prefix) + 4):  # Prefijo + 4 dígitos mínimo
                collection.write({'name': new_name})
                count += 1
                _logger.info(f"Renumerado: {collection.id} -> {new_name}")
        
        _logger.info(f"Renumeración completada: {count} registros actualizados")
        return True
    
    def write(self, vals):
        """Actualiza product_variant_name cuando cambia product_tmpl_id"""
        result = super().write(vals)
        if 'product_tmpl_id' in vals:
            self._compute_product_variant_name()
        return result
    
    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        """Al cambiar la plantilla del producto, actualiza las líneas con las variantes"""
        if self.product_tmpl_id:
            # Usar el método estándar de Odoo para obtener todas las variantes de la plantilla
            # Esto incluye todas las variantes, activas e inactivas
            variants = self.product_tmpl_id.product_variant_ids
            
            # Si no hay variantes, usar el producto base (product_variant_id) como recordset
            if not variants:
                if self.product_tmpl_id.product_variant_id:
                    variants = self.product_tmpl_id.product_variant_id
            
            # Limpiar líneas existentes y crear nuevas
            lines = []
            for variant in variants:
                lines.append((0, 0, {
                    'product_variant_id': variant.id,
                }))
            
            # Reemplazar todas las líneas existentes con las nuevas
            self.line_ids = [(5, 0, 0)]  # Eliminar todas las líneas
            if lines:
                self.line_ids = lines
    
    def action_count_initial(self):
        """Cambia el estado a 'counted' cuando se registra la cantidad inicial"""
        for record in self:
            if not record.line_ids:
                raise UserError('Debe agregar al menos una línea de recolección.')
            if not any(line.initial_box or line.initial_map or line.initial_egg for line in record.line_ids):
                raise UserError('Debe ingresar al menos una cantidad inicial.')
            record.state = 'counted'
    
    def action_complete(self):
        """Cambia el estado a 'completed' cuando se registra la cantidad final"""
        for record in self:
            if record.state != 'counted':
                raise UserError('Debe registrar primero la cantidad inicial.')
            # Verificar si hay valores finales (nuevo sistema o legacy)
            has_final_values = False
            for line in record.line_ids:
                if line.uom_value_ids:
                    if any(uom_val.final_qty > 0 for uom_val in line.uom_value_ids):
                        has_final_values = True
                        break
                else:
                    if line.final_box or line.final_map or line.final_egg:
                        has_final_values = True
                        break
            
            if not has_final_values:
                raise UserError('Debe ingresar al menos una cantidad final.')
            
            # Asegurar que todos los valores estén sincronizados antes de calcular
            # Forzar la sincronización de campos legacy a uom_value_ids
            for line in record.line_ids:
                if line.uom_value_ids:
                    # Forzar la sincronización inverse para asegurar que los valores estén guardados
                    line._sync_legacy_to_uom_values()
            
            # Calcular producción para todas las líneas
            # Forzar el cálculo accediendo a los campos computed para que se almacenen
            for line in record.line_ids:
                line._compute_production()
                # Acceder a los campos computed para forzar su almacenamiento
                _ = line.produced_box
                _ = line.produced_map
                _ = line.produced_egg
                _ = line.total_produced_reference
            record.state = 'completed'
    
    def action_set_to_draft(self):
        """Permite retroceder al estado anterior si aún no se han generado las órdenes de fabricación"""
        for record in self:
            if record.state == 'done':
                raise UserError('No se puede retroceder una recolección que ya ha sido procesada.')
            if record.production_ids:
                raise UserError('No se puede retroceder una recolección que ya tiene órdenes de fabricación generadas.')
            
            # Retroceder al estado anterior
            if record.state == 'completed':
                record.state = 'counted'  # Volver a Bruto
            elif record.state == 'counted':
                record.state = 'draft'  # Volver a Inicio
    
    def action_generate_productions(self):
        """Genera automáticamente las Órdenes de Fabricación para todas las unidades producidas"""
        self.ensure_one()
        if self.state != 'completed':
            raise UserError('Debe completar la recolección antes de generar las Órdenes de Fabricación.')
        
        if self.production_ids:
            raise UserError('Ya se han generado las Órdenes de Fabricación para esta recolección.')
        
        productions_created = []
        
        # Usar el nuevo sistema dinámico si hay uom_value_ids, sino usar legacy
        use_dynamic = any(line.uom_value_ids for line in self.line_ids)
        
        # Buscar la BOM una vez para todas las líneas (usar el producto base)
        base_product = self.product_tmpl_id
        if not base_product:
            raise UserError('No se ha seleccionado un producto base para esta recolección.')
        
        # Buscar la BOM del producto base (puede ser por plantilla o por variante)
        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', base_product.id),
            ('product_id', '=', False),
            ('type', '=', 'normal'),
        ], limit=1)
        
        if not bom:
            # Intentar con la primera variante del producto base
            first_variant = base_product.product_variant_ids[:1]
            if first_variant:
                bom = self.env['mrp.bom'].search([
                    ('product_id', '=', first_variant.id),
                    ('type', '=', 'normal'),
                ], limit=1)
        
        if not bom:
            raise UserError(f'No se encontró una Lista de Materiales (BOM) para el producto base {base_product.name}. '
                          'Debe crear una BOM antes de generar las órdenes.')
        
        # Preparar picking_type_id para productos terminados
        picking_type_id_finished = self.coop_id.picking_type_id_finished.id if self.coop_id.picking_type_id_finished else False
        
        for line in self.line_ids:
            product = line.product_variant_id
            if not product:
                continue
            
            if use_dynamic and line.uom_value_ids:
                # Usar el nuevo sistema: generar órdenes para cada unidad con produced_qty > 0
                for uom_val in line.uom_value_ids:
                    if uom_val.produced_qty > 0:
                        # Usar la BOM del producto base (ya encontrada arriba)
                        production_vals = {
                            'product_id': product.id,
                            'product_qty': uom_val.produced_qty,
                            'product_uom_id': uom_val.uom_id.id,
                            'bom_id': bom.id,
                            'coop_id': self.coop_id.id,
                            'egg_collection_id': self.id,
                            'origin': self.name,
                        }
                        if picking_type_id_finished:
                            production_vals['picking_type_id'] = picking_type_id_finished
                        
                        production = self.env['mrp.production'].create(production_vals)
                        production.action_confirm()
                        # Establecer qty_producing igual a product_qty
                        production.qty_producing = production.product_qty
                        # Establecer cantidades consumidas y cerrar la orden
                        self._force_close_production_order(production)
                        productions_created.append(production.id)
            else:
                # Método legacy: solo generar para cajones
                box_uom = self._get_uom_box()
                if not box_uom:
                    raise UserError('No se encontró la unidad de medida "Cajón". '
                                  'Debe crear esta unidad de medida antes de generar las órdenes.')
                
                if line.produced_box > 0:
                    production_vals = {
                        'product_id': product.id,
                        'product_qty': line.produced_box,
                        'product_uom_id': box_uom.id,
                        'bom_id': bom.id,
                        'coop_id': self.coop_id.id,
                        'egg_collection_id': self.id,
                        'origin': self.name,
                    }
                    if picking_type_id_finished:
                        production_vals['picking_type_id'] = picking_type_id_finished
                    
                    production = self.env['mrp.production'].create(production_vals)
                    production.action_confirm()
                    # Establecer qty_producing igual a product_qty
                    production.qty_producing = production.product_qty
                    # Establecer cantidades consumidas y cerrar la orden
                    self._force_close_production_order(production)
                    productions_created.append(production.id)
        
        # Crear orden de producción para Huevo sin Clasificar
        if self.coop_id.unclassified_egg_product_id and self.coop_id.unclassified_egg_bom_id:
            # Preparar picking_type_id para huevo sin clasificar
            picking_type_id_unclassified = self.coop_id.picking_type_id_unclassified.id if self.coop_id.picking_type_id_unclassified else False
            
            # Calcular total de huevos producidos (sumar todos los total_produced_reference)
            total_eggs = 0.0
            for line in self.line_ids:
                # Asegurar que total_produced_reference esté calculado
                if hasattr(line, 'total_produced_reference'):
                    total_eggs += line.total_produced_reference or 0.0
            
            if total_eggs > 0:
                # Obtener la unidad de medida del producto de huevo sin clasificar
                unclassified_product = self.coop_id.unclassified_egg_product_id
                unclassified_uom = unclassified_product.uom_id
                
                if not unclassified_uom:
                    raise UserError('El producto de huevo sin clasificar no tiene unidad de medida configurada.')
                
                # Crear la orden de producción para huevo sin clasificar
                unclassified_production_vals = {
                    'product_id': unclassified_product.id,
                    'product_qty': total_eggs,
                    'product_uom_id': unclassified_uom.id,
                    'bom_id': self.coop_id.unclassified_egg_bom_id.id,
                    'coop_id': self.coop_id.id,
                    'egg_collection_id': self.id,
                    'origin': f'{self.name} - Huevo sin Clasificar',
                }
                if picking_type_id_unclassified:
                    unclassified_production_vals['picking_type_id'] = picking_type_id_unclassified
                
                unclassified_production = self.env['mrp.production'].create(unclassified_production_vals)
                unclassified_production.action_confirm()
                # Establecer qty_producing igual a product_qty
                unclassified_production.qty_producing = unclassified_production.product_qty
                productions_created.append(unclassified_production.id)
        
        if productions_created:
            self.state = 'done'
            return {
                'name': 'Órdenes de Fabricación Generadas',
                'type': 'ir.actions.act_window',
                'res_model': 'mrp.production',
                'view_mode': 'list,form',
                'domain': [('id', 'in', productions_created)],
                'context': {'create': False},
            }
        else:
            raise UserError('No hay producción para generar órdenes de fabricación.')
    
    def _force_close_production_order(self, production):
        """
        Fuerza el cierre de una orden de producción estableciendo las cantidades consumidas
        incluso si no hay stock disponible. Crea move_line_ids manualmente si es necesario.
        """
        # Establecer cantidades consumidas según la BOM (cantidad estimada)
        for move in production.move_raw_ids:
            # Intentar asignar stock primero
            if move.state not in ('assigned', 'done'):
                try:
                    move._action_assign()
                except Exception as e:
                    _logger.warning(f'No se pudo asignar stock para move {move.id}: {str(e)}')
            
            # Si hay move_line_ids, establecer las cantidades
            if move.move_line_ids:
                for move_line in move.move_line_ids:
                    move_line.qty_done = move.product_uom_qty
            else:
                # Si no hay move_line_ids (sin stock disponible), crear uno manualmente
                # Esto fuerza la creación de move_line_ids incluso sin stock
                try:
                    # Intentar asignar nuevamente por si acaso
                    move._action_assign()
                except:
                    pass
                
                # Si aún no hay move_line_ids después de _action_assign(), crear manualmente
                if not move.move_line_ids:
                    # Crear move_line manualmente con la cantidad requerida
                    self.env['stock.move.line'].create({
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'qty_done': move.product_uom_qty,  # Cantidad a consumir
                    })
                    # Recargar el move para obtener los nuevos move_line_ids
                    move.invalidate_recordset(['move_line_ids'])
                
                # Establecer las cantidades en los move_line_ids
                for move_line in move.move_line_ids:
                    if move_line.qty_done == 0:
                        move_line.qty_done = move.product_uom_qty
        
        # Intentar cerrar la orden de producción (estado "Disponible")
        try:
            # Asegurar que todos los movimientos estén en estado correcto
            production.move_raw_ids._action_assign()
            production.button_mark_done()
        except Exception as e:
            # Si falla el cierre, intentar forzar el estado
            _logger.warning(f'Error al cerrar orden de producción {production.name}: {str(e)}')
            
            # Marcar los movimientos como completados manualmente
            for move in production.move_raw_ids:
                if move.state not in ('done', 'cancel'):
                    # Forzar las cantidades consumidas
                    for move_line in move.move_line_ids:
                        move_line.qty_done = move.product_uom_qty
                    # Si el move no tiene move_line_ids, crear uno
                    if not move.move_line_ids:
                        self.env['stock.move.line'].create({
                            'move_id': move.id,
                            'product_id': move.product_id.id,
                            'product_uom_id': move.product_uom.id,
                            'location_id': move.location_id.id,
                            'location_dest_id': move.location_dest_id.id,
                            'qty_done': move.product_uom_qty,
                        })
                        move.invalidate_recordset(['move_line_ids'])
                    
                    # Intentar marcar como done
                    try:
                        if hasattr(move, '_action_done'):
                            move._action_done()
                        elif move.state == 'assigned':
                            # Forzar el cambio de estado
                            move.quantity_done = sum(move.move_line_ids.mapped('qty_done'))
                    except Exception as move_error:
                        _logger.warning(f'No se pudo marcar move {move.id} como done: {str(move_error)}')
            
            # Intentar cerrar nuevamente
            try:
                production.button_mark_done()
            except Exception as e2:
                # Si aún falla, registrar el error pero continuar
                _logger.error(f'No se pudo cerrar automáticamente la orden de producción {production.name}: {str(e2)}')
                raise UserError(f'No se pudo cerrar automáticamente la orden de producción {production.name}. '
                              f'Por favor, ciérrela manualmente desde el menú de acciones. Error: {str(e2)}')
    
    def _get_uom_box(self):
        """Obtiene la unidad de medida 'Cajón' en cualquier categoría"""
        # Buscar "Cajón" en todas las categorías
        box_uom = self.env['uom.uom'].search([
            ('name', 'ilike', 'Cajón'),
        ], limit=1)
        if not box_uom:
            # Si no encuentra con tilde, buscar sin tilde
            box_uom = self.env['uom.uom'].search([
                ('name', 'ilike', 'Cajon'),
            ], limit=1)
        return box_uom
    
    def action_view_productions(self):
        """Abre la vista de órdenes de fabricación generadas"""
        self.ensure_one()
        return {
            'name': 'Órdenes de Fabricación',
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('egg_collection_id', '=', self.id)],
            'context': {'create': False},
        }
    
    def action_debug_uom_names(self):
        """Método de debug para verificar los nombres de las unidades de medida"""
        self.ensure_one()
        _logger.info("=== DEBUG action_debug_uom_names para collection %s ===", self.id)
        
        # Información de la collection
        _logger.info("Collection: %s, Producto: %s", self.name, self.product_tmpl_id.name if self.product_tmpl_id else 'N/A')
        _logger.info("Líneas: %d", len(self.line_ids))
        
        # Información de las líneas
        for line in self.line_ids:
            _logger.info("  Línea %s: Variante=%s, uom_value_ids=%d", 
                        line.id, 
                        line.product_variant_id.name if line.product_variant_id else 'N/A',
                        len(line.uom_value_ids))
            
            
            # Información de cada uom_value
            for uom_val in line.uom_value_ids:
                _logger.info("    UoM Value %s: uom_id=%s (%s), ratio=%s, uom_display_name=%s, poultry_display_name=%s",
                            uom_val.id,
                            uom_val.uom_id.id if uom_val.uom_id else 'N/A',
                            uom_val.uom_id.name if uom_val.uom_id else 'N/A',
                            uom_val.uom_ratio,
                            uom_val.uom_display_name,
                            uom_val.uom_id.poultry_display_name if uom_val.uom_id else 'N/A')
        
        # Retornar mensaje al usuario
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Debug UoM Names',
                'message': f'Revisa los logs del servidor. Collection: {self.name}',
                'type': 'info',
                'sticky': False,
            }
        }
    
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Recálculo Completado',
                'message': f'Se recalcularon {len(all_lines)} líneas y {len(all_collections)} collections',
                'type': 'success',
                'sticky': False,
            }
        }

