# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError

from .poultry_vaccine import VACCINE_ROUTES


class PoultryVaccination(models.Model):
    _name = 'poultry.vaccination'
    _description = 'Aplicación de Vacuna'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Referencia', required=True, default='Nuevo',
                       copy=False, index=True)
    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', required=True,
                               index=True, tracking=True,
                               domain="[('active', '=', True)]")
    # Galpón opcional: vacío significa que la aplicación abarcó todo el lote (ej. vacuna
    # en agua de bebida aplicada en todos sus galpones a la vez). Si se aplica galpón
    # por galpón, se carga un registro por galpón.
    coop_id = fields.Many2one('poultry.coop', string='Galpón', tracking=True,
                              domain="[('id', 'in', allowed_coop_ids)]")
    allowed_coop_ids = fields.Many2many('poultry.coop', compute='_compute_allowed',
                                        string='Galpones del Lote')
    date = fields.Date(string='Fecha de Aplicación', required=True,
                       default=fields.Date.today, index=True, tracking=True)
    vaccine_id = fields.Many2one('poultry.vaccine', string='Vacuna', required=True,
                                 ondelete='restrict', tracking=True,
                                 domain="[('active', '=', True)]")
    plan_line_id = fields.Many2one('poultry.vaccination.plan.line',
                                   string='Línea de Plan que Cumple',
                                   ondelete='restrict',
                                   domain="[('plan_id', 'in', assigned_plan_ids)]",
                                   help='Línea del plan de vacunación asignado al lote que '
                                        'esta aplicación cumple. Puede dejarse vacía para '
                                        'aplicaciones fuera de plan (refuerzos), que no '
                                        'cuentan para el Cumplimiento de Vacunación.')
    assigned_plan_ids = fields.Many2many('poultry.vaccination.plan',
                                         compute='_compute_allowed',
                                         string='Planes Asignados')
    route = fields.Selection(VACCINE_ROUTES, string='Vía de Aplicación', tracking=True)
    dose = fields.Char(string='Dosis Aplicada')
    lot_number = fields.Char(string='Nº de Partida/Lote del Producto', tracking=True,
                             help='Número de partida del frasco/envase aplicado, tal como '
                                  'figura en la etiqueta. Las vacunas no se manejan como '
                                  'stock en Odoo: es un dato de registro sanitario.')
    expiry_date = fields.Date(string='Vencimiento de la Partida')
    laboratory = fields.Char(string='Laboratorio')
    applied_by_id = fields.Many2one('hr.employee', string='Aplicado por',
                                    domain="[('active', '=', True)]")
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('done', 'Aplicada'),
        ('cancel', 'Cancelada'),
    ], string='Estado', default='draft', required=True, tracking=True, copy=False)
    observations = fields.Text(string='Observaciones')

    batch_age_weeks = fields.Integer(string='Edad del Lote (semanas)',
                                     compute='_compute_batch_age', store=True)
    bird_count = fields.Integer(string='Aves Vivas', compute='_compute_bird_count',
                                help='Aves vivas del lote (o del galpón elegido) a la '
                                     'fecha de aplicación. Informativo.')

    @api.depends('batch_id', 'batch_id.birth_date', 'date')
    def _compute_batch_age(self):
        """Edad del lote en semanas a la fecha de aplicación"""
        for record in self:
            if record.batch_id and record.batch_id.birth_date and record.date:
                days = (record.date - record.batch_id.birth_date).days
                record.batch_age_weeks = days // 7
            else:
                record.batch_age_weeks = 0

    @api.depends('batch_id', 'batch_id.current_coop_ids', 'date')
    def _compute_allowed(self):
        """Dominios dependientes del lote: sus galpones actuales y las líneas de los
        planes con asignación vigente a la fecha de aplicación."""
        Assignment = self.env['poultry.batch.vaccination.plan']
        for record in self:
            record.allowed_coop_ids = record.batch_id.current_coop_ids
            if not record.batch_id:
                record.assigned_plan_ids = False
                continue
            target_date = record.date or fields.Date.today()
            assignments = Assignment.search([
                ('batch_id', '=', record.batch_id.id),
                ('date_from', '<=', target_date),
                '|', ('date_to', '=', False), ('date_to', '>=', target_date),
            ])
            record.assigned_plan_ids = assignments.mapped('plan_id')

    def _compute_bird_count(self):
        """Aves vivas a la fecha, reusando la lógica central de
        poultry.batch.coop.line._get_live_bird_count_on."""
        for record in self:
            if not (record.batch_id and record.date):
                record.bird_count = 0
                continue
            lines = record.batch_id.coop_line_ids.filtered(
                lambda l: l.active and l.date_from and l.date_from <= record.date
                and (not l.date_to or l.date_to >= record.date))
            if record.coop_id:
                lines = lines.filtered(lambda l: l.coop_id == record.coop_id)
            record.bird_count = sum(line._get_live_bird_count_on(record.date)
                                    for line in lines)

    @api.model_create_multi
    def create(self, vals_list):
        """Genera referencia automática si no se proporciona (secuencia poultry.vaccination)."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == 'Nuevo':
                vals['name'] = self.env['ir.sequence'].next_by_code('poultry.vaccination') or 'NUEVO'
        return super().create(vals_list)

    @api.onchange('vaccine_id')
    def _onchange_vaccine_id(self):
        """Propone vía, dosis y laboratorio habituales de la vacuna, y auto-sugiere la
        línea de plan que corresponde a la semana de vida actual del lote."""
        if self.vaccine_id:
            self.route = self.vaccine_id.default_route
            self.dose = self.vaccine_id.default_dose
            self.laboratory = self.vaccine_id.laboratory
        self._suggest_plan_line()

    @api.onchange('batch_id', 'date')
    def _onchange_batch_date(self):
        if self.coop_id and self.coop_id not in self.batch_id.current_coop_ids:
            self.coop_id = False
        self._suggest_plan_line()

    def _suggest_plan_line(self):
        """Si aún no se eligió línea de plan, sugiere la línea de un plan asignado con
        la misma vacuna y semana de vida igual a la edad del lote a la fecha."""
        if self.plan_line_id or not (self.batch_id and self.vaccine_id and self.date):
            return
        line = self.env['poultry.vaccination.plan.line'].search([
            ('plan_id', 'in', self.assigned_plan_ids.ids),
            ('vaccine_id', '=', self.vaccine_id.id),
            ('week', '=', self.batch_age_weeks),
        ], limit=1)
        if line:
            self.plan_line_id = line
            if line.route:
                self.route = line.route
            if line.dose:
                self.dose = line.dose

    @api.onchange('plan_line_id')
    def _onchange_plan_line_id(self):
        """Al elegir una línea de plan a mano, completar vacuna/vía/dosis desde ella."""
        if self.plan_line_id:
            self.vaccine_id = self.plan_line_id.vaccine_id
            if self.plan_line_id.route:
                self.route = self.plan_line_id.route
            if self.plan_line_id.dose:
                self.dose = self.plan_line_id.dose

    @api.constrains('plan_line_id', 'vaccine_id')
    def _check_plan_line_vaccine(self):
        for record in self:
            if record.plan_line_id and record.plan_line_id.vaccine_id != record.vaccine_id:
                raise ValidationError(
                    'La línea de plan elegida corresponde a la vacuna %s, no a %s.'
                    % (record.plan_line_id.vaccine_id.name, record.vaccine_id.name))

    def action_done(self):
        for record in self:
            if record.state != 'draft':
                raise ValidationError('Solo se puede confirmar una aplicación en Borrador.')
            if record.batch_id.birth_date and record.date < record.batch_id.birth_date:
                raise ValidationError(
                    'La fecha de aplicación es anterior al nacimiento del lote %s.'
                    % record.batch_id.name)
            if record.expiry_date and record.expiry_date < record.date:
                raise ValidationError(
                    'La partida %s está vencida (%s) a la fecha de aplicación. Verificá '
                    'el vencimiento cargado.' % (record.lot_number or 's/n', record.expiry_date))
        self.write({'state': 'done'})

    def action_cancel(self):
        for record in self:
            if record.state not in ('draft', 'done'):
                raise ValidationError('Solo se puede cancelar una aplicación en Borrador o Aplicada.')
        self.write({'state': 'cancel'})

    def action_draft(self):
        for record in self:
            if record.state != 'cancel':
                raise ValidationError('Solo se puede volver a Borrador una aplicación Cancelada.')
        self.write({'state': 'draft'})

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done(self):
        for record in self:
            if record.state == 'done':
                raise ValidationError(
                    'No se puede eliminar una aplicación confirmada. Cancelala primero.')
