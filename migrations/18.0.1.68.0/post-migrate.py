# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

# Mapeo de los cálculos CABLEADOS a su fórmula equivalente, derivado del inventario
# de los 21 bloques de mrp_production.py y poultry_weight_record.py. Es 1:1 y
# determinista: al recalcular, los números deben ser idénticos a los actuales.
#   (categoría, tipo de acumulación) -> (numerador, denominador, factor, modo)
FORMULA_MAP = {
    ('feed_consumption', 'none'): ('feed_g', 'live_birds', '1', 'daily'),
    ('water_consumption', 'none'): ('water_ml', 'live_birds', '1', 'daily'),
    ('egg_production', 'none'): ('eggs', 'live_birds', '100', 'daily'),
    ('egg_production', 'original_rate'): ('eggs', 'original_birds', '100', 'daily'),
    ('egg_production', 'live'): ('eggs', 'live_birds', '1', 'running_sum'),
    ('egg_production', 'housed'): ('eggs', 'housed_birds', '1', 'running_sum'),
    # El % de Mortandad divide por las aves vivas al INICIO del día (vivas al
    # cierre + muertas del día), no por las que quedaron.
    ('mortality', 'none'): ('dead_birds', 'live_birds_start', '100', 'daily'),
    ('mortality_count', 'none'): ('dead_birds', 'one', '1', 'daily'),
    ('mortality', 'live'): ('dead_birds', 'live_birds_start', '100', 'running_sum'),
    ('mortality', 'housed'): ('dead_birds', 'housed_birds', '100', 'running_sum'),
    ('mortality', 'original_cumulative'): ('dead_birds', 'original_birds', '100', 'running_sum'),
    # Viabilidad: foto del estado del lote (no suma corrida), sobre Aves Alojadas.
    # Se acepta con los dos tipos históricos ('housed' y 'original_cumulative').
    ('viability', 'housed'): ('live_birds', 'housed_or_original_birds', '100', 'snapshot'),
    ('viability', 'original_cumulative'): ('live_birds', 'housed_or_original_birds', '100', 'snapshot'),
    ('egg_mass', 'none'): ('egg_mass_g', 'live_birds', '1', 'daily'),
    ('egg_mass', 'housed'): ('egg_mass_kg', 'housed_birds', '1', 'running_sum'),
    ('egg_weight', 'none'): ('measured_egg_g', 'eggs_with_weight', '1', 'daily'),
    ('feed_conversion', 'none'): ('feed_kg', 'egg_units', '1', 'daily'),
    ('feed_conversion', 'ratio_cumulative'): ('feed_kg', 'egg_units', '1', 'ratio_cumulative'),
    ('feed_egg_mass_conversion', 'none'): ('feed_kg', 'egg_mass_kg', '1', 'daily'),
    ('feed_egg_mass_conversion', 'ratio_cumulative'): ('feed_kg', 'egg_mass_kg', '1', 'ratio_cumulative'),
    ('weight', 'none'): ('weighed_g', 'weighed_birds', '1', 'daily'),
    ('uniformity', 'none'): ('uniform_birds', 'weighed_birds', '100', 'daily'),
}


def migrate(cr, version):
    """Rellena la fórmula de los indicadores existentes con el equivalente exacto
    de su cálculo cableado, para que el motor produzca los mismos números.

    Guarda antes la configuración previa en poultry_indicator_formula_backup: es la
    red de seguridad para restaurar a mano si hiciera falta (no se borra). Para
    revertir un indicador puntual alcanza con vaciar su Modo de Cálculo, que lo
    devuelve al cálculo cableado; para revertir todo, ver los commits marcados
    '[motor-formulas N/6]'.

    No recalcula nada: los valores guardados siguen siendo los del cableado hasta
    que el usuario corra el wizard de Recálculo."""
    cr.execute("""
        CREATE TABLE IF NOT EXISTS poultry_indicator_formula_backup AS
        SELECT id, name, category, accumulation_type, now() AS backup_date
          FROM poultry_indicator
    """)

    updated = 0
    skipped = []
    cr.execute("SELECT id, name, category, accumulation_type FROM poultry_indicator")
    for indicator_id, name, category, accumulation_type in cr.fetchall():
        formula = FORMULA_MAP.get((category, accumulation_type))
        if not formula:
            skipped.append(f'{name} ({category}/{accumulation_type})')
            continue
        numerator, denominator, factor, mode = formula
        cr.execute("""
            UPDATE poultry_indicator
               SET formula_numerator = %s, formula_denominator = %s,
                   formula_factor = %s, formula_mode = %s
             WHERE id = %s
        """, (numerator, denominator, factor, mode, indicator_id))
        updated += 1

    _logger.info('Poultry: fórmula cargada en %s indicadores.', updated)
    if skipped:
        # Sin fórmula siguen usando el cálculo cableado: no se rompe nada, pero
        # conviene saber cuáles quedaron afuera del motor.
        _logger.warning(
            'Poultry: %s indicadores sin fórmula equivalente (siguen con el cálculo '
            'cableado): %s', len(skipped), ', '.join(skipped))
