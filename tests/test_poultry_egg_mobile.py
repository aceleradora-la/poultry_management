# -*- coding: utf-8 -*-
"""Parte de producción de huevos desde el celular (app Avícola Campo)."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPoultryEggMobile(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env.user)
        Uom = cls.env['uom.uom']
        # Cajón = 12 maples = 360 huevos, como en el parte real.
        cls.uom_egg = Uom.create({'name': 'Huevo Test', 'use_in_poultry': True})
        cls.uom_map = Uom.create({'name': 'Maple Test', 'relative_uom_id': cls.uom_egg.id,
                                  'relative_factor': 30, 'use_in_poultry': True})
        cls.uom_box = Uom.create({'name': 'Cajón Test', 'relative_uom_id': cls.uom_egg.id,
                                  'relative_factor': 360, 'use_in_poultry': True})
        attribute = cls.env['product.attribute'].create({'name': 'Calibre Test', 'create_variant': 'always'})
        values = cls.env['product.attribute.value'].create([
            {'name': name, 'attribute_id': attribute.id, 'sequence': index}
            for index, name in enumerate(['1', '2', 'S'])])
        cls.template = cls.env['product.template'].create({
            'name': 'Huevo Jeica Test', 'type': 'consu', 'is_egg_production': True,
            'uom_id': cls.uom_egg.id,
            'attribute_line_ids': [(0, 0, {'attribute_id': attribute.id, 'value_ids': [(6, 0, values.ids)]})],
        })
        cls.coop = cls.env['poultry.coop'].create({
            'name': 'Galpón Huevos', 'code': 'GH1', 'size': 100, 'capacity': 1000,
        })
        genetics = cls.env['poultry.genetics'].create({'name': 'Genética Huevos'})
        cls.batch = cls.env['poultry.batch'].create({
            'name': 'Lote Huevos', 'code': 'LH', 'genetics_id': genetics.id,
            'birth_date': cls.today - timedelta(days=200),
        })
        cls.env['poultry.batch.coop.line'].create({
            'batch_id': cls.batch.id, 'coop_id': cls.coop.id, 'bird_count': 500,
            'date_from': cls.today - timedelta(days=150),
        })
        cls.operator = cls.env['res.users'].create({
            'name': 'Operador Huevos', 'login': 'operador_huevos',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id,
                                  cls.env.ref('poultry_management.poultry_field_user').id])],
        })
        cls.Collection = cls.env['poultry.egg.collection']

    def _open(self, Collection=None):
        # "is None", no "or": un recordset vacío es falso y se perdería el usuario.
        if Collection is None:
            Collection = self.Collection
        data = Collection.poultry_mobile_open_coop(self.coop.id)
        return Collection.browse(data['id']), data

    @staticmethod
    def _by_calibre(data):
        return {line['calibre']: line for line in data['lines']}

    @staticmethod
    def _values(data, **per_calibre):
        lines = {line['calibre']: line['id'] for line in data['lines']}
        return [{'line_id': lines[calibre], **item} for calibre, item in per_calibre.items()]

    # ------------------------------------------------------------------
    def test_open_coop_creates_today_part(self):
        record, data = self._open()
        self.assertEqual(record.state, 'draft')
        self.assertEqual(record.date, self.today)
        self.assertEqual(record.product_tmpl_id, self.template, 'Único producto de huevo')
        self.assertTrue(record.name.startswith('REC-'), record.name)
        self.assertEqual([line['calibre'] for line in data['lines']], ['1', '2', 'S'],
                         'Las líneas vienen en el orden de los calibres')
        self.assertEqual([uom['name'] for uom in data['uoms']], ['Cajón Test', 'Maple Test', 'Huevo Test'])
        self.assertEqual([uom['factor'] for uom in data['uoms']], [360, 30, 1])
        self.assertFalse(record.mobile_source, 'Todavía no se cargó nada')

        again, _ = self._open()
        self.assertEqual(again, record, 'Abrir de nuevo el galpón reutiliza el parte del día')

        coops = self.Collection.poultry_mobile_coops()
        item = next(i for i in coops['coops'] if i['coop_id'] == self.coop.id)
        self.assertEqual(item['record']['id'], record.id)
        self.assertEqual(item['live_bird_count'], 500)
        self.assertEqual(item['batch'], 'Lote Huevos')
        self.assertEqual(coops['late'], [])

    def test_open_coop_reuses_office_part(self):
        office = self.Collection.create({
            'coop_id': self.coop.id, 'product_tmpl_id': self.template.id, 'date': self.today,
            'line_ids': [(0, 0, {'product_variant_id': v.id}) for v in self.template.product_variant_ids],
        })
        record, _ = self._open()
        self.assertEqual(record, office)

    def test_initial_gross_complete(self):
        record, data = self._open()
        data = record.poultry_mobile_save_initial(
            self._values(data, **{'1': {'qty': [3, 5, 12]}, '2': {'qty': [2, 1, 0]}}))
        self.assertEqual(record.state, 'counted')
        self.assertTrue(record.initial_date and record.initial_uid == self.env.user)
        self.assertTrue(data['initial_time'] and data['has_initial'])
        self.assertTrue(record.mobile_source)
        lines = self._by_calibre(data)
        self.assertEqual(lines['1']['initial'], [3, 5, 12])
        self.assertEqual(lines['1']['initial_eggs'], 3 * 360 + 5 * 30 + 12)
        self.assertEqual(lines['S']['initial'], [0, 0, 0])

        # El bruto se va guardando celda por celda; lo producido sale ya repartido.
        data = record.poultry_mobile_write_values(
            'final', self._values(data, **{'1': {'qty': [21, 2, 7], 'average_weight': 62.5}}))
        line = self._by_calibre(data)['1']
        self.assertEqual(line['produced'], [17, 8, 25])
        self.assertEqual(line['produced_eggs'], 6385)
        self.assertFalse(record.gross_date, 'Guardar celdas no marca el bruto como cargado')

        data = record.poultry_mobile_save_gross(self._values(data, **{
            '1': {'qty': [21, 2, 7], 'average_weight': 62.5},
            '2': {'qty': [14, 9, 20], 'average_weight': 58.2},
            'S': {'qty': [1, 5, 2]},
        }))
        self.assertTrue(record.gross_date)
        self.assertEqual(record.state, 'counted', 'Guardar el bruto no completa: lo hace el resumen')

        data = record.poultry_mobile_complete()
        self.assertEqual(record.state, 'completed')
        self.assertEqual(data['total_eggs'], 6385 + 4580 + 512)
        self.assertAlmostEqual(data['total_boxes'], round((6385 + 4580 + 512) / 360, 1))
        expected_avg = (62.5 * 6385 + 58.2 * 4580) / (6385 + 4580)
        self.assertAlmostEqual(data['average_weight_elaborated'], round(expected_avg, 1))
        bodies = ' '.join(record.message_ids.mapped('body'))
        self.assertIn('Inicial cargado desde el celular', bodies)
        self.assertIn('Parte completado desde el celular', bodies)

        coops = self.Collection.poultry_mobile_coops()
        item = next(i for i in coops['coops'] if i['coop_id'] == self.coop.id)
        self.assertEqual(item['record']['state'], 'completed')

        # Procesado por la oficina: el celular ya no lo toca.
        record.write({'state': 'done'})
        with self.assertRaises(UserError):
            record.poultry_mobile_reopen()
        with self.assertRaises(UserError):
            record.poultry_mobile_save_farm(1, 0)

    def test_gross_below_initial_blocks_complete(self):
        record, data = self._open()
        record.poultry_mobile_save_initial(self._values(data, **{'1': {'qty': [1, 0, 0]}}))
        record.poultry_mobile_write_values('final', self._values(data, **{'1': {'qty': [0, 5, 0]}}))
        with self.assertRaises(UserError) as error:
            record.poultry_mobile_complete()
        self.assertIn('calibre 1', str(error.exception))
        self.assertEqual(record.state, 'counted')

    def test_wrong_state_and_negative_values(self):
        record, data = self._open()
        with self.assertRaises(UserError, msg='El bruto espera el inicial registrado'):
            record.poultry_mobile_write_values('final', self._values(data, **{'1': {'qty': [1, 0, 0]}}))
        with self.assertRaises(UserError):
            record.poultry_mobile_write_values('initial', self._values(data, **{'1': {'qty': [-1, 0, 0]}}))
        with self.assertRaises(UserError, msg='Sin inicial no se completa'):
            record.poultry_mobile_complete()

    def test_zero_initial_is_a_real_value(self):
        record, data = self._open()
        record.poultry_mobile_save_initial([])
        self.assertEqual(record.state, 'counted', 'Galpón vacío a la mañana: inicial en cero')

    def test_reopen_steps_back(self):
        record, data = self._open()
        record.poultry_mobile_save_initial(self._values(data, **{'1': {'qty': [1, 0, 0]}}))
        record.poultry_mobile_save_gross(self._values(data, **{'1': {'qty': [2, 0, 0]}}))
        record.poultry_mobile_complete()
        record.poultry_mobile_reopen()
        self.assertEqual(record.state, 'counted')
        record.poultry_mobile_reopen()
        self.assertEqual(record.state, 'draft')
        self.assertTrue(record.initial_date, 'La constancia de la carga no se pierde')
        # Y se vuelve a cargar.
        record.poultry_mobile_save_initial(self._values(data, **{'1': {'qty': [1, 1, 0]}}))
        self.assertEqual(record.state, 'counted')

    def test_copy_previous_gross(self):
        yesterday = self.Collection.create({
            'coop_id': self.coop.id, 'product_tmpl_id': self.template.id,
            'date': self.today - timedelta(days=1),
            'line_ids': [(0, 0, {'product_variant_id': v.id}) for v in self.template.product_variant_ids],
        })
        for line in yesterday.line_ids:
            line.write({'final_box': 10, 'final_map': 2, 'final_egg': 3, 'average_weight': 60})
        yesterday.write({'state': 'completed'})

        record, data = self._open()
        self.assertEqual(data['previous_total_eggs'], 3 * (10 * 360 + 2 * 30 + 3))
        data = record.poultry_mobile_copy_previous_gross()
        for line in data['lines']:
            self.assertEqual(line['initial'], [10, 2, 3])
        record.poultry_mobile_save_initial(self._values(data, **{'1': {'qty': [10, 2, 3]}}))
        with self.assertRaises(UserError, msg='Con el inicial registrado ya no se copia'):
            record.poultry_mobile_copy_previous_gross()

    def test_late_parts(self):
        old = self.Collection.create({
            'coop_id': self.coop.id, 'product_tmpl_id': self.template.id,
            'date': self.today - timedelta(days=2),
            'line_ids': [(0, 0, {'product_variant_id': v.id}) for v in self.template.product_variant_ids],
        })
        self.assertEqual(self.Collection.poultry_mobile_coops()['late'], [],
                         'Un borrador de la oficina no es un atrasado del celular')
        old.write({'initial_date': fields.Datetime.now(), 'state': 'counted'})
        late = self.Collection.poultry_mobile_coops()['late']
        self.assertEqual([item['id'] for item in late], [old.id])

    def test_field_user_runs_the_whole_flow(self):
        Collection = self.Collection.with_user(self.operator)
        record, data = self._open(Collection)
        self.assertEqual(record.create_uid, self.operator)
        record.poultry_mobile_save_initial(self._values(data, **{'1': {'qty': [1, 0, 0]}}))
        record.poultry_mobile_write_values('final', self._values(data, **{'1': {'qty': [3, 0, 0], 'average_weight': 61}}))
        record.poultry_mobile_save_gross(self._values(data, **{'1': {'qty': [3, 0, 0], 'average_weight': 61}}))
        data = record.poultry_mobile_complete()
        self.assertEqual(data['total_eggs'], 720)
        data = record.poultry_mobile_save_farm(4, 50.5, 'Sin novedad')
        self.assertEqual(data['dead_count'], 4)
        self.assertEqual(data['feed_consumed_kg'], 50.5)
        self.assertEqual(data['live_bird_count'], 500)
        self.assertEqual(data['feed_bag_kg'], 25)
        with self.assertRaises(UserError):
            record.poultry_mobile_save_farm(501, 0)
        self.assertEqual(Collection.poultry_mobile_coops()['coops'][0]['coop'], 'Galpón Huevos')

    def _setup_unclassified(self):
        """Producto de Huevo sin Clasificar con una lista que consume balanceado (125 kg por
        1000 huevos) y agua, como la OF que crea el Cierre de Galpón."""
        kg = self.env.ref('uom.product_uom_kgm')
        liter = self.env.ref('uom.product_uom_litre')
        feed = self.env['product.template'].create({
            'name': 'Balanceado Test', 'type': 'consu', 'uom_id': kg.id,
            'poultry_consumption_type': 'feed',
        })
        water = self.env['product.template'].create({
            'name': 'Agua Test', 'type': 'consu', 'uom_id': liter.id,
            'poultry_consumption_type': 'water',
        })
        unclassified = self.env['product.template'].create({
            'name': 'Huevo sin Clasificar Test', 'type': 'consu', 'uom_id': self.uom_egg.id,
        })
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': unclassified.id, 'product_qty': 1000, 'product_uom_id': self.uom_egg.id,
            'type': 'normal',
            'bom_line_ids': [
                (0, 0, {'product_id': feed.product_variant_id.id, 'product_qty': 125, 'product_uom_id': kg.id}),
                (0, 0, {'product_id': water.product_variant_id.id, 'product_qty': 250, 'product_uom_id': liter.id}),
            ],
        })
        self.coop.write({
            'unclassified_egg_product_id': unclassified.product_variant_id.id,
            'unclassified_egg_bom_id': bom.id,
        })

    def _closed_day(self, dead=12, feed=450):
        """Parte de hoy completado, procesado (estado forzado) y cerrado: devuelve el cierre."""
        record, data = self._open()
        record.poultry_mobile_save_initial([])
        record.poultry_mobile_save_gross(self._values(data, **{'1': {'qty': [10, 0, 0]}}))
        record.poultry_mobile_complete()
        record.poultry_mobile_save_farm(dead, feed, '')
        record.write({'state': 'done'})  # como si la oficina lo hubiera procesado
        close = self.env['poultry.coop.close'].create({'coop_id': self.coop.id, 'date': self.today})
        record.write({'coop_close_id': close.id})
        return record, close

    def test_farm_data_reaches_the_close(self):
        self._setup_unclassified()
        record, close = self._closed_day()
        self.assertEqual(close.dead_count_total, 12)
        self.assertEqual(close.feed_consumed_kg_total, 450)
        close.action_confirm()
        production = close.unclassified_production_id
        self.assertTrue(production)
        self.assertEqual(production.product_qty, 3600)
        self.assertEqual(production.poultry_dead_count_total, 12)
        self.assertAlmostEqual(production._poultry_feed_consumed_total(), 450)

    def test_close_order_from_mobile(self):
        """El operador carga en la OF del cierre las aves muertas y TODOS los componentes."""
        self._setup_unclassified()
        yesterday = self.Collection.create({
            'coop_id': self.coop.id, 'product_tmpl_id': self.template.id,
            'date': self.today - timedelta(days=1), 'state': 'completed',
            'line_ids': [(0, 0, {'product_variant_id': v.id}) for v in self.template.product_variant_ids],
        })
        record, close = self._closed_day()
        close.action_confirm()
        production = close.unclassified_production_id

        Close = self.env['poultry.coop.close'].with_user(self.operator)
        pending = Close.poultry_mobile_pending()
        self.assertEqual([o['id'] for o in pending['orders']], [close.id])
        header = pending['orders'][0]
        self.assertEqual(header['order_name'], production.name)
        self.assertEqual(header['dead_count'], 12, 'Lo que traía el parte')
        self.assertEqual((header['line_count'], header['loaded_count']), (2, 1),
                         'El alimento vino del parte; el agua sigue sin cargar')
        self.assertEqual([p['id'] for p in pending['parts']], [yesterday.id],
                         'Un parte completado sin cierre se carga en el parte')

        data = Close.browse(close.id).poultry_mobile_data()
        self.assertEqual(data['live_bird_count'], 500)
        self.assertEqual([(l['product'], l['uom'], l['planned'], l['quantity'], l['picked'], l['type'], l['is_kg'])
                          for l in data['lines']],
                         [('Balanceado Test', 'kg', 450, 450, True, 'feed', True),
                          ('Agua Test', 'L', 900, 900, False, 'water', False)],
                         'El agua viene propuesta por la lista pero sin confirmar')
        feed_line, water_line = data['lines']

        data = Close.browse(close.id).poultry_mobile_save(
            15, [{'move_id': feed_line['id'], 'quantity': 480}, {'move_id': water_line['id'], 'quantity': 950}],
            'Llovió toda la tarde')
        self.assertEqual(data['dead_count'], 15)
        self.assertEqual([l['quantity'] for l in data['lines']], [480, 950])
        self.assertEqual(production.poultry_dead_count_total, 15)
        self.assertAlmostEqual(production._poultry_feed_consumed_total(), 480)
        self.assertTrue(all(production.move_raw_ids.mapped('picked')))
        body = production.message_ids[0].body
        self.assertIn('15 aves muertas', body)
        self.assertIn('Llovió', body)
        self.assertEqual(production.message_ids[0].author_id, self.operator.partner_id)

        with self.assertRaises(UserError):
            Close.browse(close.id).poultry_mobile_save(600, [], '')
        production.action_cancel()
        with self.assertRaises(UserError, msg='Una OF cerrada la corrige la oficina'):
            Close.browse(close.id).poultry_mobile_save(1, [], '')
        self.assertEqual(Close.poultry_mobile_pending()['orders'], [])
