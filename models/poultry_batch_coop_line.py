# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryBatchCoopLine(models.Model):
    _name = 'poultry.batch.coop.line'
    _description = 'Asignación de Lote a Galpón'
    _order = 'date_from desc, id desc'
    _rec_name = 'display_name'

    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', required=True,
                                index=True, ondelete='cascade')
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True, index=True,
                               domain="[('active', '=', True)]")
    bird_count = fields.Integer(string='Cantidad de Aves Asignadas', required=True, default=0)
    date_from = fields.Date(string='Fecha de Asignación', required=True, default=fields.Date.today)
    date_to = fields.Date(string='Fecha de Baja/Traslado',
                          help='Fecha en que estas aves dejaron de estar en este galpón '
                               '(por traslado a otro galpón o fin del lote). Vacío = vigente.')
    active = fields.Boolean(string='Activo', default=True)
    notes = fields.Text(string='Notas')

    dead_count = fields.Integer(string='Aves Muertas', compute='_compute_dead_count')
    live_bird_count = fields.Integer(string='Aves Vivas', compute='_compute_dead_count')

    display_name = fields.Char(string='Nombre', compute='_compute_display_name', store=True)

    @api.depends('batch_id.name', 'coop_id.name', 'date_from')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f'{record.batch_id.name} -> {record.coop_id.name} ({record.date_from})'

    def _compute_dead_count(self):
        """Aves muertas de este lote en este galpón durante la vigencia de la asignación,
        según los registros de poultry.mortality (batch_id + coop_id + fecha)."""
        today = fields.Date.today()
        for record in self:
            if not (record.batch_id and record.coop_id and record.date_from):
                record.dead_count = 0
                record.live_bird_count = record.bird_count
                continue
            domain = [
                ('batch_id', '=', record.batch_id.id),
                ('coop_id', '=', record.coop_id.id),
                ('date', '>=', record.date_from),
                ('active', '=', True),
            ]
            end_date = record.date_to or today
            domain.append(('date', '<=', end_date))
            mortalities = self.env['poultry.mortality'].search(domain)
            record.dead_count = sum(mortalities.mapped('dead_count'))
            record.live_bird_count = max(record.bird_count - record.dead_count, 0)

    def _get_live_bird_count_on(self, target_date):
        """Aves vivas de esta línea a una fecha determinada (histórica), a diferencia
        de live_bird_count que siempre calcula respecto a hoy."""
        self.ensure_one()
        if not (self.batch_id and self.coop_id and self.date_from) or target_date < self.date_from:
            return 0
        end_date = self.date_to if (self.date_to and self.date_to < target_date) else target_date
        mortalities = self.env['poultry.mortality'].search([
            ('batch_id', '=', self.batch_id.id),
            ('coop_id', '=', self.coop_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', end_date),
            ('active', '=', True),
        ])
        dead = sum(mortalities.mapped('dead_count'))
        return max(self.bird_count - dead, 0)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for record in self:
            if record.date_to and record.date_from and record.date_to < record.date_from:
                raise ValidationError(
                    'La fecha de baja/traslado no puede ser anterior a la fecha de asignación.'
                )

    @api.constrains('bird_count')
    def _check_bird_count(self):
        for record in self:
            if record.bird_count <= 0:
                raise ValidationError('La cantidad de aves asignadas debe ser mayor a cero.')

    @api.constrains('bird_count', 'batch_id', 'date_to', 'active')
    def _check_batch_total(self):
        """La suma de aves asignadas vigentes de un lote no puede superar el tamaño del lote."""
        for record in self.filtered(lambda r: r.active and not r.date_to):
            other_lines = self.search([
                ('batch_id', '=', record.batch_id.id),
                ('active', '=', True),
                ('date_to', '=', False),
                ('id', '!=', record.id),
            ])
            total_assigned = record.bird_count + sum(other_lines.mapped('bird_count'))
            if record.batch_id.bird_count and total_assigned > record.batch_id.bird_count:
                raise ValidationError(
                    f'La suma de aves asignadas a galpones ({total_assigned}) no puede superar '
                    f'la cantidad de aves del lote {record.batch_id.name} ({record.batch_id.bird_count}).'
                )

    @api.constrains('bird_count', 'coop_id', 'date_to', 'active')
    def _check_coop_capacity(self):
        """La suma de aves asignadas vigentes de un galpón no puede superar su capacidad."""
        for record in self.filtered(lambda r: r.active and not r.date_to):
            other_lines = self.search([
                ('coop_id', '=', record.coop_id.id),
                ('active', '=', True),
                ('date_to', '=', False),
                ('id', '!=', record.id),
            ])
            total_assigned = record.bird_count + sum(other_lines.mapped('bird_count'))
            if total_assigned > record.coop_id.capacity:
                raise ValidationError(
                    f'No se puede asignar estas aves al galpón {record.coop_id.name}. '
                    f'Se excedería la capacidad. Capacidad: {record.coop_id.capacity}, '
                    f'Aves totales asignadas: {total_assigned}.'
                )
