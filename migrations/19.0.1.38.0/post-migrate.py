# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Elimina el parámetro poultry_management.week_start_day si quedó guardado.

    El ajuste "Inicio de la Semana de Vida" existió brevemente (19.0.1.37.0) y se
    quitó: la Semana de Vida ancla siempre en la Fecha de Nacimiento del lote (la
    granja carga como nacimiento el día desde el que quiere contar las semanas).
    Si alguien llegó a guardar el ajuste, el parámetro quedaría huérfano en BD."""
    cr.execute(
        "DELETE FROM ir_config_parameter WHERE key = 'poultry_management.week_start_day'")
    if cr.rowcount:
        _logger.info('Poultry: parámetro week_start_day huérfano eliminado.')
