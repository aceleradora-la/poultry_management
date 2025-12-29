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

    name = fields.Char(string='Referencia', required=True, default='Nueva Recolección', copy=False, index=True)
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
        ('draft', 'Borrador'),
        ('counted', 'Cantidad Inicial Registrada'),
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
    
    # Campos para nombres dinámicos de unidades (para títulos y columnas)
    uom_1_name = fields.Char(string='Unidad 1', compute='_compute_uom_display_names', store=True)
    uom_2_name = fields.Char(string='Unidad 2', compute='_compute_uom_display_names', store=True)
    uom_3_name = fields.Char(string='Unidad 3', compute='_compute_uom_display_names', store=True)
    
    # Totales (los strings se actualizarán dinámicamente en la vista)
    total_initial_boxes = fields.Float(string='Total Inicial', compute='_compute_totals', store=True)
    total_initial_maps = fields.Float(string='Total Inicial', compute='_compute_totals', store=True)
    total_initial_eggs = fields.Float(string='Total Inicial', compute='_compute_totals', store=True)
    
    total_final_boxes = fields.Float(string='Total Final', compute='_compute_totals', store=True)
    total_final_maps = fields.Float(string='Total Final', compute='_compute_totals', store=True)
    total_final_eggs = fields.Float(string='Total Final', compute='_compute_totals', store=True)
    
    total_produced_boxes = fields.Float(string='Total Producido', compute='_compute_totals', store=True)
    total_produced_maps = fields.Float(string='Total Producido', compute='_compute_totals', store=True)
    total_produced_eggs = fields.Float(string='Total Producido', compute='_compute_totals', store=True)
    
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
                 'line_ids.uom_value_ids.initial_qty', 'line_ids.uom_value_ids.final_qty',
                 'line_ids.uom_value_ids.uom_id', 'line_ids.uom_value_ids.uom_id.poultry_display_name')
    def _compute_uom_display_names(self):
        """Calcula los nombres dinámicos de las unidades de medida para mostrar en títulos y columnas"""
        for collection in self:
            _logger.info("=== DEBUG _compute_uom_display_names para collection %s ===", collection.id)
            # Obtener los nombres de la primera línea que tenga uom_value_ids
            first_line_with_uoms = collection.line_ids.filtered(lambda l: l.uom_value_ids)[:1]
            _logger.info("Collection %s: Tiene %d líneas, primera con UoMs: %s", 
                        collection.id, len(collection.line_ids), first_line_with_uoms.id if first_line_with_uoms else 'Ninguna')
            
            if first_line_with_uoms and first_line_with_uoms.uom_value_ids:
                sorted_uoms = sorted(first_line_with_uoms.uom_value_ids, 
                                   key=lambda x: x.uom_ratio or 0.0, 
                                   reverse=True)
                _logger.info("Collection %s: Primera línea tiene %d UoMs", collection.id, len(sorted_uoms))
                for idx, uom_val in enumerate(sorted_uoms[:3]):
                    _logger.info("  UoM %d: uom_display_name=%s", idx+1, uom_val.uom_display_name)
                
                collection.uom_1_name = sorted_uoms[0].uom_display_name if len(sorted_uoms) > 0 and sorted_uoms[0].uom_display_name else ''
                collection.uom_2_name = sorted_uoms[1].uom_display_name if len(sorted_uoms) > 1 and sorted_uoms[1].uom_display_name else ''
                collection.uom_3_name = sorted_uoms[2].uom_display_name if len(sorted_uoms) > 2 and sorted_uoms[2].uom_display_name else ''
            else:
                _logger.warning("Collection %s: No tiene líneas con uom_value_ids", collection.id)
                collection.uom_1_name = ''
                collection.uom_2_name = ''
                collection.uom_3_name = ''
            
            _logger.info("Collection %s: Resultados - uom_1_name=%s, uom_2_name=%s, uom_3_name=%s",
                        collection.id, collection.uom_1_name, collection.uom_2_name, collection.uom_3_name)
    
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
    
    @api.depends('production_ids')
    def _compute_production_count(self):
        """Cuenta las órdenes de fabricación generadas"""
        for collection in self:
            collection.production_count = len(collection.production_ids)
    
    @api.model
    def create(self, vals):
        """Genera referencia automática si no se proporciona"""
        if not vals.get('name') or vals.get('name') == 'Nueva Recolección':
            vals['name'] = self.env['ir.sequence'].next_by_code('poultry.egg.collection') or 'NUEVA'
        record = super().create(vals)
        # Forzar recálculo de product_variant_name después de crear
        if 'product_tmpl_id' in vals:
            record._compute_product_variant_name()
        return record
    
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
            # Forzar recálculo de los totales después de calcular producción
            record._compute_totals()
            record.state = 'completed'
    
    def action_set_to_draft(self):
        """Permite volver a borrador si aún no se han generado las órdenes de fabricación"""
        for record in self:
            if record.state == 'done':
                raise UserError('No se puede volver a borrador una recolección que ya ha sido procesada (tiene órdenes de fabricación generadas).')
            if record.production_ids:
                raise UserError('No se puede volver a borrador porque ya se han generado órdenes de fabricación.')
            record.state = 'draft'
    
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
        
        for line in self.line_ids:
            product = line.product_variant_id
            if not product:
                continue
            
            if use_dynamic and line.uom_value_ids:
                # Usar el nuevo sistema: generar órdenes para cada unidad con produced_qty > 0
                for uom_val in line.uom_value_ids:
                    if uom_val.produced_qty > 0:
                        # Usar la BOM del producto base (ya encontrada arriba)
                        production = self.env['mrp.production'].create({
                            'product_id': product.id,
                            'product_qty': uom_val.produced_qty,
                            'product_uom_id': uom_val.uom_id.id,
                            'bom_id': bom.id,
                            'coop_id': self.coop_id.id,
                            'egg_collection_id': self.id,
                            'origin': self.name,
                        })
                        production.action_confirm()
                        productions_created.append(production.id)
            else:
                # Método legacy: solo generar para cajones
                box_uom = self._get_uom_box()
                if not box_uom:
                    raise UserError('No se encontró la unidad de medida "Cajón". '
                                  'Debe crear esta unidad de medida antes de generar las órdenes.')
                
                if line.produced_box > 0:
                    production = self.env['mrp.production'].create({
                        'product_id': product.id,
                        'product_qty': line.produced_box,
                        'product_uom_id': box_uom.id,
                        'bom_id': bom.id,
                        'coop_id': self.coop_id.id,
                        'egg_collection_id': self.id,
                        'origin': self.name,
                    })
                    production.action_confirm()
                    productions_created.append(production.id)
        
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
            
            # Forzar cálculo de nombres
            line._compute_uom_display_names()
            _logger.info("    uom_1_name=%s, uom_2_name=%s, uom_3_name=%s",
                        line.uom_1_name, line.uom_2_name, line.uom_3_name)
            
            # Información de cada uom_value
            for uom_val in line.uom_value_ids:
                _logger.info("    UoM Value %s: uom_id=%s (%s), ratio=%s, uom_display_name=%s, poultry_display_name=%s",
                            uom_val.id,
                            uom_val.uom_id.id if uom_val.uom_id else 'N/A',
                            uom_val.uom_id.name if uom_val.uom_id else 'N/A',
                            uom_val.uom_ratio,
                            uom_val.uom_display_name,
                            uom_val.uom_id.poultry_display_name if uom_val.uom_id else 'N/A')
        
        # Forzar cálculo de nombres de la collection
        self._compute_uom_display_names()
        _logger.info("Collection uom_1_name=%s, uom_2_name=%s, uom_3_name=%s",
                    self.uom_1_name, self.uom_2_name, self.uom_3_name)
        
        # Retornar mensaje al usuario
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Debug UoM Names',
                'message': f'Revisa los logs del servidor. Collection: {self.name}, uom_1={self.uom_1_name}, uom_2={self.uom_2_name}, uom_3={self.uom_3_name}',
                'type': 'info',
                'sticky': False,
            }
        }
    
    def action_recompute_uom_names(self):
        """Método para recalcular los nombres de unidades de medida almacenados para esta collection"""
        self.ensure_one()
        _logger.info("=== Recalculando nombres UoM para collection %s ===", self.id)
        
        # Recalcular para todas las líneas de esta collection
        self.line_ids._compute_uom_display_names()
        
        # Recalcular para esta collection
        self._compute_uom_display_names()
        
        _logger.info("=== Recálculo completado ===")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Recálculo Completado',
                'message': f'Se recalcularon los nombres para {len(self.line_ids)} líneas',
                'type': 'success',
                'sticky': False,
            }
        }
    
    @api.model
    def _recompute_uom_names_all(self):
        """Método para recalcular todos los nombres de unidades de medida almacenados"""
        _logger.info("=== Iniciando recálculo de nombres UoM para todas las collections ===")
        
        # Recalcular para todas las líneas
        all_lines = self.env['poultry.egg.collection.line'].search([])
        _logger.info("Recalculando %d líneas", len(all_lines))
        all_lines._compute_uom_display_names()
        
        # Recalcular para todas las collections
        all_collections = self.env['poultry.egg.collection'].search([])
        _logger.info("Recalculando %d collections", len(all_collections))
        all_collections._compute_uom_display_names()
        
        _logger.info("=== Recálculo completado ===")
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

