# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryMortality(models.Model):
    _name = 'poultry.mortality'
    _description = 'Registro de Aves Muertas'
    _order = 'date desc, coop_id'

    name = fields.Char(string='Referencia', required=True, default='Nuevo Registro', copy=False, index=True)
    # OF de Huevo sin Clasificar (Cierre de Galpón) que generó este registro. Las filas
    # se crean/actualizan automáticamente desde mrp.production._poultry_sync_mortality,
    # repartiendo el total del galpón entre los lotes del galpón. Los registros históricos
    # cargados a mano quedan con production_id vacío y siguen siendo válidos.
    production_id = fields.Many2one('mrp.production', string='OF Huevo sin Clasificar',
                                    ondelete='cascade', index=True, copy=False,
                                    help='OF de Huevo sin Clasificar (Cierre de Galpón) que generó '
                                         'este registro de mortandad.')
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True,
                               domain="[('active', '=', True)]", index=True)
    genetics_id = fields.Many2one('poultry.genetics', string='Genética', required=True)
    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves',
                                domain="[('coop_id', '=', coop_id), ('genetics_id', '=', genetics_id), ('active', '=', True)]",
                                help='Lote específico de aves')
    date = fields.Date(string='Fecha', required=True, default=fields.Date.today, index=True)

    # Cantidad de aves muertas
    dead_count = fields.Integer(string='Cantidad de Aves Muertas', required=True, default=0)

    # Información calculada
    batch_age_weeks = fields.Integer(string='Edad del Lote (semanas)', compute='_compute_batch_age', store=True)

    # Campos de reporte (no almacenados): Aves Alojadas, Aves Vivas y % de mortandad del
    # lote a la fecha del registro. En 19.0 el lote pertenece a un galpón (poultry.batch.coop_id)
    # y no hay conteo por fecha, así que las aves vivas se calculan como la cantidad de aves
    # del lote menos la mortandad acumulada hasta la fecha.
    assigned_bird_count = fields.Integer(string='Aves Alojadas', compute='_compute_report_values')
    live_bird_count = fields.Integer(string='Aves Vivas', compute='_compute_report_values')
    mortality_pct = fields.Float(string='% Mortandad', compute='_compute_report_values', digits=(16, 4))

    # Notas
    notes = fields.Text(string='Notas')
    active = fields.Boolean(string='Activo', default=True)

    @api.depends('batch_id', 'batch_id.birth_date', 'date')
    def _compute_batch_age(self):
        """Calcula la edad del lote en semanas al momento del registro"""
        for record in self:
            if record.batch_id and record.batch_id.birth_date and record.date:
                days = (record.date - record.batch_id.birth_date).days
                record.batch_age_weeks = days // 7
            else:
                record.batch_age_weeks = 0

    def _get_cumulative_dead(self, batch, date):
        """Aves muertas acumuladas del lote hasta la fecha (inclusive), según los
        registros activos de poultry.mortality."""
        if not (batch and date):
            return 0
        deaths = self.search([
            ('batch_id', '=', batch.id),
            ('active', '=', True),
            ('date', '<=', date),
        ])
        return sum(deaths.mapped('dead_count'))

    def _compute_report_values(self):
        """Columnas de reporte: Aves Alojadas, Aves Vivas y % de mortandad del lote a la
        fecha del registro. % mortandad diaria = muertas del día / aves vivas al inicio
        del día * 100 (base = vivas al cierre del día + muertas del día)."""
        for record in self:
            batch = record.batch_id
            if not batch:
                record.assigned_bird_count = 0
                record.live_bird_count = 0
                record.mortality_pct = 0.0
                continue
            record.assigned_bird_count = batch.bird_count
            dead_cumulative = record._get_cumulative_dead(batch, record.date)
            live = max(batch.bird_count - dead_cumulative, 0)
            record.live_bird_count = live
            base = live + record.dead_count
            record.mortality_pct = (record.dead_count / base * 100.0) if base > 0 else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        """Genera referencia automática si no se proporciona (secuencia poultry.mortality)."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == 'Nuevo Registro':
                vals['name'] = self.env['ir.sequence'].next_by_code('poultry.mortality') or 'NUEVO'
        return super().create(vals_list)

    @api.constrains('dead_count')
    def _check_dead_count(self):
        """Valida que la cantidad de aves muertas no sea negativa. La validación de que
        no supere las aves vivas se hace a nivel del total del galpón en
        mrp.production._poultry_sync_mortality, antes de repartir entre lotes."""
        for record in self:
            if record.dead_count < 0:
                raise ValidationError('La cantidad de aves muertas no puede ser negativa.')
