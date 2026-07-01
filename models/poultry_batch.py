# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


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
    # (todavía no manejamos el proceso de Recría) y luego asignarse a uno o más galpones
    # con fecha y cantidad, incluso en simultáneo.
    coop_line_ids = fields.One2many('poultry.batch.coop.line', 'batch_id',
                                     string='Asignaciones a Galpón')
    current_coop_ids = fields.Many2many('poultry.coop', string='Galpones Actuales',
                                         compute='_compute_current_coop_ids', store=True)
    live_bird_count = fields.Integer(string='Aves Vivas', compute='_compute_live_bird_count')

    # Relaciones con mortalidad
    mortality_ids = fields.One2many('poultry.mortality', 'batch_id', string='Registros de Mortalidad')
    mortality_count = fields.Integer(string='Registros de Mortalidad', compute='_compute_mortality_count')

    # Edad del lote
    age_days = fields.Integer(string='Edad (días)', compute='_compute_age_days')
    age_weeks = fields.Integer(string='Edad (semanas)', compute='_compute_age_weeks')

    # Período de Crianza del lote (Crianza / Producción)
    period = fields.Selection([
        ('crianza', 'Crianza'),
        ('produccion', 'Producción'),
    ], string='Período', compute='_compute_period',
        help='Se calcula automáticamente según la Edad en Semanas y la Semana de '
             'Transición a Producción configurada en la Genética del lote.')

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
        """Calcula la edad del lote en semanas cerradas (semana completa desde el nacimiento)"""
        today = fields.Date.today()
        for batch in self:
            if batch.birth_date:
                days = (today - batch.birth_date).days
                batch.age_weeks = days // 7
            else:
                batch.age_weeks = 0

    @api.depends('age_weeks', 'genetics_id.rearing_end_week')
    def _compute_period(self):
        """Determina el período (Crianza/Producción) según la edad y la genética"""
        for batch in self:
            rearing_end_week = batch.genetics_id.rearing_end_week or 17
            batch.period = 'crianza' if batch.age_weeks <= rearing_end_week else 'produccion'

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

    def name_get(self):
        """Personaliza el nombre mostrado"""
        result = []
        for batch in self:
            name = f'{batch.code} - {batch.name}'
            if batch.current_coop_ids:
                coop_names = ', '.join(batch.current_coop_ids.mapped('name'))
                name += f' [{coop_names}]'
            result.append((batch.id, name))
        return result
