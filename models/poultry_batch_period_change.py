# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PoultryBatchPeriodChange(models.Model):
    _name = 'poultry.batch.period.change'
    _description = 'Cambio de Período del Lote'
    _order = 'date desc, id desc'
    _rec_name = 'display_name'

    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', required=True,
                                index=True, ondelete='cascade')
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True,
                               help='Galpón donde está el lote al momento de este cambio. '
                                    'El lote puede ya haberse trasladado de Recría a '
                                    'Producción sin que eso implique, por sí solo, que '
                                    'cambió de Período: son dos eventos independientes.')
    date = fields.Date(string='Fecha', required=True, default=fields.Date.today)
    period = fields.Selection([
        ('crianza', 'Crianza'),
        ('produccion', 'Producción'),
    ], string='Período Nuevo', required=True, default='produccion')

    housed_bird_count = fields.Integer(
        string='Aves Alojadas', readonly=True, copy=False,
        help='Aves vivas del lote en este galpón a esta fecha (aves ingresadas menos '
             'mortalidad registrada), calculadas y fijadas automáticamente al registrar '
             'el cambio a Producción. Es la base fija de Huevos Acumulados Ave-Alojada.'
    )

    notes = fields.Text(string='Notas')
    active = fields.Boolean(string='Activo', default=True)

    display_name = fields.Char(string='Nombre', compute='_compute_display_name', store=True)

    @api.depends('batch_id.name', 'coop_id.name', 'period', 'date')
    def _compute_display_name(self):
        period_labels = dict(self._fields['period'].selection)
        for record in self:
            record.display_name = (
                f'{record.batch_id.name} -> {period_labels.get(record.period, "")} '
                f'({record.coop_id.name}, {record.date})'
            )

    def _get_housed_bird_count(self):
        """Aves vivas del lote en coop_id a la fecha date, sumando las asignaciones a
        galpón activas en ese momento (misma lógica que el resto del módulo usa para
        población histórica: aves ingresadas menos mortalidad registrada)."""
        self.ensure_one()
        lines = self.batch_id.coop_line_ids.filtered(
            lambda l: l.active and l.coop_id == self.coop_id
            and l.date_from <= self.date
            and (not l.date_to or l.date_to >= self.date)
        )
        return sum(line._get_live_bird_count_on(self.date) for line in lines)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records.filtered(lambda r: r.period == 'produccion' and not r.housed_bird_count):
            record.housed_bird_count = record._get_housed_bird_count()
        return records
