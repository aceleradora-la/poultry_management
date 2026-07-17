# -*- coding: utf-8 -*-

from odoo import models, fields, tools


class PoultryVaccinationCompliance(models.Model):
    """Cumplimiento de Vacunación: vista SQL de solo lectura con una fila por línea de
    plan × asignación de plan a lote. Permite responder en una sola lista buscable y
    agrupable "¿qué vacunas están pendientes o vencidas hoy en toda la granja?".

    El match aplicación ↔ línea de plan es exclusivamente por plan_line_id (la
    aplicación más antigua confirmada que la referencia): una aplicación sin línea de
    plan es válida como refuerzo pero no cuenta para el cumplimiento. La sugerencia
    automática de línea en poultry.vaccination es lo que mantiene ese vínculo cargado.
    """
    _name = 'poultry.vaccination.compliance'
    _description = 'Cumplimiento de Vacunación'
    _auto = False
    _order = 'batch_id, week, id'
    _rec_name = 'vaccine_id'

    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', readonly=True)
    assignment_id = fields.Many2one('poultry.batch.vaccination.plan',
                                    string='Asignación', readonly=True)
    plan_id = fields.Many2one('poultry.vaccination.plan', string='Plan de Vacunación',
                              readonly=True)
    plan_line_id = fields.Many2one('poultry.vaccination.plan.line', string='Línea de Plan',
                                   readonly=True)
    week = fields.Integer(string='Semana de Vida', readonly=True)
    vaccine_id = fields.Many2one('poultry.vaccine', string='Vacuna', readonly=True)
    due_date = fields.Date(string='Fecha Prevista', readonly=True,
                           help='Inicio de la Semana de Vida en la que corresponde aplicar '
                                '(nacimiento del lote + semana × 7 días).')
    vaccination_id = fields.Many2one('poultry.vaccination', string='Aplicación', readonly=True)
    applied_date = fields.Date(string='Fecha de Aplicación', readonly=True)
    status = fields.Selection([
        ('applied', 'Aplicada'),
        ('pending', 'Pendiente'),
        ('overdue', 'Vencida'),
    ], string='Estado', readonly=True)
    active_assignment = fields.Boolean(string='Asignación Vigente', readonly=True)

    def init(self):
        # Vencida = pasó la semana prevista completa más una semana de gracia sin
        # aplicación confirmada vinculada a la línea de plan.
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE VIEW %s AS (
                SELECT
                    row_number() OVER (ORDER BY a.id, l.id) AS id,
                    a.id AS assignment_id,
                    a.batch_id AS batch_id,
                    a.plan_id AS plan_id,
                    l.id AS plan_line_id,
                    l.week AS week,
                    l.vaccine_id AS vaccine_id,
                    (b.birth_date + ((l.week - 1) * 7)) AS due_date,
                    v.id AS vaccination_id,
                    v.date AS applied_date,
                    CASE
                        WHEN v.id IS NOT NULL THEN 'applied'
                        WHEN b.birth_date IS NULL THEN 'pending'
                        WHEN (b.birth_date + ((l.week - 1) * 7 + 13)) < CURRENT_DATE THEN 'overdue'
                        ELSE 'pending'
                    END AS status,
                    (a.date_to IS NULL) AS active_assignment
                FROM poultry_batch_vaccination_plan a
                JOIN poultry_vaccination_plan_line l ON l.plan_id = a.plan_id
                JOIN poultry_batch b ON b.id = a.batch_id
                LEFT JOIN LATERAL (
                    SELECT pv.id, pv.date
                    FROM poultry_vaccination pv
                    WHERE pv.state = 'done'
                      AND pv.batch_id = a.batch_id
                      AND pv.plan_line_id = l.id
                    ORDER BY pv.date, pv.id
                    LIMIT 1
                ) v ON TRUE
            )
        """ % self._table)

    def action_register_vaccination(self):
        """Abre el formulario de Aplicación de Vacuna precargado desde esta fila de
        cumplimiento (lote, vacuna, línea de plan, vía y dosis del plan)."""
        self.ensure_one()
        return {
            'name': 'Registrar Aplicación de Vacuna',
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.vaccination',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_batch_id': self.batch_id.id,
                'default_vaccine_id': self.vaccine_id.id,
                'default_plan_line_id': self.plan_line_id.id,
                'default_route': self.plan_line_id.route,
                'default_dose': self.plan_line_id.dose,
            },
        }
