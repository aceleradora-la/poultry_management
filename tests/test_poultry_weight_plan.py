# -*- coding: utf-8 -*-
"""Programación de los pesajes por semana de vida con un Plan de Pesaje (pedido del usuario
del 2026-11-12)."""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPoultryWeightPlan(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env.user)
        cls.coop = cls.env['poultry.coop'].create({
            'name': 'Galpón Plan', 'code': 'G931', 'size': 100, 'capacity': 100})
        cls.env['poultry.cage.generate.wizard'].create({
            'coop_id': cls.coop.id, 'row_to': 1, 'side_to': 1, 'bay_to': 1, 'floor_to': 1, 'cage_to': 3,
        }).action_generate()
        cls.coop.cage_ids.is_sampling = True
        cls.cages = cls.coop.cage_ids.sorted(key=lambda cage: cage._poultry_sort_key())
        cls.genetics = cls.env['poultry.genetics'].create({'name': 'Genética Plan'})
        Plan = cls.env['poultry.weight.plan']
        Plan.search([('is_default', '=', True)]).write({'is_default': False})
        # La regla de jeica: hasta la 30 cada semana, de 30 a 40 cada 2, desde la 40 cada 4.
        cls.plan = Plan.create({
            'name': 'Plan Test', 'is_default': True, 'send_mode': 'auto',
            'line_ids': [
                (0, 0, {'week_from': 0, 'week_to': 30, 'interval': 1}),
                (0, 0, {'week_from': 30, 'week_to': 40, 'interval': 2}),
                (0, 0, {'week_from': 40, 'week_to': 0, 'interval': 4}),
            ],
        })
        cls.Record = cls.env['poultry.weight.record']

    def _batch(self, week_today, entry_week=17, code='LPT'):
        """Lote que hoy está en el tercer día de su semana de vida `week_today` y que
        ingresó al galpón en la semana `entry_week`."""
        birth = self.today - timedelta(days=(week_today - 1) * 7 + 2)
        batch = self.env['poultry.batch'].create({
            'name': 'Lote %s' % code, 'code': code, 'genetics_id': self.genetics.id, 'birth_date': birth,
        })
        self.env['poultry.batch.coop.line'].create({
            'batch_id': batch.id, 'coop_id': self.coop.id, 'bird_count': 100,
            'date_from': batch._poultry_week_start(entry_week),
        })
        return batch

    def _planned(self, batch):
        return self.Record.search([('batch_id', '=', batch.id), ('plan_week', '!=', False)], order='plan_week')

    def test_due_weeks(self):
        due = [week for week in range(1, 60) if self.plan._poultry_is_due(week, 17)]
        self.assertEqual(due, list(range(17, 31)) + [32, 34, 36, 38, 40, 44, 48, 52, 56])
        self.assertEqual(self.plan._poultry_next_due_week(31, 17), 32)
        self.assertEqual(self.plan._poultry_next_due_week(41, 17), 44)
        self.assertFalse(self.plan._poultry_is_due(16, 17), 'Antes del ingreso al galpón no se pesa')
        self.assertTrue(self.plan.preview.startswith('17, 18, 19'))

    def test_creates_this_week_and_the_next(self):
        batch = self._batch(20)
        self.Record._cron_poultry_plan_weighings()
        current, upcoming = self._planned(batch)
        self.assertEqual((current.plan_week, upcoming.plan_week), (20, 21))
        self.assertEqual((upcoming.state, upcoming.plan_week_start, upcoming.plan_week_end),
                         ('planned', batch._poultry_week_start(21), batch._poultry_week_end(21)))
        self.assertEqual(current.state, 'planned', 'Sin pesada anterior no hay jaulas para copiar')
        self.assertTrue(current.plan_needs_office)

        self.Record._cron_poultry_plan_weighings()
        self.assertEqual(len(self._planned(batch)), 2, 'No duplica')
        notes = current.message_ids.filtered(lambda m: 'No se pudo enviar sola' in (m.body or ''))
        self.assertEqual(len(notes), 1, 'Avisa una sola vez')

        upcoming.action_cancel()
        self.Record._cron_poultry_plan_weighings()
        self.assertEqual(self.Record.search_count([('batch_id', '=', batch.id), ('plan_week', '=', 21)]), 1,
                         'Cancelar saltea la semana: no se vuelve a crear')

    def test_week_that_is_not_due(self):
        batch = self._batch(33)
        self.Record._cron_poultry_plan_weighings()
        self.assertEqual(self._planned(batch).mapped('plan_week'), [34], 'Entre 30 y 40 se pesa cada 2')

    def test_sends_itself_with_the_previous_cages(self):
        batch = self._batch(20)
        previous = self.Record.create({
            'coop_id': self.coop.id, 'batch_id': batch.id, 'date': batch._poultry_week_start(19) + timedelta(days=1)})
        previous._poultry_add_cage_lines(self.cages, 3)
        weights = {self.cages[0]: [1500, 1520, 1480], self.cages[1]: [1510, 1490, 0], self.cages[2]: [0, 0, 0]}
        for cage, cage_weights in weights.items():
            for line, weight in zip(previous.line_ids.filtered(lambda l: l.cage_id == cage).sorted('bird_no'), cage_weights):
                line.weight_g = weight
        previous.action_done()

        self.Record._cron_poultry_plan_weighings()
        current, upcoming = self._planned(batch)
        self.assertEqual(current.state, 'in_progress', 'Su semana empezó: se envió sola')
        per_cage = {cage: len(current.line_ids.filtered(lambda l: l.cage_id == cage)) for cage in self.cages}
        self.assertEqual(per_cage, {self.cages[0]: 3, self.cages[1]: 2, self.cages[2]: 0},
                         'Las mismas jaulas y aves que quedaron con peso en la anterior')
        self.assertIn('Enviada a pesar sola', current.message_ids[0].body)
        self.assertEqual(upcoming.state, 'planned', 'La de la semana que viene todavía no')

    def test_office_mode_waits(self):
        self.plan.send_mode = 'office'
        batch = self._batch(20)
        self.Record._cron_poultry_plan_weighings()
        current = self._planned(batch)[0]
        self.assertEqual((current.state, current.plan_needs_office), ('planned', False))

    def test_manual_weighing_covers_the_week(self):
        batch = self._batch(20)
        self.Record.create({'coop_id': self.coop.id, 'batch_id': batch.id, 'date': self.today})
        self.Record._cron_poultry_plan_weighings()
        self.assertEqual(self._planned(batch).mapped('plan_week'), [21])

    def test_late_weighing_is_registered_in_its_real_week(self):
        batch = self._batch(20)
        start, end = batch._poultry_week_start(19), batch._poultry_week_end(19)
        record = self.Record.create({
            'coop_id': self.coop.id, 'batch_id': batch.id, 'date': start, 'state': 'in_progress',
            'plan_week': 19, 'plan_week_start': start, 'plan_week_end': end,
        })
        record._poultry_add_cage_lines(self.cages[:1], 2)
        self.assertTrue(record.is_late)
        self.assertIn(record, self.Record.search([('is_late', '=', True)]))
        self.assertNotIn(record, self.Record.search([('is_late', '=', False)]))
        phone = next(item for item in self.Record.poultry_mobile_list() if item['id'] == record.id)
        self.assertEqual((phone['late'], phone['plan_week'], phone['today_week']), (True, 19, 20))

        for line in record.line_ids:
            line.weight_g = 1500
        record.with_context(poultry_mobile=True).action_register(force=True)
        self.assertEqual(record.date, self.today, 'Se pesó hoy')
        self.assertEqual((record.plan_week, record.batch_age_weeks), (19, 20),
                         'Cubre la 19 del plan pero queda registrada en su semana real, la 20')
        self.assertFalse(record.is_late)

    def test_changing_the_plan_replans(self):
        batch = self._batch(33)
        self.Record._cron_poultry_plan_weighings()
        weekly = self.env['poultry.weight.plan'].create({
            'name': 'Semanal Test', 'line_ids': [(0, 0, {'week_from': 0, 'week_to': 0, 'interval': 1})]})
        batch.weight_plan_id = weekly
        self.assertEqual(self._planned(batch).mapped('plan_week'), [33, 34],
                         'Con el plan semanal toca también la 33')
        Batch = self.env['poultry.batch']
        self.assertIn(batch, Batch.search([('weight_plan_effective_id', '=', weekly.id)]))
        self.assertNotIn(batch, Batch.search([('weight_plan_effective_id', '=', self.plan.id)]))
        batch.weight_plan_id = False
        self.assertEqual(batch.weight_plan_effective_id, self.plan, 'Vacío = el plan de la granja')

    def test_phone_list_shows_the_upcoming_ones(self):
        batch = self._batch(33)
        self.Record._cron_poultry_plan_weighings()
        upcoming = self._planned(batch)
        phone = next(item for item in self.Record.poultry_mobile_list() if item['id'] == upcoming.id)
        self.assertEqual((phone['state'], phone['plan_week'], phone['plan_week_start']),
                         ('planned', 34, fields.Date.to_string(batch._poultry_week_start(34))))

    def test_single_default_plan(self):
        other = self.env['poultry.weight.plan'].create({
            'name': 'Otro', 'is_default': True, 'line_ids': [(0, 0, {'week_from': 0, 'interval': 2})]})
        self.assertFalse(self.plan.is_default)
        self.assertEqual(self.env['poultry.weight.plan']._poultry_default_plan(), other)

    def test_calendar_uses_the_week_of_life(self):
        batch = self._batch(33)
        self.Record._cron_poultry_plan_weighings()
        planned = self._planned(batch)
        self.assertEqual((planned.calendar_start, planned.calendar_stop),
                         (planned.plan_week_start, planned.plan_week_end), 'Ocupa sus 7 días')
        manual = self.Record.create({'coop_id': self.coop.id, 'batch_id': batch.id, 'date': self.today})
        self.assertEqual((manual.calendar_start, manual.calendar_stop), (self.today, self.today))
        label = planned.with_context(poultry_calendar_label=True).display_name
        self.assertEqual(label, 'Galpón Plan · Sem. 34 · Planificada')

    def test_kanban_columns_follow_the_process(self):
        batch = self._batch(20)
        self.Record._cron_poultry_plan_weighings()
        self.Record.create({'coop_id': self.coop.id, 'batch_id': batch.id, 'date': self.today,
                            'state': 'in_progress'})
        # Las tarjetas piden los grupos con read_group_expand (lo hace el cliente web).
        kanban = self.Record.with_context(read_group_expand=True)
        groups = kanban.web_read_group([('batch_id', '=', batch.id)], ['state'])['groups']
        self.assertEqual([group['state'] for group in groups], ['planned', 'in_progress'],
                         'Planificada antes que En Curso, sin columnas vacías')
