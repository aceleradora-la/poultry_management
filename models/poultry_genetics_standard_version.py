# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryGeneticsStandardVersion(models.Model):
    _name = 'poultry.genetics.standard.version'
    _description = 'Versión de Estándar de Genética'
    _order = 'genetics_id, is_default desc, name'
    _rec_name = 'display_name'

    genetics_id = fields.Many2one('poultry.genetics', string='Genética', required=True,
                                   index=True, ondelete='cascade')
    name = fields.Char(string='Nombre', required=True,
                        help='Ej: "Guía de Rendimiento Abril 2026", "Edición Anterior"')
    code = fields.Char(string='Código')
    is_default = fields.Boolean(string='Versión Predeterminada', default=False,
                                 help='Versión utilizada por defecto para esta genética cuando '
                                      'no se especifica una versión concreta en los reportes.')
    active = fields.Boolean(string='Activo', default=True)
    notes = fields.Text(string='Notas')

    standard_ids = fields.One2many('poultry.genetics.standard', 'version_id', string='Estándares')
    standard_count = fields.Integer(string='Cantidad de Estándares', compute='_compute_standard_count')

    display_name = fields.Char(string='Nombre', compute='_compute_display_name', store=True)

    @api.depends('genetics_id.name', 'name')
    def _compute_display_name(self):
        for record in self:
            if record.genetics_id:
                record.display_name = f'{record.genetics_id.name} - {record.name}'
            else:
                record.display_name = record.name

    @api.depends('standard_ids')
    def _compute_standard_count(self):
        for record in self:
            record.standard_count = len(record.standard_ids)

    @api.constrains('is_default', 'genetics_id', 'active')
    def _check_single_default(self):
        """Garantiza una única versión predeterminada activa por genética"""
        for record in self.filtered(lambda r: r.is_default and r.active):
            others = self.search_count([
                ('genetics_id', '=', record.genetics_id.id),
                ('is_default', '=', True),
                ('active', '=', True),
                ('id', '!=', record.id),
            ])
            if others:
                raise ValidationError(
                    f'Ya existe una versión predeterminada para la genética '
                    f'{record.genetics_id.name}. Desmarque la anterior antes de marcar esta.'
                )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered('is_default')._unset_other_defaults()
        return records

    def write(self, vals):
        result = super().write(vals)
        if vals.get('is_default'):
            self.filtered('is_default')._unset_other_defaults()
        return result

    def _unset_other_defaults(self):
        """Desmarca cualquier otra versión predeterminada de la misma genética"""
        for record in self:
            others = self.search([
                ('genetics_id', '=', record.genetics_id.id),
                ('is_default', '=', True),
                ('id', '!=', record.id),
            ])
            if others:
                others.write({'is_default': False})
