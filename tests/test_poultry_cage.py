# -*- coding: utf-8 -*-

from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestPoultryCage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coop = cls.env['poultry.coop'].create({
            'name': 'Galpón Test', 'code': 'G901', 'size': 100, 'capacity': 100,
        })
        # Un solo claro, piso y jaula por defecto: alcanza salvo para probar el galpón
        # completo, y mantiene los tests rápidos.
        cls.small = {
            'row_to': 1, 'side_to': 2, 'bay_to': 2, 'floor_to': 1, 'cage_to': 2,
        }

    def _wizard(self, **values):
        return self.env['poultry.cage.generate.wizard'].create({
            'coop_id': self.coop.id, **values,
        })

    def _cage(self, code):
        return self.env['poultry.cage'].with_context(active_test=False).search([
            ('coop_id', '=', self.coop.id), ('code', '=', code),
        ])

    def test_generate_whole_coop(self):
        """Con la numeración por defecto salen las 3264 jaulas de un galpón."""
        wizard = self._wizard()
        self.assertEqual(wizard.total_count, 3264)
        wizard.action_generate()
        self.assertEqual(self.coop.cage_count, 3264)
        cage = self._cage('901.1.2.32.3.4')
        self.assertEqual(
            (cage.row_no, cage.side_no, cage.bay_no, cage.floor_no, cage.cage_no),
            (1, 2, 32, 3, 4))
        self.assertEqual(cage.name, '901.1.2.32.3.4')
        self.assertFalse(cage.is_sampling)

    def test_preview(self):
        wizard = self._wizard(**self.small)
        self.assertEqual(wizard.coop_number, 901, 'Se sugiere desde el código del galpón')
        self.assertEqual(wizard.total_count, 8)
        self.assertEqual(wizard.new_count, 8)
        self.assertEqual(wizard.first_code, '901.1.1.1.1.1')
        self.assertEqual(wizard.last_code, '901.1.2.2.1.2')

    def test_generate_custom_start(self):
        self._wizard(**dict(self.small, bay_from=52, bay_to=53)).action_generate()
        self.assertEqual(self.coop.cage_count, 8)
        self.assertTrue(self._cage('901.1.1.52.1.1'))
        self.assertFalse(self._cage('901.1.1.1.1.1'))

    def test_generate_again_only_adds_missing(self):
        """Ampliar el galpón no duplica ni revive las jaulas archivadas."""
        self._wizard(**self.small).action_generate()
        archived = self._cage('901.1.1.1.1.1')
        archived.active = False

        wizard = self._wizard(**dict(self.small, bay_to=3))
        self.assertEqual(wizard.existing_count, 8)
        self.assertEqual(wizard.new_count, 4)
        wizard.action_generate()

        self.assertEqual(self.coop.cage_count, 11)
        self.assertEqual(len(self._cage('901.1.1.1.1.1')), 1)
        self.assertFalse(archived.active)

    def test_generate_locates_manual_cage(self):
        """Una jaula cargada a mano con un código del rango es la misma jaula."""
        manual = self.env['poultry.cage'].create({
            'coop_id': self.coop.id, 'code': '901.1.2.2.1.2', 'name': 'Manual',
            'is_sampling': True,
        })
        wizard = self._wizard(**self.small)
        self.assertEqual(wizard.existing_count, 1)
        self.assertEqual(wizard.new_count, 7)
        wizard.action_generate()

        self.assertEqual(self.coop.cage_count, 8)
        self.assertEqual(
            (manual.row_no, manual.side_no, manual.bay_no, manual.floor_no, manual.cage_no),
            (1, 2, 2, 1, 2))
        self.assertTrue(manual.is_sampling)
        self.assertEqual(manual.name, 'Manual')

    def test_generate_nothing_new(self):
        self._wizard(**self.small).action_generate()
        with self.assertRaises(ValidationError):
            self._wizard(**self.small).action_generate()

    def test_generate_invalid_range(self):
        with self.assertRaises(ValidationError):
            self._wizard(bay_from=10, bay_to=5).action_generate()
        with self.assertRaises(ValidationError):
            self._wizard(row_from=0, row_to=1).action_generate()
        self.assertEqual(self.coop.cage_count, 0)

    def test_generate_requires_coop_number(self):
        self.coop.code = 'SIN-NUMERO'
        with self.assertRaises(ValidationError):
            self._wizard(**self.small).action_generate()

    def test_coop_number_is_fixed_once_cages_exist(self):
        self._wizard(**self.small).action_generate()
        self.assertEqual(self.coop.cage_number, 901)
        self.assertTrue(self._wizard().coop_number_locked)
        with self.assertRaises(ValidationError):
            self.coop.cage_number = 902

    def test_coop_number_is_unique(self):
        self.coop.cage_number = 901
        other = self.coop.copy({'name': 'Otro', 'code': 'G902'})
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError), self.cr.savepoint():
            other.cage_number = 901
            other.flush_recordset()

    def test_sampling_wizard_replaces_cage(self):
        self._wizard(**self.small).action_generate()
        first, second, third = self.coop.cage_ids[:3]
        wizard = self.env['poultry.cage.sampling.wizard'].create({'coop_id': self.coop.id})
        wizard.cage_ids = first | second
        self.assertEqual(wizard.cage_count, 2)
        wizard.action_confirm()
        self.assertEqual(self.coop.cage_ids.filtered('is_sampling'), first | second)
        self.assertEqual(self.coop.sampling_cage_count, 2)

        # Arranca con las marcadas: se saca una y se agrega otra.
        wizard = self.env['poultry.cage.sampling.wizard'].create({'coop_id': self.coop.id})
        self.assertEqual(wizard.cage_ids, first | second)
        wizard.cage_ids = (wizard.cage_ids - second) | third
        wizard.action_confirm()
        self.assertEqual(self.coop.cage_ids.filtered('is_sampling'), first | third)

    def test_sampling_change_keeps_previous_weight_record(self):
        """Cambiar la marca no toca los partes ya cargados: siguen apuntando a la jaula
        física donde se pesó. (Qué jaulas entran en un parte nuevo lo prueba
        test_poultry_weight_record.)"""
        self._wizard(**self.small).action_generate()
        kept, replaced = self.coop.cage_ids[:2]
        (kept | replaced).is_sampling = True
        genetics = self.env['poultry.genetics'].create({'name': 'Genética Test'})
        today = fields.Date.context_today(self.env.user)
        batch = self.env['poultry.batch'].create({
            'name': 'Lote Test', 'code': 'LT', 'genetics_id': genetics.id,
            'birth_date': today - timedelta(days=100),
        })
        self.env['poultry.batch.coop.line'].create({
            'batch_id': batch.id, 'coop_id': self.coop.id, 'bird_count': 100,
            'date_from': today - timedelta(days=90),
        })
        previous = self.env['poultry.weight.record'].create({
            'coop_id': self.coop.id, 'batch_id': batch.id, 'date': today - timedelta(days=7),
            'line_ids': [(0, 0, {'cage_id': kept.id, 'weight_g': 1500}),
                         (0, 0, {'cage_id': replaced.id, 'weight_g': 1600})],
        })
        previous.action_done()

        replaced.is_sampling = False
        self.assertEqual(previous.line_ids.cage_id, kept | replaced,
                         'El parte anterior conserva la jaula donde se pesó')
        self.assertEqual(previous.bird_count, 2)

    def test_labels_have_qr_and_code_only(self):
        self._wizard(**dict(self.small, bay_to=4)).action_generate()
        cages = self.coop.cage_ids[:16]
        Report = self.env['ir.actions.report']

        zpl = Report._render_qweb_text(
            'poultry_management.action_report_cage_label_zpl', cages.ids)[0].decode()
        self.assertEqual(zpl.count('^XA'), 16)
        self.assertEqual(zpl.count('^XZ'), 16)
        self.assertIn('^FDQA,%s^FS' % cages[0].code, zpl)
        self.assertIn('^A0N,30,22^FD%s^FS' % cages[0].code, zpl)

        html = Report._render_qweb_html(
            'poultry_management.action_report_cage_label', cages.ids)[0].decode()
        self.assertEqual(html.count('data:image/png;base64,'), 16)
        self.assertIn(cages[0].code, html)

    def test_label_pages_hold_24(self):
        """Cada hoja lleva 24 etiquetas y el PDF no agrega una hoja en blanco al final."""
        self._wizard(**dict(self.small, bay_to=8)).action_generate()
        cages = self.coop.cage_ids
        self.assertEqual(len(cages), 32)
        html = self.env['ir.actions.report']._render_qweb_html(
            'poultry_management.action_report_cage_label', cages.ids)[0].decode()
        self.assertEqual(html.count('page-break-before: always'), 1)
