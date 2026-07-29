# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class PoultryCoopClose(models.Model):
    _name = 'poultry.coop.close'
    _description = 'Cierre de Galpón'
    _order = 'date desc, coop_id'

    name = fields.Char(string='Referencia', required=True, copy=False, index=True,
                       default='NUEVO', readonly=False,
                       help='Se genera automáticamente al crear el cierre')
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True,
                              domain="[('active', '=', True)]")
    date = fields.Date(string='Fecha', required=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('done', 'Confirmado'),
        ('cancel', 'Cancelado'),
    ], string='Estado', default='draft', required=True)

    egg_collection_ids = fields.One2many(
        'poultry.egg.collection', 'coop_close_id',
        string='Partes de Producción',
        help='Partes en estado Procesada incluidos en este cierre')
    unclassified_production_id = fields.Many2one(
        'mrp.production', string='OF Huevo sin Clasificar',
        readonly=True, copy=False)

    @api.model
    def _get_sequence_for_coop_close(self, coop_id):
        """Obtiene o crea una secuencia para cierres basada en el prefijo del galpón"""
        if not coop_id:
            return self.env['ir.sequence'].search(
                [('code', '=', 'poultry.coop.close')], limit=1)
        coop = self.env['poultry.coop'].browse(coop_id)
        if not coop.exists():
            return self.env['ir.sequence'].search(
                [('code', '=', 'poultry.coop.close')], limit=1)
        prefix = (coop.sequence_prefix or 'CLC').strip().upper() or 'CLC'
        sequence_code = f'poultry.coop.close.{prefix}'
        sequence = self.env['ir.sequence'].search(
            [('code', '=', sequence_code)], limit=1)
        if not sequence:
            sequence = self.env['ir.sequence'].create({
                'name': f'Secuencia de Cierre de Galpón - {prefix}',
                'code': sequence_code,
                'prefix': f'{prefix}-CLC-',
                'padding': 4,
                'number_increment': 1,
                'number_next': 1,
            })
        return sequence

    @api.model_create_multi
    def create(self, vals_list):
        """Genera nombre automático usando secuencia basada en el galpón"""
        if isinstance(vals_list, dict):
            vals_list = [vals_list]
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == 'NUEVO':
                coop_id = vals.get('coop_id')
                sequence = self._get_sequence_for_coop_close(coop_id)
                vals['name'] = (sequence.next_by_id() if sequence else None) or 'NUEVO'
        records = super().create(vals_list)
        for record in records:
            if record.name == 'NUEVO' or not record.name:
                sequence = self._get_sequence_for_coop_close(
                    record.coop_id.id if record.coop_id else None)
                if sequence:
                    record.write({'name': sequence.next_by_id()})
        return records

    @api.constrains('coop_id', 'date', 'state')
    def _check_unique_coop_date(self):
        """Solo validar unicidad para cierres en draft o done"""
        for record in self:
            if record.state in ('draft', 'done'):
                existing = self.search([
                    ('coop_id', '=', record.coop_id.id),
                    ('date', '=', record.date),
                    ('state', 'in', ('draft', 'done')),
                    ('id', '!=', record.id),
                ], limit=1)
                if existing:
                    raise ValidationError(
                        'Ya existe un cierre para el galpón %s en la fecha %s.'
                        % (record.coop_id.name, record.date)
                    )

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft_with_permission(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(
                    'Solo se pueden eliminar cierres en estado Borrador.')
            if not self.env.user.has_group(
                    'poultry_management.poultry_delete_coop_close'):
                raise UserError(
                    'No tiene permisos para eliminar cierres de galpón.')

    def action_confirm(self):
        """Crea la OF de huevo sin clasificar y pasa a done"""
        for record in self:
            if record.state != 'draft':
                raise UserError('Solo se puede confirmar un cierre en Borrador.')
            if not record.egg_collection_ids:
                raise UserError('No hay partes de producción vinculados.')

            production = record._create_unclassified_production()
            if production:
                record.write({
                    'unclassified_production_id': production.id,
                    'state': 'done',
                })
                if hasattr(production, 'coop_close_id'):
                    production.write({'coop_close_id': record.id})
            else:
                record.state = 'done'
        return True

    def _create_unclassified_production(self):
        """Crea la OF de huevo sin clasificar sumando huevos de los partes"""
        self.ensure_one()
        coop = self.coop_id
        if not coop.unclassified_egg_product_id or not coop.unclassified_egg_bom_id:
            return False

        total_eggs = 0.0
        for collection in self.egg_collection_ids.filtered(lambda c: c.state == 'done'):
            for line in collection.line_ids:
                if hasattr(line, 'total_produced_reference'):
                    total_eggs += line.total_produced_reference or 0.0

        if total_eggs <= 0:
            return False

        unclassified_product = coop.unclassified_egg_product_id
        unclassified_uom = unclassified_product.uom_id
        if not unclassified_uom:
            raise UserError(
                'El producto de huevo sin clasificar no tiene unidad de medida.')

        picking_type_id = coop.picking_type_id_unclassified.id if coop.picking_type_id_unclassified else False

        vals = {
            'product_id': unclassified_product.id,
            'product_qty': total_eggs,
            'product_uom_id': unclassified_uom.id,
            'bom_id': coop.unclassified_egg_bom_id.id,
            'coop_id': coop.id,
            'egg_collection_id': False,
            'origin': f'Cierre Galpón {coop.name} - {self.date}',
            # Fecha de Recolección/Postura: nace igual a la fecha del cierre, pero
            # desde acá todos los cálculos de la OF dependen de este campo (no del
            # cierre), y puede corregirse después (grupo Mortandad: Carga Manual).
            'poultry_collection_date': self.date,
        }
        if picking_type_id:
            vals['picking_type_id'] = picking_type_id

        production = self.env['mrp.production'].create(vals)
        production.action_confirm()
        production.qty_producing = production.product_qty
        return production

    def action_cancel(self):
        """Revierte el cierre: en draft elimina; en done desmantela OF y desvincula"""
        for record in self:
            if record.state == 'cancel':
                continue

            if record.state == 'draft':
                record.egg_collection_ids.write({'coop_close_id': False})
                record.unlink()
                continue

            if record.state == 'done' and record.unclassified_production_id:
                prod = record.unclassified_production_id
                if prod.state == 'done':
                    record._unbuild_production(prod)
                elif prod.state not in ('cancel',):
                    try:
                        if hasattr(prod, 'action_cancel'):
                            prod.action_cancel()
                        else:
                            prod.state = 'cancel'
                    except Exception:
                        pass
                if hasattr(prod, 'coop_close_id'):
                    prod.write({'coop_close_id': False})
                record.write({'unclassified_production_id': False})

            record.egg_collection_ids.write({'coop_close_id': False})
            record.state = 'cancel'
        return True

    def _unbuild_production(self, production):
        """Desmantela una orden de producción y la deja en estado completado"""
        if not production.location_dest_id:
            raise UserError('La orden no tiene ubicación de destino.')
        qty = production.qty_producing or production.product_qty
        if not qty:
            return
        loc = production.location_dest_id
        vals = {
            'mo_id': production.id,
            'product_id': production.product_id.id,
            'product_uom_id': production.product_uom_id.id,
            'product_qty': qty,
            'location_id': loc.id,
            'location_dest_id': loc.id,
        }
        Unbuild = self.env['mrp.unbuild']
        if 'company_id' in Unbuild._fields and getattr(production, 'company_id', False):
            vals['company_id'] = production.company_id.id
        unbuild = Unbuild.create(vals)
        # action_unbuild completa el desmantelado directamente (state='done')
        # action_validate verifica stock y puede abrir wizard si no hay suficiente
        if hasattr(unbuild, 'action_unbuild'):
            unbuild.action_unbuild()
        elif hasattr(unbuild, 'action_validate'):
            result = unbuild.action_validate()
            # Si action_validate devuelve un dict (wizard), forzar action_unbuild
            if isinstance(result, dict):
                unbuild.action_unbuild()
        elif hasattr(unbuild, 'button_validate'):
            unbuild.button_validate()

    def action_edit_wizard(self):
        """Abre el wizard para editar el cierre (solo en draft)"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError('Solo se puede editar un cierre en estado Borrador.')
        return {
            'name': 'Editar Cierre de Galpón',
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.coop.close.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_close_id': self.id,
                'default_coop_ids': [(6, 0, self.coop_id.ids)],
                'default_date': self.date,
            },
        }

    def _revert_from_unbuild(self):
        """Llamado cuando se desmantela manualmente la OF desde MRP"""
        for record in self:
            record.egg_collection_ids.write({'coop_close_id': False})
            if record.unclassified_production_id:
                record.unclassified_production_id.write({'coop_close_id': False})
            record.write({
                'unclassified_production_id': False,
                'state': 'cancel',
            })

    @api.model
    def _poultry_rebuild_all_indicator_values(self, date_from=None, date_to=None, coops=None):
        """Reconstruye desde cero (borra y recalcula) los valores reales derivados de
        Cierres de Galpón: Consumo (Alimento/Agua), Producción de Huevos (% Ave-Día,
        Huevos Acumulados Ave-Día), Mortandad, Masa de Huevo, Peso del Huevo, Viabilidad
        y Conversión Alimenticia (Alimento/Huevos y Alimento/Masa de Huevo).

        Siempre hace un rebuild completo del rango, nunca un recálculo incremental:
        el indicador acumulado depende del valor anterior guardado, así que recalcular
        fuera de orden o parcialmente corrompería la cadena de acumulados para todas
        las fechas posteriores. Procesa los Cierres de Galpón en orden cronológico
        GLOBAL (no por lote), porque un mismo día de un mismo galpón puede tocar la
        cadena de acumulados de varios lotes a la vez.

        El rango y el orden usan la FECHA EFECTIVA de cada cierre: la Fecha de
        Recolección/Postura de su OF si está cargada, si no la fecha del cierre
        (mismo criterio que mrp.production._poultry_target_date, que es la fecha a
        la que la OF imputó sus valores). Filtrar por la fecha del cierre dejaría
        afuera OFs cuya fecha se corrigió hacia adentro del rango, y viceversa.

        coops (opcional): acota el rebuild a los Cierres de esos galpones, para no
        recalcular toda la granja al corregir una sola OF. Se expande a los demás
        galpones donde estuvieron los lotes de esos galpones (un lote trasladado
        tiene su cadena de acumulados repartida entre varios galpones; recalcular
        solo uno la cortaría). Vacío/None = toda la granja (wizard de recálculo).

        No filtra por el estado MRP de la OF (Confirmada/Hecha/etc.): usa directamente
        product_qty y move_raw_ids, poblados desde que se crea la OF en
        _create_unclassified_production, sin importar si luego se marcó como Hecha.

        Los agregados semanales (poultry.batch.indicator.weekly.value) se recalculan
        solos como efecto secundario de poultry.batch.indicator.value._set_value; acá
        solo se borran los del rango antes de recalcular, para no dejar semanas
        obsoletas si algún día se les quita el dato diario que las sustentaba.
        """
        domain = [('unclassified_production_id', '!=', False)]
        if coops:
            initial_batches = self.env['poultry.batch.coop.line'].search([
                ('coop_id', 'in', coops.ids),
            ]).mapped('batch_id')
            expanded_coops = coops | initial_batches.mapped('coop_line_ids.coop_id')
            domain.append(('coop_id', 'in', expanded_coops.ids))
        candidates = self.search(domain)
        # Fecha efectiva por cierre; el filtro de rango se hace acá (no en el
        # domain) porque la fecha efectiva puede diferir de la del cierre.
        dated = []
        for close in candidates:
            eff = (close.unclassified_production_id.sudo().poultry_collection_date
                   or close.date)
            if date_from and eff < date_from:
                continue
            if date_to and eff > date_to:
                continue
            dated.append((eff, close.id, close))
        if not dated:
            return 0
        dated.sort(key=lambda item: (item[0], item[1]))
        closes = self.browse([item[2].id for item in dated])

        # NUNCA agregar acá las categorías 'weight' ni 'uniformity': sus valores reales
        # los publica el Parte de Registro de Peso (poultry.weight.record), no las OFs,
        # y este rebuild los borraría sin poder recalcularlos.
        #
        # Se incluyen las categorías históricas de los cálculos cableados Y, además,
        # cualquier indicador con FÓRMULA cuya fuente sea el Cierre de Galpón: un
        # indicador nuevo del motor puede tener una categoría que no esté en la lista
        # (o ninguna, el campo es opcional) y también hay que limpiarlo antes de
        # recalcular, si no quedarían valores viejos que el rebuild no repone.
        Indicator = self.env['poultry.indicator']
        weight_source_numerators = list(Indicator._POULTRY_WEIGHT_SOURCE_NUMERATORS)
        indicators = Indicator.search([
            ('formula_numerator', 'not in', weight_source_numerators),
            ('category', 'not in', ('weight', 'uniformity')),
            '|',
            ('category', 'in', ('feed_consumption', 'water_consumption', 'egg_production',
                                 'mortality', 'mortality_count', 'egg_mass', 'egg_weight',
                                 'viability', 'feed_conversion', 'feed_egg_mass_conversion')),
            ('formula_mode', '!=', False),
        ])
        affected_batches = self.env['poultry.batch.coop.line'].search([
            ('coop_id', 'in', closes.mapped('coop_id').ids),
        ]).mapped('batch_id')
        dates = [item[0] for item in dated]  # fechas EFECTIVAS (no close.date)
        if indicators and affected_batches:
            self.env['poultry.batch.indicator.value'].search([
                ('indicator_id', 'in', indicators.ids),
                ('batch_id', 'in', affected_batches.ids),
                ('date', '>=', min(dates)),
                ('date', '<=', max(dates)),
            ]).unlink()

            # Limpia también los agregados semanales del rango, ya que se derivan de
            # los valores diarios que se acaban de borrar y se van a recalcular. La
            # semana se calcula por lote (ancla en birth_date, ver poultry.batch.
            # _poultry_week_anchor), así que el rango puede variar de un lote a otro.
            # El rango se ensancha 1 semana para ambos lados: si la Fecha de
            # Nacimiento se corrigió desde el último recálculo, las filas viejas
            # pueden estar numeradas una semana más arriba o abajo y quedarían
            # huérfanas.
            Weekly = self.env['poultry.batch.indicator.weekly.value']
            for batch in affected_batches:
                if not batch.birth_date:
                    continue
                week_from = max(batch._poultry_week_of(min(dates)) - 1, 1)
                week_to = batch._poultry_week_of(max(dates)) + 1
                Weekly.search([
                    ('batch_id', '=', batch.id),
                    ('indicator_id', 'in', indicators.ids),
                    ('week', '>=', week_from),
                    ('week', '<=', week_to),
                    ('source', '=', 'system'),
                ]).unlink()

        count = 0
        for _eff, _close_id, close in dated:  # orden cronológico por fecha efectiva
            production = close.unclassified_production_id
            if production and production.coop_id:
                production._poultry_compute_all_indicator_values()
                count += 1
        return count
