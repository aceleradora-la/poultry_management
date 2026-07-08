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
    # repartiendo el total del galpón entre los lotes presentes esa fecha. Los registros
    # históricos cargados a mano quedan con production_id vacío y siguen siendo válidos.
    production_id = fields.Many2one('mrp.production', string='OF Huevo sin Clasificar',
                                    ondelete='cascade', index=True, copy=False,
                                    help='OF de Huevo sin Clasificar (Cierre de Galpón) que generó '
                                         'este registro de mortandad.')
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True,
                               domain="[('active', '=', True)]", index=True)
    genetics_id = fields.Many2one('poultry.genetics', string='Genética', required=True)
    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves',
                                domain="[('current_coop_ids', '=', coop_id), ('genetics_id', '=', genetics_id), ('active', '=', True)]",
                                help='Lote específico de aves')
    date = fields.Date(string='Fecha', required=True, default=fields.Date.today, index=True)

    # Cantidad de aves muertas
    dead_count = fields.Integer(string='Cantidad de Aves Muertas', required=True, default=0)

    # Información calculada
    batch_age_weeks = fields.Integer(string='Edad del Lote (semanas)', compute='_compute_batch_age', store=True)

    # Campos de reporte (no almacenados): se calculan a partir de la asignación
    # (poultry.batch.coop.line) del lote en el galpón vigente a la fecha del registro.
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

    def _get_coop_line(self):
        """Asignación (poultry.batch.coop.line) del lote en el galpón vigente a la fecha
        del registro. Es la misma asignación que alimenta el cálculo de Aves Vivas."""
        self.ensure_one()
        if not (self.batch_id and self.coop_id and self.date):
            return self.env['poultry.batch.coop.line']
        return self.env['poultry.batch.coop.line'].search([
            ('batch_id', '=', self.batch_id.id),
            ('coop_id', '=', self.coop_id.id),
            ('active', '=', True),
            ('date_from', '<=', self.date),
            '|', ('date_to', '=', False), ('date_to', '>=', self.date),
        ], limit=1)

    def _compute_report_values(self):
        """Columnas de reporte: Aves Alojadas, Aves Vivas y % de mortandad del lote a la
        fecha del registro. Reusa poultry.batch.coop.line._get_live_bird_count_on (misma
        lógica de Aves Vivas de todo el módulo). % mortandad diaria = muertas del día /
        aves vivas al inicio del día * 100 (base = vivas al cierre del día + muertas)."""
        for record in self:
            line = record._get_coop_line()
            if not line:
                record.assigned_bird_count = 0
                record.live_bird_count = 0
                record.mortality_pct = 0.0
                continue
            record.assigned_bird_count = line.bird_count
            live = line._get_live_bird_count_on(record.date)
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
