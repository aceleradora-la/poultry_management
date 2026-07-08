# -*- coding: utf-8 -*-
"""Respalda poultry.genetics.standard antes del rediseño del modelo.

El modelo pasa de un esquema plano (semana + standard_type + standard_value)
a un esquema con indicador, versión, período y rango Bajo/Alto. Se confirmó
con el dueño del dato que las filas existentes en producción son de prueba,
por lo que se eliminan (ver post-migrate.py) -pero se respaldan primero en
una tabla aparte, por las dudas, ya que no se puede revertir un DELETE.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'poultry_genetics_standard'
        )
    """)
    if not cr.fetchone()[0]:
        return
    cr.execute("""
        CREATE TABLE IF NOT EXISTS poultry_genetics_standard_pre_19_0_1_5_0_backup AS
        TABLE poultry_genetics_standard
    """)
    cr.execute("SELECT count(*) FROM poultry_genetics_standard_pre_19_0_1_5_0_backup")
    _logger.info('Poultry: respaldadas %s filas de poultry.genetics.standard (esquema '
                 'anterior) en poultry_genetics_standard_pre_19_0_1_5_0_backup antes '
                 'del rediseño del modelo.', cr.fetchone()[0])

    # Confirmado con el dueño del dato: las filas existentes son de prueba. No hay una
    # correspondencia automática válida hacia el nuevo esquema (requiere criterio humano
    # para asignar indicador/versión), así que se eliminan para que _auto_init recree la
    # tabla con las nuevas columnas NOT NULL (version_id, indicator_id, period) sin fallar
    # por filas huérfanas. El respaldo de arriba queda como red de seguridad.
    cr.execute("DELETE FROM poultry_genetics_standard")
    _logger.info('Poultry: se eliminaron los estándares de genética existentes (esquema '
                 'anterior incompatible con el nuevo modelo; respaldo disponible en '
                 'poultry_genetics_standard_pre_19_0_1_5_0_backup).')
