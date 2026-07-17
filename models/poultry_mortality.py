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
                record.batch_age_weeks = days // 7 + 1
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
        records = super().create(vals_list)
        records._recompute_affected_housed()
        return records

    def write(self, vals):
        # Recalcular Aves Alojadas si cambia algo que afecte las aves vivas a la fecha
        # del Cambio de Período (cantidad, fecha, lote, galpón o baja lógica).
        trigger = bool({'dead_count', 'date', 'batch_id', 'coop_id', 'active'} & set(vals))
        batches = self.mapped('batch_id') if trigger else self.env['poultry.batch']
        result = super().write(vals)
        if trigger:
            self._recompute_affected_housed(batches | self.mapped('batch_id'))
        return result

    def unlink(self):
        batches = self.mapped('batch_id')
        result = super().unlink()
        self._recompute_affected_housed(batches)
        return result

    def _recompute_affected_housed(self, batches=None):
        """Recalcula las Aves Alojadas (housed_bird_count) de los Cambios de Período a
        Producción de los lotes afectados. Registrar, modificar o borrar mortandad
        ANTERIOR a la Fecha de Entrada en Producción cambia las aves vivas a esa fecha,
        que son la base fija Ave-Alojada; sin este recálculo la foto quedaría obsoleta.
        La mortandad POSTERIOR al cambio no altera el resultado (_get_housed_bird_count
        solo cuenta hasta la fecha del cambio), así que recalcular de más es inocuo:
        el guard 'si cambió' evita escrituras espurias (p. ej. durante el alta masiva
        de mortandad de una OF, cuya fecha es de producción)."""
        if batches is None:
            batches = self.mapped('batch_id')
        if not batches:
            return
        changes = self.env['poultry.batch.period.change'].search([
            ('batch_id', 'in', batches.ids),
            ('period', '=', 'produccion'),
            ('active', '=', True),
        ])
        for change in changes:
            new_val = change._get_housed_bird_count()
            if change.housed_bird_count != new_val:
                change.housed_bird_count = new_val

    @api.constrains('dead_count')
    def _check_dead_count(self):
        """Valida que la cantidad de aves muertas no sea negativa. La validación de que
        no supere las aves vivas se hace a nivel del total del galpón en
        mrp.production._poultry_sync_mortality, antes de repartir entre lotes."""
        for record in self:
            if record.dead_count < 0:
                raise ValidationError('La cantidad de aves muertas no puede ser negativa.')

    # -- Carga manual (grupo Mortandad: Carga Manual) --------------------------
    # Al cargar a mano día por día y por lote, ayudan a mantener coherente el
    # (galpón, genética, lote) reseteando el lote cuando cambia el galpón/genética.

    @api.onchange('coop_id')
    def _onchange_coop_id(self):
        """Al cambiar el galpón, limpiar genética y lote."""
        self.genetics_id = False
        self.batch_id = False

    @api.onchange('genetics_id', 'coop_id')
    def _onchange_genetics_coop(self):
        """Al cambiar genética o galpón, resetear el lote para respetar el dominio."""
        if self.coop_id and self.genetics_id:
            self.batch_id = False
