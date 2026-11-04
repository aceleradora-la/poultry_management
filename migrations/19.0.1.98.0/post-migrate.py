# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Numera las aves de las líneas existentes dentro de cada jaula, en el orden en que
    se cargaron, como las numera ahora el asistente Generar Líneas."""
    if not version:
        return
    cr.execute("""
        UPDATE poultry_weight_record_line line
           SET bird_no = numbered.bird_no
          FROM (SELECT id,
                       row_number() OVER (PARTITION BY record_id, cage_id
                                          ORDER BY sequence, id) AS bird_no
                  FROM poultry_weight_record_line) numbered
         WHERE numbered.id = line.id
    """)
