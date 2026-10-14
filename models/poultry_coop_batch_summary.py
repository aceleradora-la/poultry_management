# -*- coding: utf-8 -*-

from odoo import fields, models, tools


class PoultryCoopBatchSummary(models.Model):
    """Resumen de lectura: UNA fila por lote que pasó por el galpón.

    Las líneas de asignación (poultry.batch.coop.line) son la maquinaria de las
    aves vivas: cada Retiro/Traslado parcial cierra la vigente y crea un
    remanente, así que un mismo lote acumula varias líneas técnicas. Esta vista
    SQL las agrupa para la solapa "Lotes de Aves" del galpón; el detalle crudo
    queda en su propia solapa, solo para administradores.

    Las Aves Ingresadas salen de los MOVIMIENTOS de llegada (Ingreso/Traslado
    con destino este galpón) — la misma fuente que alimenta las Aves Alojadas —
    con fallback a la primera línea para lotes anteriores a los movimientos.
    No alimenta ningún cálculo: Aves Alojadas e indicadores no pasan por acá.
    """
    _name = 'poultry.coop.batch.summary'
    _description = 'Resumen de Lotes por Galpón'
    _auto = False
    _order = 'is_active desc, first_entry_date desc'
    _rec_name = 'batch_id'

    coop_id = fields.Many2one('poultry.coop', string='Galpón', readonly=True)
    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', readonly=True)
    first_entry_date = fields.Date(string='Primer Ingreso', readonly=True)
    last_exit_date = fields.Date(string='Último Egreso', readonly=True)
    entered_bird_count = fields.Integer(string='Aves Ingresadas', readonly=True)
    is_active = fields.Boolean(string='Activo', readonly=True,
                               help='El lote todavía tiene aves asignadas en este galpón. '
                                    'Se apaga solo cuando sale el último remanente.')
    dead_count = fields.Integer(string='Aves Muertas', compute='_compute_counts',
                                help='Mortandad del lote en este galpón.')
    live_bird_count = fields.Integer(string='Aves Vivas', compute='_compute_counts')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    min(l.id) AS id,
                    l.coop_id,
                    l.batch_id,
                    COALESCE(mi.first_date, min(l.date_from)) AS first_entry_date,
                    mo.last_date AS last_exit_date,
                    COALESCE(mi.total_birds,
                             (array_agg(l.bird_count ORDER BY l.date_from, l.id))[1]
                    ) AS entered_bird_count,
                    bool_or(l.active AND l.date_to IS NULL) AS is_active
                FROM poultry_batch_coop_line l
                LEFT JOIN (
                    SELECT batch_id, dest_coop_id AS coop_id,
                           min(date) AS first_date, sum(bird_count) AS total_birds
                    FROM poultry_batch_movement
                    WHERE movement_type IN ('ingreso', 'traslado')
                      AND state = 'done' AND active
                    GROUP BY batch_id, dest_coop_id
                ) mi ON mi.batch_id = l.batch_id AND mi.coop_id = l.coop_id
                LEFT JOIN (
                    SELECT batch_id, origin_coop_id AS coop_id, max(date) AS last_date
                    FROM poultry_batch_movement
                    WHERE movement_type IN ('retiro', 'traslado')
                      AND state = 'done' AND active
                    GROUP BY batch_id, origin_coop_id
                ) mo ON mo.batch_id = l.batch_id AND mo.coop_id = l.coop_id
                GROUP BY l.coop_id, l.batch_id,
                         mi.first_date, mi.total_birds, mo.last_date
            )
        """)

    def _compute_counts(self):
        """Vivas/muertas reutilizando el motor de las líneas (son campos
        calculados no almacenados: no se pueden agregar en el SQL de la vista)."""
        Line = self.env['poultry.batch.coop.line'].with_context(active_test=False)
        for rec in self:
            lines = Line.search([('coop_id', '=', rec.coop_id.id),
                                 ('batch_id', '=', rec.batch_id.id)])
            rec.dead_count = sum(lines.mapped('dead_count'))
            rec.live_bird_count = sum(
                line.live_bird_count for line in lines
                if line.active and not line.date_to)
