# -*- coding: utf-8 -*-
"""Planes de Pesaje: cada cuántas semanas de vida se pesa un lote (pedido del usuario del
2026-11-12).

Un plan tiene tramos (desde semana, hasta semana, cada N semanas). Uno es el plan por
defecto de la granja y un lote puede usar otro. Las semanas que tocan forman una grilla
fija: con "hasta la 30 cada semana, de 30 a 40 cada 2, desde 40 cada 4" tocan la 17..30,
32, 34, 36, 38, 40, 44, 48... para un lote que ingresa al galpón en la semana 17. Si una
pesada se hace tarde queda registrada en la semana de vida real, pero la grilla no se
corre. El proceso diario que crea las pesadas planificadas vive en poultry.weight.record.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Hasta cuántas semanas hacia adelante se busca la próxima que toca (un lote de postura no
# vive tanto: es solo un tope para no iterar sin fin si el plan no tiene tramos abiertos).
MAX_WEEKS_AHEAD = 260


class PoultryWeightPlan(models.Model):
    _name = 'poultry.weight.plan'
    _description = 'Plan de Pesaje'
    _order = 'is_default desc, name'

    name = fields.Char(string='Nombre', required=True)
    active = fields.Boolean(string='Activo', default=True)
    is_default = fields.Boolean(
        string='Plan por defecto de la granja', copy=False,
        help='Lo usan todos los lotes que no tienen otro plan elegido. Hay uno solo.')
    send_mode = fields.Selection([
        ('auto', 'Se envía a pesar sola'),
        ('office', 'Espera a la oficina'),
    ], string='Cuando empieza la semana que toca', default='auto', required=True,
        help='Se envía a pesar sola: al empezar su semana de vida la pesada pasa a En Curso '
             'con las mismas jaulas y aves que la pesada anterior, y aparece en el celular. '
             'Espera a la oficina: queda Planificada hasta que alguien genere las líneas y '
             'la envíe a pesar.')
    line_ids = fields.One2many('poultry.weight.plan.line', 'plan_id', string='Tramos', copy=True)
    batch_count = fields.Integer(string='Lotes', compute='_compute_batch_count')
    preview = fields.Char(string='Semanas que tocan pesar', compute='_compute_preview',
                          help='Ejemplo para un lote que ingresa al galpón en la semana 17.')

    def _compute_batch_count(self):
        Batch = self.env['poultry.batch']
        for plan in self:
            plan.batch_count = Batch.search_count([('weight_plan_effective_id', '=', plan.id)])

    @api.depends('line_ids.week_from', 'line_ids.week_to', 'line_ids.interval')
    def _compute_preview(self):
        for plan in self:
            weeks = []
            week = 17
            while len(weeks) < 24:
                week = plan._poultry_next_due_week(week, 17)
                if not week:
                    break
                weeks.append(week)
                week += 1
            plan.preview = ', '.join(str(week) for week in weeks) + (' …' if len(weeks) == 24 else '')

    @api.model_create_multi
    def create(self, vals_list):
        plans = super().create(vals_list)
        plans.filtered('is_default')._poultry_keep_single_default()
        return plans

    def write(self, vals):
        result = super().write(vals)
        if vals.get('is_default'):
            self.filtered('is_default')._poultry_keep_single_default()
        if {'is_default', 'active', 'send_mode'} & set(vals):
            self._poultry_replan()
        return result

    def _poultry_keep_single_default(self):
        """Un solo plan por defecto: marcar uno desmarca los demás (si se marcan varios a la
        vez, queda el último)."""
        if not self:
            return
        keep = self[-1:]
        others = self.search([('is_default', '=', True), ('id', '!=', keep.id)])
        if others:
            super(PoultryWeightPlan, others).write({'is_default': False})
            others._poultry_replan()

    @api.model
    def _poultry_default_plan(self):
        return self.search([('is_default', '=', True)], limit=1)

    def _poultry_batches(self):
        """Lotes que usan estos planes (los elegidos y, para el plan por defecto, los que no
        eligieron ninguno)."""
        return self.env['poultry.batch'].search([('weight_plan_effective_id', 'in', self.ids)])

    def _poultry_replan(self):
        """Algo del plan cambió: se rehacen las pesadas planificadas que todavía no empezaron
        de sus lotes."""
        self.env['poultry.weight.record']._poultry_replan_batches(self._poultry_batches())

    # ------------------------------------------------------------------
    # La grilla de semanas
    # ------------------------------------------------------------------
    def _poultry_is_due(self, week, entry_week):
        """True si en la semana de vida `week` toca pesar a un lote que ingresó al galpón en
        la semana `entry_week`. Un tramo con "desde 0" arranca en el ingreso; los demás, en
        su semana "desde" (así la grilla es la misma para todos los lotes)."""
        self.ensure_one()
        if not week or week < entry_week:
            return False
        for line in self.line_ids:
            anchor = line.week_from if line.week_from > 0 else entry_week
            if week < max(anchor, entry_week):
                continue
            if line.week_to and week > line.week_to:
                continue
            if (week - anchor) % max(line.interval, 1) == 0:
                return True
        return False

    def _poultry_next_due_week(self, from_week, entry_week):
        """La primera semana desde `from_week` (incluida) que toca pesar, o 0."""
        self.ensure_one()
        for week in range(max(from_week, entry_week, 1), max(from_week, 1) + MAX_WEEKS_AHEAD):
            if self._poultry_is_due(week, entry_week):
                return week
        return 0

    def action_view_batches(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'poultry_management.action_poultry_weight_plan_batch')
        action['domain'] = [('weight_plan_effective_id', '=', self.id)]
        return action


class PoultryWeightPlanLine(models.Model):
    _name = 'poultry.weight.plan.line'
    _description = 'Tramo del Plan de Pesaje'
    _order = 'week_from, id'

    plan_id = fields.Many2one('poultry.weight.plan', string='Plan', required=True,
                              ondelete='cascade', index=True)
    week_from = fields.Integer(string='Desde semana',
                               help='Semana de vida desde la que rige el tramo. 0 = desde el '
                                    'ingreso del lote al galpón.')
    week_to = fields.Integer(string='Hasta semana',
                             help='Última semana de vida del tramo. 0 = hasta el fin del lote.')
    interval = fields.Integer(string='Cada (semanas)', default=1, required=True)

    @api.constrains('week_from', 'week_to', 'interval')
    def _check_weeks(self):
        for line in self:
            if line.interval < 1:
                raise ValidationError('Cada cuántas semanas se pesa tiene que ser 1 o más.')
            if line.week_from < 0 or line.week_to < 0:
                raise ValidationError('Las semanas del tramo no pueden ser negativas.')
            if line.week_to and line.week_to < line.week_from:
                raise ValidationError('El tramo termina antes de empezar (semana %d a %d).'
                                      % (line.week_from, line.week_to))

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.plan_id._poultry_replan()
        return lines

    def write(self, vals):
        plans = self.plan_id
        result = super().write(vals)
        (plans | self.plan_id)._poultry_replan()
        return result

    def unlink(self):
        plans = self.plan_id
        result = super().unlink()
        plans.exists()._poultry_replan()
        return result


class PoultryBatch(models.Model):
    _inherit = 'poultry.batch'

    weight_plan_id = fields.Many2one(
        'poultry.weight.plan', string='Plan de Pesaje',
        help='Vacío: usa el plan por defecto de la granja.')
    weight_plan_effective_id = fields.Many2one(
        'poultry.weight.plan', string='Plan que usa', compute='_compute_weight_plan_effective',
        search='_search_weight_plan_effective', compute_sudo=True)

    @api.depends('weight_plan_id')
    def _compute_weight_plan_effective(self):
        default = self.env['poultry.weight.plan']._poultry_default_plan()
        for batch in self:
            batch.weight_plan_effective_id = batch.weight_plan_id or default

    def _search_weight_plan_effective(self, operator, value):
        if operator not in ('=', 'in'):
            raise ValidationError('Búsqueda no soportada sobre el plan que usa el lote.')
        ids = [value] if operator == '=' else list(value)
        ids = [plan_id for plan_id in ids if plan_id]
        default = self.env['poultry.weight.plan']._poultry_default_plan()
        if not ids:
            # Lotes sin ningún plan: solo existen si no hay plan por defecto.
            return [('id', '=', 0)] if default else [('weight_plan_id', '=', False)]
        domain = [('weight_plan_id', 'in', ids)]
        if default and default.id in ids:
            domain = ['|', ('weight_plan_id', 'in', ids), ('weight_plan_id', '=', False)]
        return domain

    def _poultry_weight_plan(self):
        self.ensure_one()
        return self.weight_plan_effective_id

    def write(self, vals):
        result = super().write(vals)
        if 'weight_plan_id' in vals:
            self.env['poultry.weight.record']._poultry_replan_batches(self)
        return result
