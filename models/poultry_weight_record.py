# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryWeightRecord(models.Model):
    _name = 'poultry.weight.record'
    _description = 'Parte de Registro de Peso de Aves'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, coop_id'

    name = fields.Char(string='Referencia', required=True, default='Nuevo',
                       copy=False, index=True)
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True,
                              domain="[('active', '=', True)]", index=True, tracking=True)
    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', required=True,
                               domain="[('current_coop_ids', '=', coop_id), ('active', '=', True)]",
                               index=True, tracking=True)
    date = fields.Date(string='Fecha', required=True, default=fields.Date.today,
                       index=True, tracking=True)
    operator_id = fields.Many2one('hr.employee', string='Operador',
                                  domain="[('active', '=', True)]")
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('done', 'Confirmado'),
        ('cancel', 'Cancelado'),
    ], string='Estado', default='draft', required=True, tracking=True, copy=False)
    line_ids = fields.One2many('poultry.weight.record.line', 'record_id', string='Pesos')
    notes = fields.Text(string='Notas')

    batch_age_weeks = fields.Integer(string='Edad del Lote (semanas)',
                                     compute='_compute_batch_age', store=True)

    # Banda de uniformidad: % de desvío respecto del promedio dentro del cual un ave
    # se considera "uniforme". El estándar de la industria es ±10%.
    uniformity_band_pct = fields.Float(string='Banda de Uniformidad (±%)', default=10.0)

    bird_count = fields.Integer(string='Aves Pesadas', compute='_compute_totals', store=True)
    total_weight_g = fields.Float(string='Peso Total (g)', compute='_compute_totals',
                                  store=True, digits=(16, 1))
    average_weight_g = fields.Float(string='Peso Promedio (g)', compute='_compute_totals',
                                    store=True, digits=(16, 1))
    uniformity_pct = fields.Float(string='Uniformidad (%)', compute='_compute_totals',
                                  store=True, digits=(16, 2))
    cv_pct = fields.Float(string='Coef. de Variación (%)', compute='_compute_totals',
                          store=True, digits=(16, 2))
    min_weight_g = fields.Float(string='Peso Mínimo (g)', compute='_compute_totals',
                                digits=(16, 1))
    max_weight_g = fields.Float(string='Peso Máximo (g)', compute='_compute_totals',
                                digits=(16, 1))

    @api.depends('batch_id', 'batch_id.birth_date', 'date')
    def _compute_batch_age(self):
        """Calcula la edad del lote en semanas al momento de la pesada"""
        for record in self:
            if record.batch_id and record.batch_id.birth_date and record.date:
                days = (record.date - record.batch_id.birth_date).days
                record.batch_age_weeks = days // 7
            else:
                record.batch_age_weeks = 0

    @api.depends('line_ids.weight_g', 'uniformity_band_pct')
    def _compute_totals(self):
        """Totales del parte: promedio, uniformidad (% de aves dentro de la banda
        respecto del promedio) y coeficiente de variación (desvío estándar
        poblacional / promedio)."""
        for record in self:
            weights = record.line_ids.mapped('weight_g')
            count = len(weights)
            record.bird_count = count
            if not count:
                record.total_weight_g = 0.0
                record.average_weight_g = 0.0
                record.uniformity_pct = 0.0
                record.cv_pct = 0.0
                record.min_weight_g = 0.0
                record.max_weight_g = 0.0
                continue
            total = sum(weights)
            avg = total / count
            record.total_weight_g = total
            record.average_weight_g = avg
            record.min_weight_g = min(weights)
            record.max_weight_g = max(weights)
            if avg:
                band = avg * (record.uniformity_band_pct or 10.0) / 100.0
                in_band = sum(1 for w in weights if abs(w - avg) <= band)
                record.uniformity_pct = in_band / count * 100.0
                variance = sum((w - avg) ** 2 for w in weights) / count
                record.cv_pct = (variance ** 0.5) / avg * 100.0
            else:
                record.uniformity_pct = 0.0
                record.cv_pct = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        """Genera referencia automática si no se proporciona (secuencia poultry.weight.record)."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == 'Nuevo':
                vals['name'] = self.env['ir.sequence'].next_by_code('poultry.weight.record') or 'NUEVO'
        return super().create(vals_list)

    @api.onchange('coop_id')
    def _onchange_coop_id(self):
        """Al cambiar el galpón, resetear el lote (y auto-seleccionarlo si hay uno solo)."""
        self.batch_id = False
        if self.coop_id:
            batches = self.env['poultry.batch'].search([
                ('current_coop_ids', '=', self.coop_id.id),
                ('active', '=', True),
            ])
            if len(batches) == 1:
                self.batch_id = batches

    def _get_coop_line(self):
        """Asignación (poultry.batch.coop.line) del lote en el galpón vigente a la fecha
        de la pesada. Misma lógica que poultry.mortality._get_coop_line."""
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

    def action_prefill_from_previous(self):
        """Precarga la estructura de jaulas/filas del último parte confirmado del mismo
        galpón, con peso en cero. Las filas sobrantes (aves muertas desde la pesada
        anterior) se borran a mano: esa ES la forma de reflejar la baja de la jaula."""
        self.ensure_one()
        if self.state != 'draft':
            raise ValidationError('Solo se puede precargar un parte en Borrador.')
        if self.line_ids:
            raise ValidationError('Solo se puede precargar un parte sin pesos cargados.')
        previous = self.search([
            ('coop_id', '=', self.coop_id.id),
            ('state', '=', 'done'),
            ('id', '!=', self.id),
        ], order='date desc, id desc', limit=1)
        if not previous:
            raise ValidationError('No hay un parte confirmado anterior de este galpón '
                                  'para precargar. Cargá las filas manualmente.')
        self.write({
            'line_ids': [(0, 0, {
                'cage_id': line.cage_id.id,
                'sequence': line.sequence,
                'weight_g': 0.0,
            }) for line in previous.line_ids.sorted(key=lambda l: (l.cage_id.sequence, l.cage_id.code, l.sequence, l.id))],
        })

    def action_done(self):
        """Confirma el parte y publica los indicadores Peso Corporal y Uniformidad."""
        for record in self:
            if record.state != 'draft':
                raise ValidationError('Solo se puede confirmar un parte en Borrador.')
            if not record.line_ids:
                raise ValidationError('El parte no tiene pesos cargados.')
            zero_lines = record.line_ids.filtered(lambda l: l.weight_g <= 0)
            if zero_lines:
                cages = ', '.join(sorted(set(zero_lines.mapped('cage_id.name'))))
                raise ValidationError(
                    'Hay filas con peso en cero o negativo (jaulas: %s). Completá el peso '
                    'o borrá la fila si el ave ya no está.' % cages)
            if record.date > fields.Date.today():
                raise ValidationError('La fecha de la pesada no puede ser futura.')
            if not record._get_coop_line():
                raise ValidationError(
                    'El lote %s no tiene una asignación vigente en el galpón %s a la '
                    'fecha %s.' % (record.batch_id.name, record.coop_id.name, record.date))
        self.write({'state': 'done'})
        self._poultry_apply_indicator_values()

    def action_cancel(self):
        for record in self:
            if record.state not in ('draft', 'done'):
                raise ValidationError('Solo se puede cancelar un parte en Borrador o Confirmado.')
        was_done = self.filtered(lambda r: r.state == 'done')
        self.write({'state': 'cancel'})
        # Recalcular desde los partes confirmados restantes del mismo lote y fecha
        # (o limpiar los valores si este era el último).
        was_done._poultry_apply_indicator_values()

    def action_draft(self):
        for record in self:
            if record.state != 'cancel':
                raise ValidationError('Solo se puede volver a Borrador un parte Cancelado.')
        self.write({'state': 'draft'})

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done(self):
        for record in self:
            if record.state == 'done':
                raise ValidationError(
                    'No se puede eliminar un parte Confirmado. Cancelalo primero.')

    def _poultry_apply_indicator_values(self):
        """Publica (o limpia) los Valores Reales de los indicadores Peso Corporal y
        Uniformidad para cada (lote, fecha) tocado por estos partes.

        Como el valor real es único por (lote, indicador, fecha) y un lote puede pesarse
        el mismo día en más de un galpón, siempre se agregan TODOS los partes confirmados
        del lote en esa fecha (no solo self): promedio ponderado por ave y uniformidad
        recalculada contra la media combinada.

        Se guarda numerator=gramos totales y denominator=aves pesadas para que el rollup
        semanal (accumulation_type='none') pondere correctamente pesadas múltiples en la
        misma semana, en vez de promediar promedios.

        IMPORTANTE: las categorías weight/uniformity NO deben agregarse a la lista de
        _poultry_rebuild_all_indicator_values (poultry_coop_close.py): ese rebuild
        borraría estos valores y solo sabe recalcular desde OFs de Huevo sin Clasificar.
        Los partes de peso son la única fuente de estas dos categorías.

        Se usa sudo() acotado sobre los modelos de valores para que el Usuario Avícola
        (solo lectura sobre indicadores) pueda confirmar sus propios partes."""
        Indicator = self.env['poultry.indicator'].sudo()
        Value = self.env['poultry.batch.indicator.value'].sudo()
        Weekly = self.env['poultry.batch.indicator.weekly.value'].sudo()
        weight_indicator = Indicator.search([
            ('category', '=', 'weight'),
            ('accumulation_type', '=', 'none'),
            ('active', '=', True),
        ], limit=1)
        uniformity_indicator = Indicator.search([
            ('category', '=', 'uniformity'),
            ('accumulation_type', '=', 'none'),
            ('active', '=', True),
        ], limit=1)
        indicators = weight_indicator | uniformity_indicator
        if not indicators:
            # Sin indicadores configurados no hay dónde publicar: se omite en silencio
            # (misma convención que los cálculos de mrp_production).
            return

        pairs = {(record.batch_id.id, record.date): record.batch_id for record in self}
        for (batch_id, target_date), batch in pairs.items():
            siblings = self.search([
                ('batch_id', '=', batch_id),
                ('date', '=', target_date),
                ('state', '=', 'done'),
            ])
            lines = siblings.mapped('line_ids')
            if lines:
                weights = lines.mapped('weight_g')
                birds = len(weights)
                total_g = sum(weights)
                avg_g = total_g / birds
                coop = siblings.sorted(key=lambda r: r.id)[-1].coop_id
                if weight_indicator:
                    Value._set_value(batch, coop, target_date, weight_indicator, avg_g,
                                     numerator=total_g, denominator=birds)
                if uniformity_indicator:
                    in_band = 0
                    for line in lines:
                        band_pct = line.record_id.uniformity_band_pct or 10.0
                        if avg_g and abs(line.weight_g - avg_g) <= avg_g * band_pct / 100.0:
                            in_band += 1
                    Value._set_value(batch, coop, target_date, uniformity_indicator,
                                     in_band / birds * 100.0,
                                     numerator=in_band * 100.0, denominator=birds)
            else:
                # Se canceló el último parte del día: borrar los valores diarios y
                # limpiar/recalcular el semanal a mano, porque _recompute_weekly_value
                # no hace nada cuando la semana queda sin valores diarios (mismo motivo
                # que la limpieza de _poultry_rebuild_all_indicator_values).
                Value.search([
                    ('batch_id', '=', batch_id),
                    ('indicator_id', 'in', indicators.ids),
                    ('date', '=', target_date),
                ]).unlink()
                birth_date = batch.birth_date
                if not birth_date or target_date < birth_date:
                    continue
                week = (target_date - birth_date).days // 7
                week_date_from = birth_date + timedelta(days=week * 7)
                week_date_to = week_date_from + timedelta(days=6)
                for indicator in indicators:
                    remaining = Value.search([
                        ('batch_id', '=', batch_id),
                        ('indicator_id', '=', indicator.id),
                        ('date', '>=', week_date_from),
                        ('date', '<=', week_date_to),
                    ], limit=1)
                    if remaining:
                        Value._recompute_weekly_value(batch, indicator, target_date)
                    else:
                        weekly_domain = [
                            ('batch_id', '=', batch_id),
                            ('indicator_id', '=', indicator.id),
                            ('week', '=', week),
                        ]
                        # Solo se borra el semanal de Origen=Sistema: uno Manual es un
                        # dato histórico cargado a mano y no depende de estos partes.
                        # El campo source llega con el port de "carga manual de valores
                        # semanales históricos"; el guard permite que ambos ports
                        # aterricen en 19.0 en cualquier orden.
                        if 'source' in Weekly._fields:
                            weekly_domain.append(('source', '=', 'system'))
                        Weekly.search(weekly_domain).unlink()
