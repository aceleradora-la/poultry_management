# -*- coding: utf-8 -*-

from datetime import date as pydate

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryCoopBom(models.Model):
    _name = 'poultry.coop.bom'
    _description = 'Lista de Materiales de Alimento por Galpón'
    _order = 'start_date desc'

    name = fields.Char(string='Descripción', default='Nueva Lista de Materiales')
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True, 
                               domain="[('active', '=', True)]")
    bom_id = fields.Many2one('mrp.bom', string='Lista de Materiales', required=True,
                              domain="[('type', '=', 'normal')]")
    bom_product_id = fields.Many2one('product.product', string='Producto de la BOM', 
                                      related='bom_id.product_id', readonly=True, store=True)
    
    # Fechas de activación
    start_date = fields.Date(string='Fecha de Inicio', required=True, default=fields.Date.today)
    end_date = fields.Date(string='Fecha de Fin', help='Fecha en que se desactivó esta lista de materiales')
    
    # Estado
    active = fields.Boolean(string='Activa', default=True, help='Indica si esta es la lista de materiales activa para el galpón')
    
    # Notas
    notes = fields.Text(string='Notas')

    def _get_overlap_record(self, records):
        """Retorna un registro activo que se solape con self, si existe."""
        self.ensure_one()
        this_end = self.end_date or pydate.max
        for other in records:
            if other == self:
                continue
            if not other.active or not other.start_date:
                continue
            if other.coop_id != self.coop_id:
                continue
            other_end = other.end_date or pydate.max
            if self.start_date <= other_end and other.start_date <= this_end:
                return other
        return self.browse()

    def _range_label(self):
        """Texto legible del rango de vigencia para mensajes de validación."""
        self.ensure_one()
        end_date = self.end_date or 'sin fin'
        return f'{self.start_date} -> {end_date}'

    @api.onchange('coop_id', 'active', 'start_date', 'end_date')
    def _onchange_validate_active_bom_overlap(self):
        """Valida en edición que no exista solapamiento activo para el galpón."""
        for coop_bom in self:
            if not (coop_bom.active and coop_bom.coop_id and coop_bom.start_date):
                continue
            overlap = coop_bom._get_overlap_record(coop_bom.coop_id.coop_bom_ids)
            if overlap:
                raise ValidationError(
                    'Ya existe una lista activa superpuesta para este galpón.\n'
                    f'Rango existente: {overlap._range_label()}\n'
                    f'Rango ingresado: {coop_bom._range_label()}'
                )
    
    @api.constrains('coop_id', 'active', 'start_date', 'end_date')
    def _check_active_bom_date_overlap(self):
        """Evita solapamientos entre listas activas de un mismo galpón."""
        for coop_bom in self.filtered(lambda b: b.active and b.coop_id and b.start_date):
            other_active = self.search([
                ('coop_id', '=', coop_bom.coop_id.id),
                ('active', '=', True),
                ('id', '!=', coop_bom.id),
            ])
            overlap = coop_bom._get_overlap_record(other_active)
            if overlap:
                raise ValidationError(
                    'No se puede tener dos listas activas con rangos de fechas superpuestos '
                    f'para el galpón {coop_bom.coop_id.display_name}. '
                    f'Rango existente: {overlap._range_label()}.'
                )
    
    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        """Valida que la fecha de fin sea posterior a la fecha de inicio"""
        for coop_bom in self:
            if coop_bom.end_date and coop_bom.start_date:
                if coop_bom.end_date < coop_bom.start_date:
                    raise ValidationError(
                        'La fecha de fin no puede ser anterior a la fecha de inicio.'
                    )
    
    def action_set_active(self):
        """Acción para activar esta lista de materiales"""
        self.ensure_one()
        self.write({'active': True, 'end_date': False})
    
    def action_set_inactive(self):
        """Acción para desactivar esta lista de materiales"""
        self.ensure_one()
        self.write({'active': False, 'end_date': fields.Date.today()})
    
    def name_get(self):
        """Personaliza el nombre mostrado"""
        result = []
        for coop_bom in self:
            name = f'{coop_bom.coop_id.name} - {coop_bom.bom_id.product_id.name}'
            if coop_bom.active:
                name += ' [ACTIVA]'
            result.append((coop_bom.id, name))
        return result

    @api.model
    def get_active_bom_for_coop_date(self, coop_id, target_date=False):
        """Devuelve la lista activa del galpón que cubre la fecha indicada."""
        if not coop_id:
            return self.browse()

        target_date = target_date or fields.Date.context_today(self)
        if isinstance(target_date, str):
            target_date = fields.Date.to_date(target_date)

        return self.search([
            ('coop_id', '=', coop_id),
            ('active', '=', True),
            ('start_date', '<=', target_date),
            '|',
            ('end_date', '=', False),
            ('end_date', '>=', target_date),
        ], order='start_date desc, id desc', limit=1)

