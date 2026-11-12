# -*- coding: utf-8 -*-
"""Cómo viaja el Parte de Registro de Peso a los indicadores: se publica al confirmar,
se recalcula o se borra al cancelar, y el botón "Recalcular este indicador" lo rehace
desde los partes confirmados."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPoultryWeightIndicators(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env.user)
        Coop = cls.env['poultry.coop']
        cls.coop = Coop.create({'name': 'Galpón Peso A', 'code': 'G911', 'size': 100, 'capacity': 100})
        cls.coop2 = Coop.create({'name': 'Galpón Peso B', 'code': 'G912', 'size': 100, 'capacity': 100})
        for coop in (cls.coop, cls.coop2):
            cls.env['poultry.cage.generate.wizard'].create({
                'coop_id': coop.id, 'row_to': 1, 'side_to': 1, 'bay_to': 1, 'floor_to': 1, 'cage_to': 2,
            }).action_generate()
            coop.cage_ids[0].is_sampling = True
        genetics = cls.env['poultry.genetics'].create({'name': 'Genética Peso'})
        cls.batch = cls.env['poultry.batch'].create({
            'name': 'Lote Peso', 'code': 'LP', 'genetics_id': genetics.id,
            'birth_date': cls.today - timedelta(days=100),
        })
        # El mismo lote en dos galpones: sus pesadas del mismo día se combinan.
        for coop in (cls.coop, cls.coop2):
            cls.env['poultry.batch.coop.line'].create({
                'batch_id': cls.batch.id, 'coop_id': coop.id, 'bird_count': 100,
                'date_from': cls.today - timedelta(days=90),
            })
        Indicator = cls.env['poultry.indicator']
        Indicator.search(['|', ('category', 'in', ('weight', 'uniformity')),
                          ('formula_numerator', 'in', ('weighed_g', 'uniform_birds'))]).write({'active': False})
        # Como PESO CORPORAL (g) en jeica: fórmula gramos pesados / aves pesadas, del día.
        cls.indicator = Indicator.create({
            'name': 'Peso Corporal Test', 'uom_id': cls.env.ref('uom.product_uom_gram').id,
            'category': 'weight', 'accumulation_type': 'none', 'calculation_source': 'formula',
            'formula_numerator': 'weighed_g', 'formula_denominator': 'weighed_birds',
            'formula_mode': 'daily',
        })
        cls.Value = cls.env['poultry.batch.indicator.value']
        cls.Weekly = cls.env['poultry.batch.indicator.weekly.value']

    def _confirmed(self, coop, weights, date=None, exceptional=False):
        vals = {'coop_id': coop.id, 'batch_id': self.batch.id, 'date': date or self.today}
        if exceptional:
            vals.update({'is_exceptional': True, 'exceptional_reason': 'Control puntual'})
        record = self.env['poultry.weight.record'].create(vals)
        wizard = self.env['poultry.weight.lines.wizard'].create({'record_id': record.id})
        wizard.mode = 'fixed'
        wizard.birds_per_cage = len(weights)
        wizard.action_confirm()
        for line, weight in zip(record.line_ids.sorted('bird_no'), weights):
            line.weight_g = weight
        record.action_done()
        return record

    def _daily(self, date=None):
        values = self.Value.search([
            ('batch_id', '=', self.batch.id), ('indicator_id', '=', self.indicator.id),
            ('date', '=', date or self.today)])
        return [(v.value, v.numerator, v.denominator) for v in values]

    def _weekly(self, date=None):
        week = self.batch._poultry_week_of(date or self.today)
        return self.Weekly.search([
            ('batch_id', '=', self.batch.id), ('indicator_id', '=', self.indicator.id),
            ('week', '=', week)]).mapped('real_value')

    def test_confirm_cancel_and_draft(self):
        first = self._confirmed(self.coop, [1900, 2100, 2000])
        self.assertEqual(self._daily(), [(2000, 6000, 3)], 'Se publica al confirmar')
        self.assertEqual(self._weekly(), [2000])

        second = self._confirmed(self.coop2, [1600])
        self.assertEqual(self._daily(), [(1900, 7600, 4)],
                         'Mismo lote y día: un solo valor, ponderado por ave')
        self.assertEqual(self._weekly(), [1900])

        second.action_cancel()
        self.assertEqual(self._daily(), [(2000, 6000, 3)], 'Cancelar recalcula con lo que queda')
        self.assertEqual(self._weekly(), [2000])
        second.action_draft()
        self.assertEqual(self._daily(), [(2000, 6000, 3)], 'Volver a Borrador no toca nada')

        first.action_cancel()
        self.assertEqual(self._daily(), [], 'Cancelado el último del día, el valor se borra')
        self.assertEqual(self._weekly(), [], 'y el semanal de origen Sistema también')

        first.action_draft()
        self.assertEqual(self._daily(), [])
        first.action_done()
        self.assertEqual(self._daily(), [(2000, 6000, 3)], 'Confirmar de nuevo vuelve a publicar')

    def test_cancel_keeps_manual_weekly(self):
        week = self.batch._poultry_week_of(self.today)
        record = self._confirmed(self.coop, [2000])
        self.Weekly.search([('batch_id', '=', self.batch.id), ('indicator_id', '=', self.indicator.id),
                            ('week', '=', week)]).write({'source': 'manual', 'real_value': 1850})
        record.action_cancel()
        self.assertEqual(self._weekly(), [1850], 'Un semanal cargado a mano no se borra')

    def test_recompute_button_rebuilds_from_weighings(self):
        """El botón de la ficha rehace el indicador desde los partes confirmados (antes
        avisaba que había recalculado sin tocar nada)."""
        self._confirmed(self.coop, [1900, 2100, 2000])
        last_week = self.today - timedelta(days=7)
        self._confirmed(self.coop, [1800], date=last_week)
        # Un valor viejo de cuando el indicador salía de una OF, en una semana sin pesadas.
        product = self.env['product.product'].create({'name': 'Huevo Peso Test', 'type': 'consu'})
        production = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': 1, 'product_uom_id': product.uom_id.id})
        old_date = self.today - timedelta(days=30)
        self.Value._set_value(self.batch, self.coop, old_date, self.indicator, 55.0,
                              numerator=55.0, denominator=1.0, production=production)
        # Un valor diario cargado a mano por el Gestor, sin pesada ese día.
        manual_date = self.today - timedelta(days=50)
        self.Value._set_value(self.batch, self.coop, manual_date, self.indicator, 1700.0,
                              numerator=1700.0, denominator=1.0)
        self.assertEqual(self._weekly(old_date), [55.0])

        # Valores que ya no coinciden con los partes (p. ej. tras cambiar la fórmula).
        self.Value.search([('indicator_id', '=', self.indicator.id),
                           ('production_id', '=', False)]).write({'value': 999})
        self.indicator.write({'values_outdated': True})

        action = self.indicator.action_recompute_indicator()
        self.assertIn('2 días con Partes de Peso confirmados', action['params']['message'])
        self.assertFalse(self.indicator.values_outdated)
        self.assertEqual(self._daily(), [(2000, 6000, 3)])
        self.assertEqual(self._daily(last_week), [(1800, 1800, 1)])
        self.assertEqual(self._daily(old_date), [], 'El valor que venía de una OF se borra')
        self.assertEqual(self._weekly(old_date), [], 'y su semanal de origen Sistema también')
        self.assertEqual([v for v, _n, _d in self._daily(manual_date)], [999],
                         'Un valor sin pesada ni OF (carga manual) no se toca')

    def test_exceptional_weighing_is_left_out(self):
        """Una pesada excepcional se guarda pero no entra en los indicadores del lote."""
        routine = self._confirmed(self.coop, [1900, 2100, 2000])
        special = self._confirmed(self.coop2, [1000], exceptional=True)
        self.assertEqual(special.average_weight_g, 1000, 'Sus resultados propios se ven igual')
        self.assertEqual(self._daily(), [(2000, 6000, 3)], 'La excepcional no entra')

        # Marcarla o desmarcarla con el parte ya confirmado recalcula el día.
        routine.write({'is_exceptional': True, 'exceptional_reason': 'Re-pesada'})
        self.assertEqual(self._daily(), [], 'Con solo pesadas excepcionales el día queda sin valor')
        self.assertEqual(self._weekly(), [])
        special.write({'is_exceptional': False})
        self.assertEqual(self._daily(), [(1000, 1000, 1)])

        with self.assertRaises(ValidationError, msg='La marca pide el motivo'):
            special.write({'is_exceptional': True, 'exceptional_reason': ' '})

        # El botón de recálculo tampoco la toma.
        self.indicator.action_recompute_indicator()
        self.assertEqual(self._daily(), [(1000, 1000, 1)])

    def test_exceptional_is_not_the_previous_weighing(self):
        routine = self._confirmed(self.coop, [2000], date=self.today - timedelta(days=14))
        self._confirmed(self.coop, [1500, 1600], date=self.today - timedelta(days=7), exceptional=True)
        record = self.env['poultry.weight.record'].create({
            'coop_id': self.coop.id, 'batch_id': self.batch.id, 'date': self.today})
        self.assertEqual(record._poultry_previous_record(), routine,
                         'Generar líneas repite la última pesada de rutina, no la excepcional')

    def test_uniformity_indicator(self):
        """La actualización crea UNIFORMIDAD (%) y publica la historia de los partes."""
        Indicator = self.env['poultry.indicator']
        Indicator.with_context(active_test=False).search([
            '|', ('category', '=', 'uniformity'), ('formula_numerator', '=', 'uniform_birds')]).unlink()
        # Promedio 2125 g, banda ±10 % = ±212,5 g: entran 2100 y 2000, quedan afuera 1900 y 2500.
        record = self._confirmed(self.coop, [1900, 2100, 2000, 2500])
        self.assertEqual(record.uniformity_pct, 50)
        self._confirmed(self.coop2, [3000], exceptional=True)

        uniformity = Indicator._poultry_ensure_uniformity_indicator()
        self.assertEqual((uniformity.name, uniformity.uom_id.name, uniformity.formula_factor),
                         ('UNIFORMIDAD (%)', '%', '100'))
        values = self.Value.search([('indicator_id', '=', uniformity.id)])
        self.assertEqual([(v.date, v.value, v.numerator, v.denominator) for v in values],
                         [(self.today, 50, 200, 4)], 'Igual que la uniformidad del parte, sin la excepcional')
        weekly = self.Weekly.search([('indicator_id', '=', uniformity.id)])
        self.assertEqual(weekly.mapped('real_value'), [50])
        self.assertEqual(Indicator._poultry_ensure_uniformity_indicator(), uniformity,
                         'No se duplica si ya existe')

        # De ahí en más se publica sola al confirmar y se borra al cancelar.
        record.action_cancel()
        self.assertFalse(self.Value.search([('indicator_id', '=', uniformity.id)]))

    def test_empty_lines_do_not_count(self):
        """Las líneas sin peso se conservan al confirmar y no entran en los indicadores."""
        record = self.env['poultry.weight.record'].create({
            'coop_id': self.coop.id, 'batch_id': self.batch.id, 'date': self.today})
        wizard = self.env['poultry.weight.lines.wizard'].create({'record_id': record.id})
        wizard.mode = 'fixed'
        wizard.birds_per_cage = 5
        wizard.action_confirm()
        for line, weight in zip(record.line_ids.sorted('bird_no'), [1900, 2100, 2000]):
            line.weight_g = weight
        record.action_done()
        self.assertEqual((len(record.line_ids), record.planned_bird_count, record.bird_count), (5, 5, 3))
        self.assertEqual(self._daily(), [(2000, 6000, 3)], 'Dos aves sin peso no son aves de 0 g')

    def test_uniformity_from_the_phone(self):
        """Pesar desde el celular (operador de campo, poultry_mobile_set_weight) calcula la
        uniformidad igual que cargarla en la ficha."""
        operator = self.env['res.users'].create({
            'name': 'Operador Peso', 'login': 'operador_peso_test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('poultry_management.poultry_field_weighing').id])],
        })
        record = self.env['poultry.weight.record'].create({
            'coop_id': self.coop.id, 'batch_id': self.batch.id, 'date': self.today})
        wizard = self.env['poultry.weight.lines.wizard'].create({'record_id': record.id})
        wizard.mode = 'fixed'
        wizard.birds_per_cage = 4
        wizard.action_confirm()
        record.action_send()
        phone = record.with_user(operator)
        for line, weight in zip(record.line_ids.sorted('bird_no'), [1900, 2100, 2000, 2500]):
            phone.poultry_mobile_set_weight(line.id, weight)
        record.invalidate_recordset()
        self.assertEqual((record.bird_count, record.average_weight_g), (4, 2125))
        self.assertEqual(record.uniformity_pct, 50, 'Promedio 2125 g, banda ±10 %: entran 2100 y 2000')
