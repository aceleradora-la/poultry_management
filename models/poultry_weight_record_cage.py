# -*- coding: utf-8 -*-

from odoo import models, fields, api, tools


class PoultryWeightRecordCage(models.Model):
    """Resumen por jaula de cada Parte de Peso: una fila por (parte, jaula), calculada
    en SQL sobre las líneas con peso. Alimenta la solapa Por Jaula, las tarjetas del
    celular y el pivote de evolución por jaula."""
    _name = 'poultry.weight.record.cage'
    _description = 'Resumen por Jaula del Parte de Peso'
    _auto = False
    _order = 'record_id, cage_sequence, row_no, side_no, bay_no, floor_no, cage_no, cage_code'

    record_id = fields.Many2one('poultry.weight.record', string='Parte de Peso', readonly=True)
    cage_id = fields.Many2one('poultry.cage', string='Jaula', readonly=True)
    cage_code = fields.Char(string='Código', readonly=True)
    coop_id = fields.Many2one('poultry.coop', string='Galpón', readonly=True)
    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', readonly=True)
    date = fields.Date(string='Fecha', readonly=True)
    batch_age_weeks = fields.Integer(string='Semana de Vida', readonly=True, aggregator=None)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('in_progress', 'En Curso'),
        ('registered', 'Registrado'),
        ('done', 'Confirmado'),
        ('cancel', 'Cancelado'),
    ], string='Estado', readonly=True)
    cage_sequence = fields.Integer(readonly=True, aggregator=None)
    row_no = fields.Integer(string='Fila', readonly=True, aggregator=None)
    side_no = fields.Integer(string='Lado', readonly=True, aggregator=None)
    bay_no = fields.Integer(string='Claro', readonly=True, aggregator=None)
    floor_no = fields.Integer(string='Piso', readonly=True, aggregator=None)
    cage_no = fields.Integer(string='Jaula N°', readonly=True, aggregator=None)

    line_count = fields.Integer(string='Aves Previstas', readonly=True)
    bird_count = fields.Integer(string='Aves Pesadas', readonly=True)
    average_weight_g = fields.Float(string='Peso Promedio (g)', readonly=True, digits=(16, 1),
                                    aggregator='avg')
    min_weight_g = fields.Float(string='Peso Mínimo (g)', readonly=True, digits=(16, 1),
                                aggregator='min')
    max_weight_g = fields.Float(string='Peso Máximo (g)', readonly=True, digits=(16, 1),
                                aggregator='max')
    cv_pct = fields.Float(string='Coef. de Variación (%)', readonly=True, digits=(16, 1),
                          aggregator='avg')

    deviation_pct = fields.Float(string='Desvío vs Parte (%)', compute='_compute_analysis',
                                 digits=(16, 1))
    previous_average_g = fields.Float(string='Pesada Anterior (g)', compute='_compute_analysis',
                                      digits=(16, 1))
    is_closed = fields.Boolean(string='Cerrada', compute='_compute_analysis')
    alert = fields.Char(string='Aviso', compute='_compute_analysis')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT min(l.id) AS id,
                       l.record_id,
                       l.cage_id,
                       r.coop_id,
                       r.batch_id,
                       r.date,
                       r.batch_age_weeks,
                       r.state,
                       c.sequence AS cage_sequence,
                       c.row_no, c.side_no, c.bay_no, c.floor_no, c.cage_no,
                       c.code AS cage_code,
                       count(*) AS line_count,
                       count(*) FILTER (WHERE l.weight_g > 0) AS bird_count,
                       coalesce(avg(l.weight_g) FILTER (WHERE l.weight_g > 0), 0) AS average_weight_g,
                       coalesce(min(l.weight_g) FILTER (WHERE l.weight_g > 0), 0) AS min_weight_g,
                       coalesce(max(l.weight_g) FILTER (WHERE l.weight_g > 0), 0) AS max_weight_g,
                       CASE WHEN avg(l.weight_g) FILTER (WHERE l.weight_g > 0) > 0
                            THEN stddev_pop(l.weight_g) FILTER (WHERE l.weight_g > 0)
                                 / avg(l.weight_g) FILTER (WHERE l.weight_g > 0) * 100
                            ELSE 0 END AS cv_pct
                FROM poultry_weight_record_line l
                JOIN poultry_weight_record r ON r.id = l.record_id
                JOIN poultry_cage c ON c.id = l.cage_id
                GROUP BY l.record_id, l.cage_id, r.coop_id, r.batch_id, r.date,
                         r.batch_age_weeks, r.state, c.sequence, c.row_no, c.side_no,
                         c.bay_no, c.floor_no, c.cage_no, c.code
            )
        """ % self._table)

    @api.model
    def _poultry_flush_sources(self):
        """La vista lee las tablas: lo escrito en caché tiene que estar en la base. No
        invalida esta caché a propósito: se llama desde los computes de esta vista."""
        self.env['poultry.weight.record'].flush_model(['state', 'date', 'coop_id', 'batch_id',
                                                       'batch_age_weeks', 'closed_cage_ids'])
        self.env['poultry.weight.record.line'].flush_model()

    def _poultry_previous_summary(self):
        """La misma jaula en el último parte registrado o confirmado anterior del galpón."""
        self.ensure_one()
        self._poultry_flush_sources()
        return self.search([
            ('cage_id', '=', self.cage_id.id),
            ('record_id', '!=', self.record_id.id),
            ('state', 'in', ('registered', 'done')),
            ('date', '<=', self.date),
            ('bird_count', '>', 0),
        ], order='date desc, record_id desc', limit=1)

    @api.depends('average_weight_g', 'cv_pct', 'bird_count', 'line_count',
                 'record_id.average_weight_g', 'record_id.closed_cage_ids')
    def _compute_analysis(self):
        Record = self.env['poultry.weight.record']
        for row in self:
            record_avg = row.record_id.average_weight_g
            row.deviation_pct = ((row.average_weight_g - record_avg) / record_avg * 100.0
                                 if record_avg and row.bird_count else 0.0)
            previous = row._poultry_previous_summary()
            row.previous_average_g = previous.average_weight_g if previous else 0.0
            row.is_closed = row.cage_id in row.record_id.closed_cage_ids
            alerts = []
            if not row.bird_count:
                alerts.append('sin pesar')
            else:
                if abs(row.deviation_pct) > Record.CAGE_DEVIATION_ALERT_PCT:
                    alerts.append('se aparta %.1f %% del parte' % abs(row.deviation_pct))
                if row.cv_pct > Record.CAGE_CV_ALERT_PCT:
                    alerts.append('CV %.1f %%' % row.cv_pct)
                if row.bird_count < row.line_count:
                    alerts.append('%d de %d aves' % (row.bird_count, row.line_count))
            row.alert = ' · '.join(alerts)
