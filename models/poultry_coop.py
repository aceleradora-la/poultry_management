# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryCoop(models.Model):
    _name = 'poultry.coop'
    _description = 'Galpón Avícola'
    _order = 'name'

    name = fields.Char(string='Nombre del Galpón', required=True, index=True)
    code = fields.Char(string='Código', required=True, index=True, copy=False)
    size = fields.Float(string='Tamaño (m²)', required=True, help='Tamaño del galpón en metros cuadrados')
    capacity = fields.Integer(string='Capacidad de Aves', required=True, help='Capacidad máxima de aves que puede albergar')
    active = fields.Boolean(string='Activo', default=True)
    
    # Relaciones con lotes de aves (vía asignaciones lote-galpón, un lote puede repartirse
    # entre varios galpones y cambiar de galpón a lo largo de su vida)
    coop_line_ids = fields.One2many('poultry.batch.coop.line', 'coop_id',
                                     string='Historial de Asignaciones de Lotes')
    current_batch_ids = fields.Many2many('poultry.batch', string='Lotes Actuales',
                                          compute='_compute_current_batch_ids')
    batch_count = fields.Integer(string='Cantidad de Lotes', compute='_compute_batch_count')
    
    # Relaciones con recolecciones de producción
    egg_collection_ids = fields.One2many('poultry.egg.collection', 'coop_id', string='Recolecciones de Producción')
    egg_collection_count = fields.Integer(string='Recolecciones', compute='_compute_egg_collection_count')
    
    # Relaciones con mortalidad
    mortality_ids = fields.One2many('poultry.mortality', 'coop_id', string='Registros de Mortalidad')
    mortality_count = fields.Integer(string='Registros de Mortalidad', compute='_compute_mortality_count')
    
    # Relación con listas de materiales (BOM)
    coop_bom_ids = fields.One2many('poultry.coop.bom', 'coop_id', string='Historial de Listas de Materiales')
    active_bom_id = fields.Many2one('poultry.coop.bom', string='Lista de Materiales Activa', 
                                     compute='_compute_active_bom', search='_search_active_bom_id')
    active_bom_name = fields.Char(string='Lista de Materiales Activa',
                                  compute='_compute_active_bom')
    active_bom_start_date = fields.Date(string='Fecha Inicio Lista Activa', 
                                         related='active_bom_id.start_date', readonly=True)
    
    # Tipo de Operación para listas de materiales
    routing_workcenter_id = fields.Many2one('mrp.routing.workcenter', string='Tipo de Operación',
                                             help='Tipo de operación a utilizar al crear las listas de materiales para este galpón')
    
    # Lista de Materiales para Huevo sin Clasificar
    unclassified_egg_product_id = fields.Many2one('product.product', string='Producto - Huevo sin Clasificar',
                                                    help='Producto de huevo sin clasificar para este galpón')
    unclassified_egg_bom_id = fields.Many2one('mrp.bom', string='Lista de Materiales - Huevo sin Clasificar',
                                               domain="[('type', '=', 'normal')]",
                                               help='Lista de materiales para el producto de huevo sin clasificar de este galpón')
    
    # Tipos de Operación de Inventario
    picking_type_id_finished = fields.Many2one('stock.picking.type', string='Tipo de Operación - Productos Terminados',
                                               help='Tipo de operación de inventario para órdenes de producción de productos terminados')
    picking_type_id_unclassified = fields.Many2one('stock.picking.type', string='Tipo de Operación - Huevo sin Clasificar',
                                                    help='Tipo de operación de inventario para órdenes de producción de huevo sin clasificar')
    
    # Prefijo de Secuencia para Partes de Producción
    sequence_prefix = fields.Char(string='Prefijo de Secuencia', default='REC',
                                  help='Prefijo para la numeración de partes de producción de este galpón (ej: REC, GP1, etc.)')
    
    # Total de aves asignadas actualmente al galpón (asignaciones vigentes, sin descontar mortalidad)
    current_birds_count = fields.Integer(string='Total de Aves Asignadas',
                                         compute='_compute_current_birds_count',
                                         store=True)

    # Aves realmente vivas hoy (asignadas menos mortalidad registrada). No se almacena:
    # siempre se recalcula al leer, para reflejar la mortalidad cargada hasta el momento.
    live_bird_count = fields.Integer(string='Aves Vivas', compute='_compute_live_bird_count')

    # Porcentaje de ocupación
    occupancy_percentage = fields.Float(string='% Ocupación',
                                        compute='_compute_occupancy_percentage',
                                        store=True)

    notes = fields.Text(string='Notas')

    def _get_active_coop_lines(self):
        self.ensure_one()
        return self.coop_line_ids.filtered(lambda l: l.active and not l.date_to)

    @api.depends('coop_line_ids.bird_count', 'coop_line_ids.date_to', 'coop_line_ids.active')
    def _compute_current_birds_count(self):
        """Calcula el total de aves asignadas vigentes al galpón (sin descontar mortalidad)"""
        for coop in self:
            coop.current_birds_count = sum(coop._get_active_coop_lines().mapped('bird_count'))

    def _compute_live_bird_count(self):
        """Calcula el total de aves vivas hoy en el galpón (asignadas menos mortalidad)"""
        for coop in self:
            coop.live_bird_count = sum(coop._get_active_coop_lines().mapped('live_bird_count'))

    @api.depends('current_birds_count', 'capacity')
    def _compute_occupancy_percentage(self):
        """Calcula el porcentaje de ocupación del galpón"""
        for coop in self:
            if coop.capacity > 0:
                coop.occupancy_percentage = coop.current_birds_count / coop.capacity
            else:
                coop.occupancy_percentage = 0.0

    @api.depends('coop_line_ids.batch_id', 'coop_line_ids.date_to', 'coop_line_ids.active')
    def _compute_current_batch_ids(self):
        """Lotes con aves actualmente asignadas (vigentes) a este galpón"""
        for coop in self:
            coop.current_batch_ids = coop._get_active_coop_lines().mapped('batch_id')

    @api.depends('current_batch_ids')
    def _compute_batch_count(self):
        """Cuenta la cantidad de lotes actualmente asignados al galpón"""
        for coop in self:
            coop.batch_count = len(coop.current_batch_ids)
    
    @api.depends('egg_collection_ids')
    def _compute_egg_collection_count(self):
        """Cuenta la cantidad de recolecciones del galpón"""
        for coop in self:
            coop.egg_collection_count = len(coop.egg_collection_ids)
    
    @api.depends('mortality_ids')
    def _compute_mortality_count(self):
        """Cuenta la cantidad de registros de mortalidad del galpón"""
        for coop in self:
            coop.mortality_count = len(coop.mortality_ids)
    
    @api.depends('coop_bom_ids', 'coop_bom_ids.active', 'coop_bom_ids.start_date', 'coop_bom_ids.end_date')
    def _compute_active_bom(self):
        """Obtiene la lista activa del galpón válida para hoy."""
        today = fields.Date.context_today(self)
        for coop in self:
            active_bom = self.env['poultry.coop.bom'].get_active_bom_for_coop_date(coop.id, today)
            coop.active_bom_id = active_bom
            coop.active_bom_name = active_bom.bom_id.display_name if active_bom and active_bom.bom_id else False

    def _search_active_bom_id(self, operator, value):
        """Permite filtrar por existencia de lista activa vigente a la fecha de hoy."""
        if operator not in ('=', '!='):
            return [('id', '!=', 0)]

        today = fields.Date.context_today(self)
        active_coop_ids = self.env['poultry.coop.bom'].search([
            ('active', '=', True),
            ('start_date', '<=', today),
            '|',
            ('end_date', '=', False),
            ('end_date', '>=', today),
        ]).mapped('coop_id').ids

        if value in (False, None):
            if operator == '=':
                return [('id', 'not in', active_coop_ids)]
            return [('id', 'in', active_coop_ids)]

        bom = self.env['poultry.coop.bom'].browse(value)
        coop_ids = bom.filtered(
            lambda b: b.active and b.start_date and b.start_date <= today and (not b.end_date or b.end_date >= today)
        ).mapped('coop_id').ids
        if operator == '=':
            return [('id', 'in', coop_ids)]
        return [('id', 'not in', coop_ids)]
    
    @api.constrains('capacity', 'current_birds_count')
    def _check_capacity(self):
        """Valida que no se exceda la capacidad del galpón"""
        for coop in self:
            if coop.current_birds_count > coop.capacity:
                raise ValidationError(
                    f'El galpón {coop.name} excede su capacidad. '
                    f'Capacidad: {coop.capacity}, Aves actuales: {coop.current_birds_count}'
                )
    
    @api.constrains('code')
    def _check_code_unique(self):
        """Valida que el código sea único"""
        for coop in self:
            if self.search_count([('code', '=', coop.code), ('id', '!=', coop.id)]) > 0:
                raise ValidationError(f'El código {coop.code} ya existe. Debe ser único.')
    
    @api.model_create_multi
    def create(self, vals_list):
        """Genera código automático si no se proporciona."""
        for vals in vals_list:
            if not vals.get('code'):
                vals['code'] = self.env['ir.sequence'].next_by_code('poultry.coop') or 'NUEVO'
        return super().create(vals_list)

    @staticmethod
    def _sort_coop_bom_commands(commands):
        """Ordena comandos one2many para aplicar primero bajas y evitar falsos solapes."""
        priority = {
            5: 0,  # clear
            2: 1,  # delete
            3: 2,  # unlink
            1: 3,  # update
            0: 4,  # create
            4: 5,  # link
            6: 6,  # set
        }
        normalized = []
        for command in commands or []:
            if isinstance(command, (list, tuple)) and command:
                normalized.append(command)
        return sorted(normalized, key=lambda cmd: priority.get(cmd[0], 99))

    def _validate_final_coop_bom_ranges(self):
        """Valida solapamientos usando el estado final persistido del galpón."""
        for coop in self:
            active_boms = coop.coop_bom_ids.filtered(lambda b: b.active and b.start_date).sorted(
                key=lambda b: (b.start_date, b.id or 0)
            )
            for index, bom in enumerate(active_boms):
                bom_end = bom.end_date or fields.Date.to_date('9999-12-31')
                for other in active_boms[index + 1:]:
                    other_end = other.end_date or fields.Date.to_date('9999-12-31')
                    if bom.start_date <= other_end and other.start_date <= bom_end:
                        raise ValidationError(
                            'No se puede tener dos listas activas con rangos de fechas superpuestos '
                            f'para el galpón {coop.display_name}. '
                            f'Rango existente: {bom.start_date} -> {bom.end_date or "sin fin"}.'
                        )

    def write(self, vals):
        """Aplica comandos de listas de materiales en orden seguro."""
        has_bom_commands = bool(vals.get('coop_bom_ids') and isinstance(vals.get('coop_bom_ids'), list))
        if vals.get('coop_bom_ids') and isinstance(vals.get('coop_bom_ids'), list):
            vals = dict(vals)
            vals['coop_bom_ids'] = self._sort_coop_bom_commands(vals['coop_bom_ids'])
        result = super(PoultryCoop, self.with_context(skip_coop_bom_overlap_check=True)).write(vals)
        if has_bom_commands:
            self._validate_final_coop_bom_ranges()
        return result
    
    def action_view_batches(self):
        """Abre la vista de lotes actualmente asignados a este galpón"""
        self.ensure_one()
        action = {
            'name': f'Lotes de Aves - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.batch',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.current_batch_ids.ids)],
        }
        return action
    
    def action_view_active_bom(self):
        """Abre la vista de la lista de materiales activa"""
        if not self.active_bom_id:
            return False
        return {
            'name': f'Lista de Materiales Activa - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.coop.bom',
            'res_id': self.active_bom_id.id,
            'view_mode': 'form',
        }

