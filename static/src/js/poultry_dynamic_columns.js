/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { FormRenderer } from "@web/views/form/form_renderer";
import { onMounted, onPatched } from "@odoo/owl";

// Renombra dinámicamente las columnas/labels del parte de producción con los
// nombres reales de las unidades de medida (uom_1_name / uom_2_name / uom_3_name).
//
// Odoo 19: el texto del header de la lista es `column.label` (antes se intentaba
// `column.title`). Los renderers ya no exponen `this.el` (usan refs), por eso se
// abandona el viejo enfoque de MutationObserver + this.el.

const LINE_MODEL = "poultry.egg.collection.line";
const COLLECTION_MODEL = "poultry.egg.collection";

// Campo de la lista -> [prefijo, índice de slot de UoM (0=PT, 1=PI, 2=Huevo)]
const LIST_COLUMN_SLOTS = {
    initial_box: ["Inicial", 0],
    initial_map: ["Inicial", 1],
    initial_egg: ["Inicial", 2],
    final_box: ["Bruto", 0],
    final_map: ["Bruto", 1],
    final_egg: ["Bruto", 2],
};

// Campo de total del form -> [prefijo, índice de slot de UoM]
const FORM_TOTAL_SLOTS = {
    total_initial_boxes: ["Total Inicial", 0],
    total_initial_maps: ["Total Inicial", 1],
    total_initial_eggs: ["Total Inicial", 2],
    total_final_boxes: ["Total Final", 0],
    total_final_maps: ["Total Final", 1],
    total_final_eggs: ["Total Final", 2],
    total_produced_boxes: ["Total Producido", 0],
    total_produced_maps: ["Total Producido", 1],
    total_produced_eggs: ["Total Producido", 2],
};

function uomSlotNames(data) {
    return [data?.uom_1_name || "", data?.uom_2_name || "", data?.uom_3_name || ""];
}

patch(ListRenderer.prototype, {
    // La clase base hace `this.columns = this.getActiveColumns()` dentro de su propio
    // onWillRender, reasignando el array en cada render. Enganchamos ese mismo método
    // para renombrar los labels sobre el array definitivo, evitando problemas de orden
    // de hooks. El header (t-foreach="columns" / column.label) toma los nombres reales.
    getActiveColumns() {
        const columns = super.getActiveColumns();
        const list = this.props.list;
        if (!list || list.resModel !== LINE_MODEL || !list.records || !list.records.length) {
            return columns;
        }
        const names = uomSlotNames(list.records[0].data);
        if (!names[0] && !names[1] && !names[2]) {
            return columns;
        }
        for (const column of columns) {
            const slot = LIST_COLUMN_SLOTS[column.name];
            if (slot && names[slot[1]]) {
                column.label = `${names[slot[1]]} ${slot[0]}`;
            }
        }
        return columns;
    },
});

patch(FormRenderer.prototype, {
    setup() {
        super.setup();
        const resModel = this.props.resModel || this.props.record?.resModel;
        if (resModel === COLLECTION_MODEL) {
            const update = () => this._poultryUpdateTotalLabels();
            onMounted(update);
            onPatched(update);
        }
    },

    _poultryUpdateTotalLabels() {
        try {
            const record = this.props.record;
            if (!record || !record.data) {
                return;
            }
            const form = document.querySelector(".o_form_view");
            if (!form) {
                return;
            }
            const names = uomSlotNames(record.data);
            for (const [field, [prefix, idx]] of Object.entries(FORM_TOTAL_SLOTS)) {
                if (!names[idx]) {
                    continue;
                }
                // El atributo for puede llevar sufijo único: usar prefijo de coincidencia.
                const label = form.querySelector(`label[for="${field}"]`)
                    || form.querySelector(`label[for^="${field}"]`);
                if (label) {
                    label.textContent = `${prefix} ${names[idx]}`;
                }
            }
        } catch {
            // Nunca romper el render del form por el renombrado de labels.
        }
    },
});
