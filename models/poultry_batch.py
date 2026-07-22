# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import ValidationError

# Índice de día de la semana (convención Python: lunes = 0) para el parámetro
# de configuración poultry_management.week_start_day.
WEEK_START_INDEX = {
    'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
    'friday': 4, 'saturday': 5, 'sunday': 6,
}


class PoultryBatch(models.Model):
    _name = 'poultry.batch'
    _description = 'Lote de Aves'
    _order = 'birth_date desc'

    name = fields.Char(string='Nombre del Lote', required=True, index=True, default='Nuevo')
    code = fields.Char(string='Código', required=True, index=True, copy=False)
    birth_date = fields.Date(string='Fecha de Nacimiento', required=True, default=fields.Date.today)
    genetics_id = fields.Many2one('poultry.genetics', string='Genética', required=True)
    genetics_name = fields.Char(string='Genética', related='genetics_id.name', readonly=True, store=True)

    # Cantidad de aves (tamaño total del lote, independiente del galpón). Se calcula
    # solo a partir de los Movimientos de Aves de tipo Ingreso confirmados: un Traslado
    # no suma aves nuevas, solo las reubica entre galpones dentro del mismo lote.
    movement_ids = fields.One2many('poultry.batch.movement', 'batch_id', string='Movimientos de Aves')
    bird_count = fields.Integer(string='Cantidad de Aves', compute='_compute_bird_count', store=True)

    # Información adicional
    supplier_id = fields.Many2one('res.partner', string='Proveedor',
                                   domain="[('supplier_rank', '>', 0)]")
    notes = fields.Text(string='Notas')
    active = fields.Boolean(string='Activo', default=True)

    # Asignación a galpón(es): un lote puede no tener galpón asignado al darse de alta
    # y luego asignarse a uno o más galpones con fecha y cantidad, incluso en simultáneo.
    coop_line_ids = fields.One2many('poultry.batch.coop.line', 'batch_id',
                                     string='Asignaciones a Galpón')
    current_coop_ids = fields.Many2many('poultry.coop', string='Galpones Actuales',
                                         compute='_compute_current_coop_ids', store=True)
    live_bird_count = fields.Integer(string='Aves Vivas', compute='_compute_live_bird_count')

    # Relaciones con mortalidad
    mortality_ids = fields.One2many('poultry.mortality', 'batch_id', string='Registros de Mortalidad')
    mortality_count = fields.Integer(string='Registros de Mortalidad', compute='_compute_mortality_count')

    # Sanidad: planes de vacunación asignados (con historial) y aplicaciones de vacunas
    vaccination_plan_ids = fields.One2many('poultry.batch.vaccination.plan', 'batch_id',
                                           string='Planes de Vacunación')
    vaccination_ids = fields.One2many('poultry.vaccination', 'batch_id',
                                      string='Aplicaciones de Vacunas')
    vaccination_count = fields.Integer(string='Aplicaciones de Vacunas',
                                       compute='_compute_health_counts')

    # Pesajes de aves (partes de registro de peso)
    weight_record_ids = fields.One2many('poultry.weight.record', 'batch_id',
                                        string='Partes de Peso')
    weight_record_count = fields.Integer(string='Partes de Peso',
                                         compute='_compute_health_counts')

    # Edad del lote
    age_days = fields.Integer(string='Edad (días)', compute='_compute_age_days')
    age_weeks = fields.Integer(string='Edad (semanas)', compute='_compute_age_weeks')

    # Período de Crianza del lote (Crianza / Producción). El cambio de galpón (Recría
    # -> Productivo) y el cambio de Período son eventos independientes: un lote puede
    # trasladarse de galpón sin cambiar todavía de Período. El Período "real" es el
    # último Cambio de Período confirmado (poultry.batch.period.change); mientras no
    # haya ninguno, se sugiere por edad (period_suggested), igual que antes.
    period_change_ids = fields.One2many('poultry.batch.period.change', 'batch_id',
                                         string='Cambios de Período')
    period_suggested = fields.Selection([
        ('crianza', 'Crianza'),
        ('produccion', 'Producción'),
    ], string='Período Sugerido (por edad)', compute='_compute_period_suggested',
        help='Sugerencia automática según la Edad en Semanas y la Semana de Transición '
             'a Producción configurada en la Genética. No es el Período confirmado.')
    period = fields.Selection([
        ('crianza', 'Crianza'),
        ('produccion', 'Producción'),
    ], string='Período', compute='_compute_period',
        help='Último Cambio de Período confirmado para este lote. Si todavía no se '
             'registró ninguno, se usa el Período Sugerido por edad como valor '
             'provisorio.')

    # Aves Alojadas: la base fija de Huevos Acumulados Ave-Alojada. Se toma del
    # último Cambio de Período a Producción confirmado (ahí se calculó con la
    # población viva de ese galpón a esa fecha, ingresos y mortandad incluidos).
    production_start_date = fields.Date(string='Fecha de Entrada en Producción',
                                         compute='_compute_housed_info')
    housed_bird_count = fields.Integer(string='Aves Alojadas', compute='_compute_housed_info')

    @api.depends('birth_date')
    def _compute_age_days(self):
        """Calcula la edad del lote en días"""
        today = fields.Date.today()
        for batch in self:
            if batch.birth_date:
                batch.age_days = (today - batch.birth_date).days
            else:
                batch.age_days = 0

    @api.depends('birth_date')
    def _compute_age_weeks(self):
        """Calcula la Semana de Vida en curso del lote, numerada desde 1 y anclada
        según la configuración de inicio de semana (_poultry_week_anchor). Misma
        convención en todo el módulo."""
        today = fields.Date.today()
        for batch in self:
            batch.age_weeks = batch._poultry_week_of(today) if batch.birth_date else 0

    # -- Semana de Vida: ancla configurable -----------------------------------
    # Toda la numeración de Semanas de Vida del módulo (indicadores, agregados
    # semanales, reportes, mortandad, pesajes) pasa por estos helpers. Excepción
    # deliberada: la vacunación sigue anclada a la Fecha de Nacimiento (un plan de
    # "semana 6" significa 36-42 días de vida — edad biológica, no semana calendario).

    def _poultry_week_anchor(self):
        """Primer día de la Semana de Vida 1 del lote.

        Configurable en Ajustes (parámetro poultry_management.week_start_day):
        - 'birth' (predeterminado): ancla en la Fecha de Nacimiento (días 0-6 de
          vida = Semana 1, como en las guías de genética).
        - un día fijo de la semana (ej. 'monday'): la Semana 1 arranca el primer
          lunes desde el nacimiento, y todas las semanas cortan de lunes a domingo,
          igual que las planillas de la granja. Los días de vida anteriores a ese
          primer lunes se agrupan también en la Semana 1 (que puede ser más larga).
        """
        self.ensure_one()
        if not self.birth_date:
            return False
        start = self.env['ir.config_parameter'].sudo().get_param(
            'poultry_management.week_start_day', 'birth')
        index = WEEK_START_INDEX.get(start)
        if index is None:
            return self.birth_date
        return self.birth_date + timedelta(days=(index - self.birth_date.weekday()) % 7)

    def _poultry_week_of(self, target_date):
        """Semana de Vida (numerada desde 1) a la que pertenece target_date."""
        self.ensure_one()
        anchor = self._poultry_week_anchor()
        if not (anchor and target_date):
            return 0
        return max((target_date - anchor).days, 0) // 7 + 1

    def _poultry_week_start(self, week):
        """Primer día de la Semana de Vida indicada."""
        self.ensure_one()
        anchor = self._poultry_week_anchor()
        if not (anchor and week):
            return False
        return anchor + timedelta(days=(week - 1) * 7)

    def _poultry_week_end(self, week):
        """Último día de la Semana de Vida indicada."""
        start = self._poultry_week_start(week)
        return start + timedelta(days=6) if start else False

    @api.depends('age_weeks', 'genetics_id.rearing_end_week')
    def _compute_period_suggested(self):
        """Sugerencia de período según la edad y la genética (no confirmada)"""
        for batch in self:
            rearing_end_week = batch.genetics_id.rearing_end_week or 17
            batch.period_suggested = 'crianza' if batch.age_weeks <= rearing_end_week else 'produccion'

    @api.depends('period_change_ids.period', 'period_change_ids.date', 'period_change_ids.active',
                 'period_suggested')
    def _compute_period(self):
        """Período real: el último Cambio de Período confirmado; si no hay ninguno,
        se usa la sugerencia por edad como valor provisorio."""
        for batch in self:
            changes = batch.period_change_ids.filtered('active').sorted(
                key=lambda c: (c.date, c.id), reverse=True)
            batch.period = changes[0].period if changes else batch.period_suggested

    @api.depends('period_change_ids.period', 'period_change_ids.date', 'period_change_ids.active',
                 'period_change_ids.housed_bird_count')
    def _compute_housed_info(self):
        """Fecha de Entrada en Producción y Aves Alojadas: del último Cambio de
        Período a Producción confirmado para este lote."""
        for batch in self:
            changes = batch.period_change_ids.filtered(
                lambda c: c.active and c.period == 'produccion'
            ).sorted(key=lambda c: (c.date, c.id), reverse=True)
            if changes:
                batch.production_start_date = changes[0].date
                batch.housed_bird_count = changes[0].housed_bird_count
            else:
                batch.production_start_date = False
                batch.housed_bird_count = 0

    @api.depends('coop_line_ids.coop_id', 'coop_line_ids.date_to', 'coop_line_ids.active')
    def _compute_current_coop_ids(self):
        """Galpones donde el lote tiene aves asignadas vigentes (sin fecha de baja/traslado)"""
        for batch in self:
            active_lines = batch.coop_line_ids.filtered(lambda l: l.active and not l.date_to)
            batch.current_coop_ids = active_lines.mapped('coop_id')

    def _compute_live_bird_count(self):
        """Aves vivas del lote: suma de aves vivas de todas sus asignaciones vigentes.
        No se almacena porque depende de los registros de mortalidad (siempre al día)."""
        for batch in self:
            active_lines = batch.coop_line_ids.filtered(lambda l: l.active and not l.date_to)
            batch.live_bird_count = sum(active_lines.mapped('live_bird_count'))

    @api.depends('movement_ids.movement_type', 'movement_ids.state', 'movement_ids.bird_count')
    def _compute_bird_count(self):
        """Cantidad total de aves del lote: suma de los Ingresos confirmados (los
        Traslados no cambian el total, solo mueven aves ya existentes del lote)."""
        for batch in self:
            ingresos = batch.movement_ids.filtered(
                lambda m: m.movement_type == 'ingreso' and m.state == 'done'
            )
            batch.bird_count = sum(ingresos.mapped('bird_count'))

    @api.depends('mortality_ids')
    def _compute_mortality_count(self):
        """Cuenta la cantidad de registros de mortalidad"""
        for batch in self:
            batch.mortality_count = len(batch.mortality_ids)

    @api.depends('vaccination_ids', 'weight_record_ids')
    def _compute_health_counts(self):
        for batch in self:
            batch.vaccination_count = len(batch.vaccination_ids)
            batch.weight_record_count = len(batch.weight_record_ids)

    def action_view_vaccinations(self):
        self.ensure_one()
        return {
            'name': 'Aplicaciones de Vacunas - %s' % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.vaccination',
            'view_mode': 'list,form',
            'domain': [('batch_id', '=', self.id)],
            'context': {'default_batch_id': self.id},
        }

    def action_view_vaccination_compliance(self):
        self.ensure_one()
        return {
            'name': 'Cumplimiento de Vacunación - %s' % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.vaccination.compliance',
            'view_mode': 'list',
            'domain': [('batch_id', '=', self.id)],
            'context': {'search_default_active_assignment': 1},
        }

    def action_view_weight_records(self):
        self.ensure_one()
        return {
            'name': 'Partes de Peso - %s' % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.weight.record',
            'view_mode': 'list,form',
            'domain': [('batch_id', '=', self.id)],
            'context': {'default_batch_id': self.id},
        }

    @api.constrains('code')
    def _check_code_unique(self):
        """Valida que el código sea único"""
        for batch in self:
            if self.search_count([('code', '=', batch.code), ('id', '!=', batch.id)]) > 0:
                raise ValidationError(f'El código {batch.code} ya existe. Debe ser único.')

    @api.model_create_multi
    def create(self, vals_list):
        """Genera código y nombre automáticos si no se proporcionan."""
        for vals in vals_list:
            if not vals.get('code'):
                vals['code'] = self.env['ir.sequence'].next_by_code('poultry.batch') or 'NUEVO'
            if not vals.get('name') or vals.get('name') == 'Nuevo':
                genetics_name = (
                    self.env['poultry.genetics'].browse(vals.get('genetics_id')).name
                    if vals.get('genetics_id') else ''
                )
                birth_date = vals.get('birth_date', fields.Date.today())
                vals['name'] = f'{genetics_name} - {birth_date}'
        return super().create(vals_list)

    @api.depends('code', 'name', 'current_coop_ids.name')
    def _compute_display_name(self):
        """Personaliza el nombre mostrado."""
        for batch in self:
            name = f'{batch.code} - {batch.name}'
            if batch.current_coop_ids:
                coop_names = ', '.join(batch.current_coop_ids.mapped('name'))
                name += f' [{coop_names}]'
            batch.display_name = name

    def action_register_period_change(self):
        """Abre el formulario para registrar un Cambio de Período para este lote,
        preseleccionando el galpón actual si el lote está en uno solo."""
        self.ensure_one()
        default_coop_id = self.current_coop_ids[0].id if len(self.current_coop_ids) == 1 else False
        return {
            'name': 'Registrar Cambio de Período',
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.batch.period.change',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_batch_id': self.id,
                'default_coop_id': default_coop_id,
                'default_period': 'produccion' if self.period_suggested == 'produccion' else 'crianza',
            },
        }
