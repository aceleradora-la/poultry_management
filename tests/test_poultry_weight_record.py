# -*- coding: utf-8 -*-

from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPoultryWeightRecord(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env.user)
        cls.coop = cls.env['poultry.coop'].create({
            'name': 'Galpón Test', 'code': 'G901', 'size': 100, 'capacity': 100,
        })
        cls.other_coop = cls.env['poultry.coop'].create({
            'name': 'Otro Galpón', 'code': 'G902', 'size': 100, 'capacity': 100,
        })
        # 2 filas × 1 lado × 2 claros × 1 piso × 2 jaulas = 8 jaulas por galpón.
        for coop in (cls.coop, cls.other_coop):
            cls.env['poultry.cage.generate.wizard'].create({
                'coop_id': coop.id, 'row_to': 2, 'side_to': 1, 'bay_to': 2,
                'floor_to': 1, 'cage_to': 2,
            }).action_generate()
        cages = cls.coop.cage_ids.sorted(key=lambda c: c._poultry_sort_key())
        # Marcadas en desorden a propósito: el orden de las líneas sale de la ubicación.
        cls.cage_a, cls.cage_b, cls.cage_c = cages[0], cages[3], cages[6]
        (cls.cage_c | cls.cage_a | cls.cage_b).is_sampling = True
        cls.other_coop.cage_ids[0].is_sampling = True

        genetics = cls.env['poultry.genetics'].create({'name': 'Genética Test'})
        cls.batch = cls.env['poultry.batch'].create({
            'name': 'Lote Test', 'code': 'LT', 'genetics_id': genetics.id,
            'birth_date': cls.today - timedelta(days=100),
        })
        cls.env['poultry.batch.coop.line'].create({
            'batch_id': cls.batch.id, 'coop_id': cls.coop.id, 'bird_count': 100,
            'date_from': cls.today - timedelta(days=90),
        })
        cls.Record = cls.env['poultry.weight.record']

    def _record(self, **values):
        return self.Record.create({
            'coop_id': self.coop.id, 'batch_id': self.batch.id, 'date': self.today, **values,
        })

    def _generate(self, record, birds_per_cage=3):
        """Líneas con cantidad fija por jaula (aunque haya una pesada anterior)."""
        wizard = self.env['poultry.weight.lines.wizard'].create({'record_id': record.id})
        wizard.mode = 'fixed'
        wizard.birds_per_cage = birds_per_cage
        wizard.action_confirm()
        return wizard

    def _weigh(self, record, cage, weights):
        lines = record.line_ids.filtered(lambda l: l.cage_id == cage).sorted('bird_no')
        for line, weight in zip(lines, weights):
            line.weight_g = weight

    # ------------------------------------------------------------------
    # Numeración
    # ------------------------------------------------------------------
    def test_name_per_coop_and_year(self):
        year = self.today.year
        first = self._record()
        second = self._record()
        other = self.Record.create({
            'coop_id': self.other_coop.id, 'batch_id': self.batch.id, 'date': self.today,
        })
        self.assertEqual(first.name, 'G901-%d-001' % year)
        self.assertEqual(second.name, 'G901-%d-002' % year)
        self.assertEqual(other.name, 'G902-%d-001' % year, 'Correlativo propio por galpón')

        old = self._record(date=date(year - 1, 5, 5))
        self.assertEqual(old.name, 'G901-%d-001' % (year - 1), 'Arranca en 1 cada año')

        # Cambiar el galpón en Borrador renumera; una referencia vieja se conserva.
        second.coop_id = self.other_coop
        self.assertEqual(second.name, 'G902-%d-002' % year)
        legacy = self._record(name='PES-0007')
        self.assertEqual(legacy.name, 'PES-0007')

    # ------------------------------------------------------------------
    # Generar Líneas
    # ------------------------------------------------------------------
    def test_lines_wizard_creates_birds_in_physical_order(self):
        record = self._record()
        wizard = self.env['poultry.weight.lines.wizard'].create({'record_id': record.id})
        self.assertEqual(wizard.birds_per_cage, 10, 'Sin pesada anterior propone 10')
        self.assertFalse(wizard.previous_id)
        self.assertEqual(wizard.mode, 'fixed', 'Sin pesada anterior, cantidad fija')
        self.assertEqual(wizard.cage_count, 3)
        wizard.birds_per_cage = 3
        self.assertEqual(wizard.line_count, 9)
        wizard.action_confirm()

        self.assertEqual(record.birds_per_cage, 3)
        self.assertEqual(record.planned_bird_count, 9)
        self.assertEqual(record.bird_count, 0)
        self.assertEqual(record.cage_count, 3)
        lines = record.line_ids.sorted(key=lambda l: (l.sequence, l.bird_no, l.id))
        self.assertEqual(lines.mapped('cage_id'), self.cage_a | self.cage_b | self.cage_c)
        self.assertEqual([(l.cage_id.code, l.bird_no) for l in lines[:4]], [
            (self.cage_a.code, 1), (self.cage_a.code, 2), (self.cage_a.code, 3),
            (self.cage_b.code, 1)])
        self.assertEqual(lines, record._poultry_sorted_lines())
        with self.assertRaises(ValidationError):
            self._generate(record)

    def test_lines_wizard_repeats_previous_record(self):
        """Con una pesada anterior, propone solo las jaulas que quedaron con peso, con
        esas mismas aves; una jaula sin pesar o marcada después no entra (se escanea
        desde el celular o se usa la cantidad fija)."""
        previous = self._record()
        self._generate(previous, birds_per_cage=4)
        self._weigh(previous, self.cage_a, [1900, 2000, 2100])
        self._weigh(previous, self.cage_c, [1950])
        previous.action_register(force=True)
        self.cage_c.is_sampling = False
        new_cage = (self.coop.cage_ids - self.cage_a - self.cage_b - self.cage_c)[0]
        new_cage.is_sampling = True

        record = self._record()
        wizard = self.env['poultry.weight.lines.wizard'].create({'record_id': record.id})
        self.assertEqual(wizard.previous_id, previous)
        self.assertEqual(wizard.mode, 'previous')
        self.assertEqual(wizard.previous_summary, '%s: 2 jaulas · 4 aves con peso' % previous.name)
        self.assertEqual(wizard.birds_per_cage, 4)
        self.assertEqual(wizard.cage_count, 1, 'Solo A tuvo peso (C ya no es de muestreo)')
        self.assertEqual(wizard.skipped_count, 2, 'B sin pesar y la nueva quedan afuera')
        self.assertEqual(wizard.line_count, 3)
        wizard.action_confirm()
        counts = {cage: len(lines) for cage, lines in record.line_ids.grouped('cage_id').items()}
        self.assertEqual(counts, {self.cage_a: 3})

        other = self._record()
        wizard = self.env['poultry.weight.lines.wizard'].create({'record_id': other.id})
        wizard.mode = 'fixed'
        wizard.birds_per_cage = 2
        self.assertEqual(wizard.line_count, 6, 'Cantidad fija: A, B y la nueva, 2 aves cada una')
        wizard.action_confirm()
        self.assertEqual(len(other.line_ids), 6)

    # ------------------------------------------------------------------
    # Totales, registro y confirmación
    # ------------------------------------------------------------------
    def test_totals_ignore_lines_without_weight(self):
        record = self._record()
        self._generate(record)
        self._weigh(record, self.cage_a, [1900, 2100])
        self._weigh(record, self.cage_b, [2000])
        self.assertEqual(record.bird_count, 3)
        self.assertEqual(record.planned_bird_count, 9)
        self.assertEqual(record.weighed_cage_count, 2)
        self.assertAlmostEqual(record.average_weight_g, 2000.0)
        self.assertAlmostEqual(record.min_weight_g, 1900.0)
        self.assertEqual(record._poultry_pending_cages(), self.cage_c)

    def test_register_warns_pending_then_done_drops_empty_lines(self):
        record = self._record()
        self._generate(record)
        with self.assertRaises(ValidationError, msg='Sin pesos no se registra'):
            record.action_register()
        self._weigh(record, self.cage_a, [1900, 2100, 2000])
        self._weigh(record, self.cage_b, [1950])

        action = record.action_register()
        self.assertEqual(action['res_model'], 'poultry.weight.register.wizard',
                         'Con jaulas sin pesar primero avisa')
        self.assertEqual(record.state, 'draft')
        wizard = self.env['poultry.weight.register.wizard'].create({'record_id': record.id})
        self.assertEqual(wizard.pending_count, 1)
        self.assertEqual(wizard.pending_codes, self.cage_c.code)
        wizard.action_confirm()
        self.assertEqual(record.state, 'registered')
        self.assertEqual(record.registered_uid, self.env.user)
        self.assertTrue(record.registered_date)
        with self.assertRaises(ValidationError):
            record.unlink()

        record.action_reopen()
        self.assertEqual(record.state, 'draft')
        self.assertFalse(record.registered_date)
        self._weigh(record, self.cage_c, [2050])
        self.assertTrue(record.action_register(), 'Sin jaulas pendientes registra directo')
        self.assertEqual(record.state, 'registered')

        record.action_done()
        self.assertEqual(record.state, 'done')
        self.assertEqual(len(record.line_ids), 5, 'Las líneas sin peso se borran al confirmar')
        self.assertFalse(record.line_ids.filtered(lambda l: l.weight_g <= 0))
        self.assertEqual(record.bird_count, 5)

    # ------------------------------------------------------------------
    # Resumen por jaula
    # ------------------------------------------------------------------
    def test_cage_summary(self):
        previous = self._record(date=self.today - timedelta(days=7))
        self._generate(previous)
        self._weigh(previous, self.cage_a, [1800, 1800, 1800])
        previous.action_register(force=True)

        record = self._record()
        self._generate(record)
        self._weigh(record, self.cage_a, [1900, 2100, 2000])
        self._weigh(record, self.cage_b, [1500, 1500])
        summaries = record._poultry_cage_summaries()
        self.assertEqual(summaries.mapped('cage_id'), self.cage_a | self.cage_b | self.cage_c,
                         'Una fila por jaula, en orden físico')
        a, b, c = summaries
        self.assertEqual((a.bird_count, a.line_count), (3, 3))
        self.assertAlmostEqual(a.average_weight_g, 2000.0)
        self.assertAlmostEqual(a.min_weight_g, 1900.0)
        self.assertAlmostEqual(a.max_weight_g, 2100.0)
        self.assertAlmostEqual(a.cv_pct, 4.08, places=2)
        self.assertAlmostEqual(a.previous_average_g, 1800.0)
        self.assertAlmostEqual(a.deviation_pct, (2000 - 1800) / 1800 * 100, places=1)
        self.assertIn('se aparta', a.alert)
        self.assertIn('2 de 3 aves', b.alert)
        self.assertEqual(c.bird_count, 0)
        self.assertEqual(c.alert, 'sin pesar')

    # ------------------------------------------------------------------
    # Celular
    # ------------------------------------------------------------------
    def test_send_to_weigh_and_progress(self):
        record = self._record()
        with self.assertRaises(ValidationError, msg='Sin líneas no se envía'):
            record.action_send()
        self._generate(record)
        self.assertEqual(record.progress_pct, 0.0)
        record.action_send()
        self.assertEqual(record.state, 'in_progress')
        self._weigh(record, self.cage_a, [1900, 2100, 2000])
        self.assertAlmostEqual(record.progress_pct, 3 / 9 * 100, places=1)

        record.action_reopen()
        self.assertEqual(record.state, 'draft', 'Se puede corregir y volver a enviar')
        record.action_send()
        self.assertTrue(record.action_register(force=True))
        self.assertEqual(record.state, 'registered')
        self.assertAlmostEqual(record.progress_pct, 100.0 * 3 / 9, places=3)

    def test_field_user_only_uses_the_app(self):
        operator = self.env['res.users'].create({
            'name': 'Operador Test', 'login': 'operador_test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('poultry_management.poultry_field_user').id])],
        })
        record = self._record()
        self._generate(record)
        record.action_send()

        Record = self.Record.with_user(operator)
        self.assertEqual([r['id'] for r in Record.poultry_mobile_list()], [record.id])
        data = Record.browse(record.id).poultry_mobile_data()
        line = data['cages'][0]['lines'][0]
        Record.browse(record.id).poultry_mobile_set_weight(line['id'], 1980)
        Record.browse(record.id).with_context(poultry_mobile=True).action_register(force=True)
        self.assertEqual(record.state, 'registered')
        self.assertEqual(record.registered_uid, operator)
        with self.assertRaises(AccessError, msg='No crea partes ni entra a Gestión Avícola'):
            Record.create({'coop_id': self.coop.id, 'batch_id': self.batch.id})
        self.assertFalse(operator.has_group('poultry_management.poultry_user'))
        self.assertIn(self.env.ref('poultry_management.poultry_field_user'),
                      self.env.ref('poultry_management.poultry_manager').all_implied_ids,
                      'El Gestor Avícola hereda la app del celular')

    def test_mobile_flow(self):
        record = self._record()
        self._generate(record)
        self.assertEqual(self.Record.poultry_mobile_list(), [],
                         'En Borrador todavía no aparece en el celular')
        with self.assertRaises(ValidationError):
            record.poultry_mobile_set_weight(record.line_ids[0].id, 1900)
        record.action_send()
        self.assertEqual([r['id'] for r in self.Record.poultry_mobile_list()], [record.id])

        data = record.poultry_mobile_data()
        self.assertEqual([c['code'] for c in data['cages']],
                         [self.cage_a.code, self.cage_b.code, self.cage_c.code])
        self.assertEqual(data['cages'][0]['status'], 'pending')
        self.assertEqual(len(data['cages'][0]['lines']), 3)

        self.assertIn('error', record.poultry_mobile_find_cage('9.9.9.9.9.9'))
        other = self.other_coop.cage_ids[0]
        self.assertIn(self.other_coop.name, record.poultry_mobile_find_cage(other.code)['error'])
        not_sampling = (self.coop.cage_ids - record.line_ids.cage_id)[0]
        self.assertIn('no es de muestreo', record.poultry_mobile_find_cage(not_sampling.code)['error'])
        found = record.poultry_mobile_find_cage(' %s ' % self.cage_b.code)
        self.assertEqual(found, {'cage_id': self.cage_b.id, 'added': False})

        # Una jaula marcada después de generar las líneas se agrega al escanearla.
        late = not_sampling
        late.is_sampling = True
        self.assertEqual(record.poultry_mobile_find_cage(late.code), {'cage_id': late.id, 'added': True})
        self.assertEqual(len(record.line_ids.filtered(lambda l: l.cage_id == late)), 3)

        line = data['cages'][0]['lines'][0]
        result = record.poultry_mobile_set_weight(line['id'], 1950)
        self.assertEqual(result['cage']['status'], 'open')
        self.assertEqual(result['cage']['bird_count'], 1)
        self.assertAlmostEqual(result['cage']['average_weight_g'], 1950.0)
        self.assertEqual(result['record']['bird_count'], 1)
        self.assertNotIn('lines', result['cage'])

        data = record.poultry_mobile_add_line(self.cage_a.id)
        self.assertEqual([l['bird_no'] for l in data['cages'][0]['lines']], [1, 2, 3, 4])
        data = record.poultry_mobile_remove_line(self.cage_a.id)
        self.assertEqual([l['bird_no'] for l in data['cages'][0]['lines']], [1, 2, 3],
                         'Saca la última línea vacía, no la pesada')

        result = record.poultry_mobile_close_cage(self.cage_a.id)
        self.assertEqual(result['cage']['status'], 'closed')
        self.assertEqual(result['record']['closed_cage_count'], 1)
        self.assertEqual(record.poultry_mobile_pending_cages(),
                         [late.code, self.cage_b.code, self.cage_c.code],
                         'Pendientes en orden físico: la agregada está antes que B y C')

        record.with_context(poultry_mobile=True).action_register(force=True)
        self.assertEqual(record.state, 'registered')
        self.assertTrue(record.message_ids.filtered(lambda m: 'celular' in (m.body or '')))
        with self.assertRaises(ValidationError):
            record.poultry_mobile_set_weight(line['id'], 2000)
        listed = self.Record.poultry_mobile_list()
        self.assertEqual([(r['id'], r['state']) for r in listed], [(record.id, 'registered')])

    # ------------------------------------------------------------------
    # Planilla
    # ------------------------------------------------------------------
    def test_sheet_pages_flow_by_column(self):
        record = self._record()
        self._generate(record)  # 3 jaulas × 3 aves
        pages = record._poultry_sheet_pages()
        self.assertEqual([len(column) for column in pages[0]], [1, 1, 1],
                         'Con pocas aves las secciones se reparten parejas')
        pages = record._poultry_sheet_pages(rows_per_column=4)
        self.assertEqual(len(pages), 1)
        self.assertEqual([len(column) for column in pages[0]], [1, 1, 1],
                         'Cada jaula (título + 3 aves) llena una sección')
        self.assertEqual([column[0]['cage'] for column in pages[0]],
                         [self.cage_a, self.cage_b, self.cage_c])
        self.assertFalse(any(group['continued'] for column in pages[0] for group in column))

        pages = record._poultry_sheet_pages(rows_per_column=3, columns=2)
        # Columna: título + 2 aves; la tercera ave sigue en la columna siguiente, y la
        # jaula siguiente (título + ave = 2 filas) ya no entra ahí: arranca columna nueva.
        self.assertEqual(len(pages), 3)
        first, second = pages[0]
        self.assertEqual([(g['cage'], g['continued'], len(g['rows'])) for g in first],
                         [(self.cage_a, False, 2)])
        self.assertEqual([(g['cage'], g['continued'], len(g['rows'])) for g in second],
                         [(self.cage_a, True, 1)])
        self.assertEqual([(g['cage'], g['continued']) for column in pages[1] for g in column],
                         [(self.cage_b, False), (self.cage_b, True)])

        html = self.env['ir.actions.report']._render_qweb_html(
            'poultry_management.action_report_weight_sheet', record.ids)[0].decode()
        self.assertIn(record.name, html)
        self.assertIn('Jaula %s' % self.cage_c.code, html)
        self.assertNotIn('class="pw-break"', html, 'Entra en una sola hoja')
        self.assertIn(self.env.company.name, html, 'Lleva los datos de la empresa')
        self.assertIn('Hoja 1 de 1', html)
